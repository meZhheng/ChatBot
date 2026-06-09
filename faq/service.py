import hashlib
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from langchain_chroma import Chroma
from langchain_community.embeddings import DashScopeEmbeddings

from agent.utils.config_handler import get_env, rag_config
from agent.utils.logger_handler import logger

FAQ_STATUSES = {"active", "disabled", "deleted"}


class FaqService:
    def __init__(self, sqlite: sqlite3.Connection, vector_store: Any | None = None, config: dict | None = None):
        self.sqlite = sqlite
        self.sqlite.row_factory = sqlite3.Row
        self.config = config or rag_config
        self.vector_store = vector_store or self._create_vector_store()
        self.ensure_schema()

    def ensure_schema(self):
        self.sqlite.execute("PRAGMA foreign_keys = ON")
        self.sqlite.execute(
            """
            CREATE TABLE IF NOT EXISTS faq_items (
                faq_id TEXT PRIMARY KEY,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'default',
                tags TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                priority INTEGER NOT NULL DEFAULT 0,
                hit_count INTEGER NOT NULL DEFAULT 0,
                operator TEXT NOT NULL DEFAULT 'admin',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                deleted_at TEXT
            )
            """
        )
        self.sqlite.execute(
            """
            CREATE TABLE IF NOT EXISTS faq_question_variants (
                variant_id TEXT PRIMARY KEY,
                faq_id TEXT NOT NULL,
                question TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                operator TEXT NOT NULL DEFAULT 'admin',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                deleted_at TEXT,
                FOREIGN KEY (faq_id) REFERENCES faq_items(faq_id) ON DELETE CASCADE
            )
            """
        )
        self.sqlite.execute("CREATE INDEX IF NOT EXISTS idx_faq_items_status ON faq_items(status)")
        self.sqlite.execute("CREATE INDEX IF NOT EXISTS idx_faq_items_category ON faq_items(category)")
        self.sqlite.execute("CREATE INDEX IF NOT EXISTS idx_faq_items_priority ON faq_items(priority)")
        self.sqlite.execute("CREATE INDEX IF NOT EXISTS idx_faq_items_updated_at ON faq_items(updated_at)")
        self.sqlite.execute("CREATE INDEX IF NOT EXISTS idx_faq_variants_faq_id ON faq_question_variants(faq_id)")
        self.sqlite.execute("CREATE INDEX IF NOT EXISTS idx_faq_variants_status ON faq_question_variants(status)")
        self.sqlite.execute("CREATE INDEX IF NOT EXISTS idx_faq_variants_updated_at ON faq_question_variants(updated_at)")
        self.sqlite.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS faq_search_fts USING fts5(
                doc_id UNINDEXED,
                faq_id UNINDEXED,
                doc_type UNINDEXED,
                question,
                answer,
                category,
                tags
            )
            """
        )
        self.sqlite.commit()

    def create_item(
        self,
        question: str,
        answer: str,
        category: str = "default",
        tags: list[str] | None = None,
        priority: int = 0,
        operator: str = "admin",
        variants: list[str] | None = None,
    ) -> dict:
        question = self._clean_required(question)
        answer = self._clean_required(answer)
        category = self._clean_category(category)
        normalized_tags = self._normalize_tags(tags or [])
        operator = operator.strip() or "admin"
        now = self._current_timestamp()
        faq_id = self._faq_id(question, answer, now)

        with self.sqlite:
            self.sqlite.execute(
                """
                INSERT INTO faq_items (
                    faq_id, question, answer, category, tags, status, priority,
                    hit_count, operator, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, 'active', ?, 0, ?, ?, ?)
                """,
                (faq_id, question, answer, category, self._tags_to_storage(normalized_tags), priority, operator, now, now),
            )
            self._sync_standard_indexes(faq_id)
            for variant_question in self._unique_questions(variants or []):
                self._create_variant_in_tx(faq_id, variant_question, operator=operator, now=now)

        return self.get_item(faq_id) or {}

    def list_items(
        self,
        query: str | None = None,
        category: str | None = None,
        status: str | None = "active",
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        limit = self._clamp(limit, 1, 200)
        offset = max(0, offset)
        filters = []
        params: list[Any] = []

        if status:
            self._validate_status(status)
            filters.append("fi.status = ?")
            params.append(status)
        else:
            filters.append("fi.status != 'deleted'")

        if category and category.strip():
            filters.append("fi.category = ?")
            params.append(category.strip())

        if query and query.strip():
            like_query = f"%{query.strip()}%"
            filters.append(
                """
                (fi.question LIKE ? OR fi.answer LIKE ? OR fi.tags LIKE ? OR fi.category LIKE ?
                 OR EXISTS (
                    SELECT 1 FROM faq_question_variants fqv
                    WHERE fqv.faq_id = fi.faq_id
                      AND fqv.status != 'deleted'
                      AND fqv.question LIKE ?
                 ))
                """
            )
            params.extend([like_query, like_query, like_query, like_query, like_query])

        where_sql = " AND ".join(filters)
        count = self.sqlite.execute(
            f"SELECT COUNT(*) AS count FROM faq_items fi WHERE {where_sql}",
            params,
        ).fetchone()["count"]
        rows = self.sqlite.execute(
            f"""
            SELECT fi.*,
                   (
                       SELECT COUNT(*)
                       FROM faq_question_variants fqv
                       WHERE fqv.faq_id = fi.faq_id AND fqv.status != 'deleted'
                   ) AS variant_count
            FROM faq_items fi
            WHERE {where_sql}
            ORDER BY fi.priority DESC, fi.updated_at DESC, fi.faq_id
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        ).fetchall()
        return {"count": int(count), "items": [self._item_response(row, include_variants=False) for row in rows]}

    def get_item(self, faq_id: str) -> dict | None:
        row = self.sqlite.execute(
            """
            SELECT fi.*,
                   (
                       SELECT COUNT(*)
                       FROM faq_question_variants fqv
                       WHERE fqv.faq_id = fi.faq_id AND fqv.status != 'deleted'
                   ) AS variant_count
            FROM faq_items fi
            WHERE fi.faq_id = ? AND fi.status != 'deleted'
            """,
            (faq_id.strip(),),
        ).fetchone()
        if not row:
            return None
        return self._item_response(row, include_variants=True)

    def update_item(
        self,
        faq_id: str,
        question: str,
        answer: str,
        category: str = "default",
        tags: list[str] | None = None,
        priority: int = 0,
        status: str = "active",
        operator: str = "admin",
        variants: list[str] | None = None,
    ) -> dict | None:
        faq_id = faq_id.strip()
        question = self._clean_required(question)
        answer = self._clean_required(answer)
        category = self._clean_category(category)
        status = self._validate_status(status)
        normalized_tags = self._normalize_tags(tags or [])
        operator = operator.strip() or "admin"
        now = self._current_timestamp()

        existing = self._active_or_disabled_item(faq_id)
        if not existing:
            return None

        with self.sqlite:
            self.sqlite.execute(
                """
                UPDATE faq_items
                SET question = ?, answer = ?, category = ?, tags = ?, status = ?,
                    priority = ?, operator = ?, updated_at = ?, deleted_at = ?
                WHERE faq_id = ?
                """,
                (
                    question,
                    answer,
                    category,
                    self._tags_to_storage(normalized_tags),
                    status,
                    priority,
                    operator,
                    now,
                    now if status == "deleted" else None,
                    faq_id,
                ),
            )
            if variants is not None:
                self._replace_variants_in_tx(faq_id, variants, operator=operator, now=now)
            self._sync_standard_indexes(faq_id)
            self._sync_variant_indexes_for_faq(faq_id)

        return self.get_item(faq_id)

    def delete_item(self, faq_id: str) -> dict | None:
        faq_id = faq_id.strip()
        existing = self._active_or_disabled_item(faq_id)
        if not existing:
            return None

        now = self._current_timestamp()
        variant_ids = self._variant_ids_for_faq(faq_id)
        with self.sqlite:
            self.sqlite.execute(
                """
                UPDATE faq_items
                SET status = 'deleted', updated_at = ?, deleted_at = ?
                WHERE faq_id = ?
                """,
                (now, now, faq_id),
            )
            self.sqlite.execute(
                """
                UPDATE faq_question_variants
                SET status = 'deleted', updated_at = ?, deleted_at = ?
                WHERE faq_id = ? AND status != 'deleted'
                """,
                (now, now, faq_id),
            )
            self._delete_fts_doc(self._standard_doc_id(faq_id))
            for variant_id in variant_ids:
                self._delete_fts_doc(self._variant_doc_id(variant_id))
            self._delete_vectors([self._standard_doc_id(faq_id), *[self._variant_doc_id(variant_id) for variant_id in variant_ids]])

        return {"faq_id": faq_id, "deleted": True, "message": "FAQ 已删除。"}

    def create_variant(self, faq_id: str, question: str, operator: str = "admin") -> dict | None:
        faq_id = faq_id.strip()
        if not self._active_or_disabled_item(faq_id):
            return None
        now = self._current_timestamp()
        with self.sqlite:
            variant_id = self._create_variant_in_tx(faq_id, question, operator=operator, now=now)
        return self.get_variant(faq_id, variant_id)

    def get_variant(self, faq_id: str, variant_id: str) -> dict | None:
        row = self.sqlite.execute(
            """
            SELECT *
            FROM faq_question_variants
            WHERE faq_id = ? AND variant_id = ? AND status != 'deleted'
            """,
            (faq_id.strip(), variant_id.strip()),
        ).fetchone()
        if not row:
            return None
        return self._variant_response(row)

    def update_variant(self, faq_id: str, variant_id: str, question: str, status: str = "active", operator: str = "admin") -> dict | None:
        faq_id = faq_id.strip()
        variant_id = variant_id.strip()
        question = self._clean_required(question)
        status = self._validate_status(status)
        operator = operator.strip() or "admin"
        if status == "deleted":
            return self.delete_variant(faq_id, variant_id)

        existing = self.get_variant(faq_id, variant_id)
        if not existing:
            return None
        now = self._current_timestamp()
        with self.sqlite:
            self.sqlite.execute(
                """
                UPDATE faq_question_variants
                SET question = ?, status = ?, operator = ?, updated_at = ?, deleted_at = NULL
                WHERE faq_id = ? AND variant_id = ?
                """,
                (question, status, operator, now, faq_id, variant_id),
            )
            self._sync_variant_indexes(variant_id)
        return self.get_variant(faq_id, variant_id)

    def delete_variant(self, faq_id: str, variant_id: str) -> dict | None:
        faq_id = faq_id.strip()
        variant_id = variant_id.strip()
        existing = self.get_variant(faq_id, variant_id)
        if not existing:
            return None

        now = self._current_timestamp()
        with self.sqlite:
            self.sqlite.execute(
                """
                UPDATE faq_question_variants
                SET status = 'deleted', updated_at = ?, deleted_at = ?
                WHERE faq_id = ? AND variant_id = ?
                """,
                (now, now, faq_id, variant_id),
            )
            self._delete_fts_doc(self._variant_doc_id(variant_id))
            self._delete_vectors([self._variant_doc_id(variant_id)])
        return {"faq_id": faq_id, "variant_id": variant_id, "deleted": True, "message": "扩展问已删除。"}

    def retrieve(self, query: str, top_k: int = 5, category: str | None = None, include_disabled: bool = False) -> list[dict]:
        query = self._clean_required(query)
        top_k = self._clamp(top_k, 1, 20)
        logger.info(
            f"[FAQ检索]开始检索 query={query!r} top_k={top_k} category={category or '-'} include_disabled={include_disabled}"
        )

        bm25_hits = self._retrieve_bm25(query, top_k=top_k * 4, category=category, include_disabled=include_disabled)
        vector_hits = self._retrieve_vector(query, top_k=top_k * 4, category=category, include_disabled=include_disabled)
        logger.debug(
            f"[FAQ检索]召回完成 query={query!r} bm25_hits={len(bm25_hits)} vector_hits={len(vector_hits)}"
        )

        merged = self._merge_hits(bm25_hits, vector_hits)
        results = sorted(
            merged.values(),
            key=lambda item: (item["score"], item["priority"], item["updated_at"]),
            reverse=True,
        )[:top_k]

        if results:
            with self.sqlite:
                self.sqlite.executemany(
                    "UPDATE faq_items SET hit_count = hit_count + 1 WHERE faq_id = ?",
                    [(item["faq_id"],) for item in results],
                )
            refreshed = {row["faq_id"]: row["hit_count"] for row in self.sqlite.execute(
                f"SELECT faq_id, hit_count FROM faq_items WHERE faq_id IN ({','.join('?' for _ in results)})",
                [item["faq_id"] for item in results],
            ).fetchall()}
            for item in results:
                item["hit_count"] = int(refreshed.get(item["faq_id"], item["hit_count"]))

            top_hit = results[0]
            logger.info(
                "[FAQ检索]命中结果 "
                f"query={query!r} count={len(results)} top_faq_id={top_hit['faq_id']} "
                f"score={top_hit['score']} sources={','.join(top_hit['sources'])} "
                f"matched_doc_type={top_hit['matched_doc_type']} matched_question={top_hit['matched_question']!r}"
            )
            logger.debug(f"[FAQ检索]结果详情 query={query!r} results={self._loggable_results(results)}")
        else:
            logger.info(f"[FAQ检索]未命中 query={query!r}")

        return results

    def _create_vector_store(self):
        storage_config = self.config.get("storage", {})
        vector_store_config = self.config.get("vector_store", {})
        qwen_config = self.config.get("qwen", {})
        chroma_persist_dir = storage_config.get("chroma_persist_dir", "data/chroma")
        Path(chroma_persist_dir).mkdir(parents=True, exist_ok=True)
        return Chroma(
            collection_name=vector_store_config.get("faq_collection_name", "faq_questions"),
            embedding_function=DashScopeEmbeddings(
                model=qwen_config.get("embedding_model", "text-embedding-v4"),
                dashscope_api_key=get_env("DASHSCOPE_API_KEY"),
            ),
            persist_directory=chroma_persist_dir,
        )

    def _sync_standard_indexes(self, faq_id: str):
        row = self.sqlite.execute("SELECT * FROM faq_items WHERE faq_id = ?", (faq_id,)).fetchone()
        if not row:
            return
        doc_id = self._standard_doc_id(faq_id)
        if row["status"] != "active":
            self._delete_fts_doc(doc_id)
            self._delete_vectors([doc_id])
            return
        self._replace_fts_doc(
            doc_id=doc_id,
            faq_id=faq_id,
            doc_type="standard",
            question=row["question"],
            answer=row["answer"],
            category=row["category"],
            tags=row["tags"],
        )
        self._replace_vector_doc(
            doc_id=doc_id,
            text=self._standard_vector_text(row),
            metadata=self._vector_metadata(row, doc_type="standard"),
        )

    def _sync_variant_indexes(self, variant_id: str):
        row = self.sqlite.execute(
            """
            SELECT fqv.*, fi.answer, fi.category, fi.tags, fi.status AS faq_status
            FROM faq_question_variants fqv
            JOIN faq_items fi ON fi.faq_id = fqv.faq_id
            WHERE fqv.variant_id = ?
            """,
            (variant_id,),
        ).fetchone()
        if not row:
            return
        doc_id = self._variant_doc_id(variant_id)
        if row["status"] != "active" or row["faq_status"] != "active":
            self._delete_fts_doc(doc_id)
            self._delete_vectors([doc_id])
            return
        self._replace_fts_doc(
            doc_id=doc_id,
            faq_id=row["faq_id"],
            doc_type="variant",
            question=row["question"],
            answer=row["answer"],
            category=row["category"],
            tags=row["tags"],
        )
        self._replace_vector_doc(
            doc_id=doc_id,
            text=row["question"],
            metadata={
                "faq_id": row["faq_id"],
                "doc_type": "variant",
                "variant_id": row["variant_id"],
                "category": row["category"],
                "tags": row["tags"],
                "status": row["status"],
            },
        )

    def _sync_variant_indexes_for_faq(self, faq_id: str):
        for variant_id in self._variant_ids_for_faq(faq_id, include_deleted=True):
            self._sync_variant_indexes(variant_id)

    def _replace_fts_doc(self, doc_id: str, faq_id: str, doc_type: str, question: str, answer: str, category: str, tags: str):
        self._delete_fts_doc(doc_id)
        self.sqlite.execute(
            """
            INSERT INTO faq_search_fts (doc_id, faq_id, doc_type, question, answer, category, tags)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (doc_id, faq_id, doc_type, question, answer, category, tags),
        )

    def _delete_fts_doc(self, doc_id: str):
        self.sqlite.execute("DELETE FROM faq_search_fts WHERE doc_id = ?", (doc_id,))

    def _replace_vector_doc(self, doc_id: str, text: str, metadata: dict):
        self._delete_vectors([doc_id])
        self.vector_store.add_texts(texts=[text], metadatas=[metadata], ids=[doc_id])

    def _delete_vectors(self, ids: list[str]):
        if not ids:
            return
        try:
            self.vector_store.delete(ids=ids)
        except Exception:
            pass

    def _retrieve_bm25(self, query: str, top_k: int, category: str | None, include_disabled: bool) -> list[dict]:
        match_query = self._fts_query(query)
        if not match_query:
            return []
        filters = ["faq_search_fts MATCH ?"]
        params: list[Any] = [match_query]
        if category and category.strip():
            filters.append("fi.category = ?")
            params.append(category.strip())
        if include_disabled:
            filters.append("fi.status != 'deleted'")
        else:
            filters.append("fi.status = 'active'")
        where_sql = " AND ".join(filters)
        rows = self.sqlite.execute(
            f"""
            SELECT faq_search_fts.doc_id,
                   faq_search_fts.faq_id,
                   faq_search_fts.doc_type,
                   faq_search_fts.question AS matched_question,
                   bm25(faq_search_fts) AS raw_score,
                   fi.*
            FROM faq_search_fts
            JOIN faq_items fi ON fi.faq_id = faq_search_fts.faq_id
            WHERE {where_sql}
            ORDER BY raw_score ASC
            LIMIT ?
            """,
            [*params, top_k],
        ).fetchall()
        return [self._hit_from_row(row, source="bm25", score=self._bm25_to_positive(row["raw_score"])) for row in rows]

    def _retrieve_vector(self, query: str, top_k: int, category: str | None, include_disabled: bool) -> list[dict]:
        try:
            results = self.vector_store.similarity_search_with_score(query, k=top_k)
        except Exception as e:
            logger.warning(f"[FAQ检索]向量召回失败 query={query!r} reason={e}")
            return []

        hits = []
        for doc, distance in results:
            metadata = doc.metadata or {}
            faq_id = metadata.get("faq_id")
            if not faq_id:
                continue
            row = self._active_or_disabled_item(faq_id) if include_disabled else self._active_item(faq_id)
            if not row:
                continue
            if category and category.strip() and row["category"] != category.strip():
                continue
            status = metadata.get("status")
            if not include_disabled and status != "active":
                continue
            hits.append(
                self._hit_from_row(
                    row,
                    source="vector",
                    score=self._vector_to_positive(distance),
                    doc_id=metadata.get("variant_id") and self._variant_doc_id(metadata["variant_id"]) or self._standard_doc_id(faq_id),
                    doc_type=metadata.get("doc_type", "standard"),
                    matched_question=row["question"] if metadata.get("doc_type") == "standard" else doc.page_content,
                )
            )
            if len(hits) >= top_k:
                break
        return hits

    def _merge_hits(self, bm25_hits: list[dict], vector_hits: list[dict]) -> dict[str, dict]:
        merged: dict[str, dict] = {}
        for hits, source in ((bm25_hits, "bm25"), (vector_hits, "vector")):
            seen_faq_ids: set[str] = set()
            for rank, hit in enumerate(hits, start=1):
                faq_id = hit["faq_id"]
                if faq_id in seen_faq_ids:
                    continue
                seen_faq_ids.add(faq_id)

                item = merged.setdefault(faq_id, self._result_from_hit(hit))
                rrf_score = self._rrf_score(rank)
                if source == "bm25":
                    item["bm25_score"] = max(item["bm25_score"], hit["score"])
                    item["normalized_bm25_score"] = max(item["normalized_bm25_score"], rrf_score)
                else:
                    item["vector_score"] = max(item["vector_score"], hit["score"])
                    item["normalized_vector_score"] = max(item["normalized_vector_score"], rrf_score)
                if source not in item["sources"]:
                    item["sources"].append(source)
                if hit["score"] >= item["matched_score"]:
                    item["matched_question"] = hit["matched_question"]
                    item["matched_doc_type"] = hit["doc_type"]
                    item["matched_doc_id"] = hit["doc_id"]
                    item["matched_score"] = hit["score"]

        for item in merged.values():
            priority_boost = min(max(item["priority"], 0), 100) / 1000
            item["score"] = round(item["normalized_bm25_score"] + item["normalized_vector_score"] + priority_boost, 6)
            item["bm25_score"] = round(item["bm25_score"], 6)
            item["vector_score"] = round(item["vector_score"], 6)
            item["sources"] = sorted(item["sources"])
        return merged

    def _rrf_score(self, rank: int, k: int = 60) -> float:
        return 1.0 / (k + rank)

    def _loggable_results(self, results: list[dict]) -> list[dict]:
        return [
            {
                "rank": rank,
                "faq_id": item["faq_id"],
                "score": item["score"],
                "sources": item["sources"],
                "matched_doc_type": item["matched_doc_type"],
                "matched_question": item["matched_question"],
                "category": item["category"],
            }
            for rank, item in enumerate(results, start=1)
        ]

    def _result_from_hit(self, hit: dict) -> dict:
        return {
            "faq_id": hit["faq_id"],
            "question": hit["question"],
            "answer": hit["answer"],
            "category": hit["category"],
            "tags": hit["tags"],
            "status": hit["status"],
            "priority": hit["priority"],
            "hit_count": hit["hit_count"],
            "updated_at": hit["updated_at"],
            "matched_question": hit["matched_question"],
            "matched_doc_type": hit["doc_type"],
            "matched_doc_id": hit["doc_id"],
            "matched_score": hit["score"],
            "sources": [],
            "score": 0.0,
            "bm25_score": 0.0,
            "vector_score": 0.0,
            "normalized_bm25_score": 0.0,
            "normalized_vector_score": 0.0,
        }

    def _hit_from_row(
        self,
        row: sqlite3.Row,
        source: str,
        score: float,
        doc_id: str | None = None,
        doc_type: str | None = None,
        matched_question: str | None = None,
    ) -> dict:
        return {
            "faq_id": row["faq_id"],
            "question": row["question"],
            "answer": row["answer"],
            "category": row["category"],
            "tags": self._tags_from_storage(row["tags"]),
            "status": row["status"],
            "priority": int(row["priority"]),
            "hit_count": int(row["hit_count"]),
            "updated_at": row["updated_at"],
            "doc_id": doc_id or row["doc_id"],
            "doc_type": doc_type or row["doc_type"],
            "matched_question": matched_question or row["matched_question"],
            "source": source,
            "score": float(score),
        }

    def _create_variant_in_tx(self, faq_id: str, question: str, operator: str, now: str) -> str:
        question = self._clean_required(question)
        operator = operator.strip() or "admin"
        variant_id = self._variant_id(faq_id, question, now)
        self.sqlite.execute(
            """
            INSERT INTO faq_question_variants (
                variant_id, faq_id, question, status, operator, created_at, updated_at
            )
            VALUES (?, ?, ?, 'active', ?, ?, ?)
            """,
            (variant_id, faq_id, question, operator, now, now),
        )
        self._sync_variant_indexes(variant_id)
        return variant_id

    def _replace_variants_in_tx(self, faq_id: str, variants: list[str], operator: str, now: str):
        old_variant_ids = self._variant_ids_for_faq(faq_id)
        self.sqlite.execute(
            """
            UPDATE faq_question_variants
            SET status = 'deleted', updated_at = ?, deleted_at = ?
            WHERE faq_id = ? AND status != 'deleted'
            """,
            (now, now, faq_id),
        )
        for variant_id in old_variant_ids:
            self._delete_fts_doc(self._variant_doc_id(variant_id))
        self._delete_vectors([self._variant_doc_id(variant_id) for variant_id in old_variant_ids])
        for variant_question in self._unique_questions(variants):
            self._create_variant_in_tx(faq_id, variant_question, operator=operator, now=now)

    def _item_response(self, row: sqlite3.Row, include_variants: bool) -> dict:
        item = {
            "faq_id": row["faq_id"],
            "question": row["question"],
            "answer": row["answer"],
            "category": row["category"],
            "tags": self._tags_from_storage(row["tags"]),
            "status": row["status"],
            "priority": int(row["priority"]),
            "hit_count": int(row["hit_count"]),
            "operator": row["operator"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "deleted_at": row["deleted_at"],
            "variant_count": int(row["variant_count"] or 0),
        }
        if include_variants:
            item["variants"] = self._list_variants(row["faq_id"])
        return item

    def _variant_response(self, row: sqlite3.Row) -> dict:
        return {
            "variant_id": row["variant_id"],
            "faq_id": row["faq_id"],
            "question": row["question"],
            "status": row["status"],
            "operator": row["operator"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "deleted_at": row["deleted_at"],
        }

    def _list_variants(self, faq_id: str) -> list[dict]:
        rows = self.sqlite.execute(
            """
            SELECT *
            FROM faq_question_variants
            WHERE faq_id = ? AND status != 'deleted'
            ORDER BY updated_at DESC, variant_id
            """,
            (faq_id,),
        ).fetchall()
        return [self._variant_response(row) for row in rows]

    def _active_item(self, faq_id: str):
        return self.sqlite.execute("SELECT * FROM faq_items WHERE faq_id = ? AND status = 'active'", (faq_id,)).fetchone()

    def _active_or_disabled_item(self, faq_id: str):
        return self.sqlite.execute("SELECT * FROM faq_items WHERE faq_id = ? AND status != 'deleted'", (faq_id,)).fetchone()

    def _variant_ids_for_faq(self, faq_id: str, include_deleted: bool = False) -> list[str]:
        status_filter = "" if include_deleted else "AND status != 'deleted'"
        rows = self.sqlite.execute(
            f"SELECT variant_id FROM faq_question_variants WHERE faq_id = ? {status_filter}",
            (faq_id,),
        ).fetchall()
        return [row["variant_id"] for row in rows]

    def _standard_vector_text(self, row: sqlite3.Row) -> str:
        tags = row["tags"].replace(",", " ")
        return f"{row['question']}\n{row['answer']}\n{row['category']} {tags}".strip()

    def _vector_metadata(self, row: sqlite3.Row, doc_type: str) -> dict:
        return {
            "faq_id": row["faq_id"],
            "doc_type": doc_type,
            "variant_id": "",
            "category": row["category"],
            "tags": row["tags"],
            "status": row["status"],
        }

    def _clean_required(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("字段不能为空。")
        return value

    def _clean_category(self, category: str) -> str:
        return category.strip() or "default"

    def _normalize_tags(self, tags: list[str]) -> list[str]:
        normalized = []
        seen = set()
        for tag in tags:
            clean = str(tag).strip()
            if clean and clean not in seen:
                normalized.append(clean)
                seen.add(clean)
        return normalized

    def _tags_to_storage(self, tags: list[str]) -> str:
        return ",".join(self._normalize_tags(tags))

    def _tags_from_storage(self, tags: str | None) -> list[str]:
        if not tags:
            return []
        return [tag for tag in tags.split(",") if tag]

    def _unique_questions(self, questions: list[str]) -> list[str]:
        unique = []
        seen = set()
        for question in questions:
            clean = str(question).strip()
            if clean and clean not in seen:
                unique.append(clean)
                seen.add(clean)
        return unique

    def _validate_status(self, status: str) -> str:
        status = status.strip()
        if status not in FAQ_STATUSES:
            raise ValueError("status 无效。")
        return status

    def _clamp(self, value: int, minimum: int, maximum: int) -> int:
        return min(max(int(value), minimum), maximum)

    def _fts_query(self, query: str) -> str:
        tokens = [token.strip() for token in query.replace('"', " ").split() if token.strip()]
        if not tokens:
            return query.replace('"', " ").strip()
        return " OR ".join(f'"{token}"' for token in tokens)

    def _bm25_to_positive(self, raw_score: float) -> float:
        return abs(float(raw_score))

    def _vector_to_positive(self, distance: float) -> float:
        return 1.0 / (1.0 + max(float(distance), 0.0))

    def _faq_id(self, question: str, answer: str, now: str) -> str:
        digest = hashlib.sha256(f"{question}\n{answer}\n{now}".encode("utf-8")).hexdigest()
        return f"faq_{digest[:32]}"

    def _variant_id(self, faq_id: str, question: str, now: str) -> str:
        digest = hashlib.sha256(f"{faq_id}\n{question}\n{now}\n{uuid.uuid4().hex}".encode("utf-8")).hexdigest()
        return f"fqv_{digest[:32]}"

    def _standard_doc_id(self, faq_id: str) -> str:
        return f"faq:{faq_id}"

    def _variant_doc_id(self, variant_id: str) -> str:
        return f"variant:{variant_id}"

    def _current_timestamp(self) -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
