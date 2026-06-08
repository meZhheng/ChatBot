import hashlib
import sqlite3
from datetime import datetime
from pathlib import Path

from langchain_chroma import Chroma
from langchain_community.embeddings import DashScopeEmbeddings

from agent.rag.splitter import DocumentSplitter
from agent.utils.config_handler import get_env, load_rag_config


class KnowledgeIndexStore:
    def __init__(self, sqlite_path: str | Path):
        self.sqlite_path = Path(sqlite_path)
        if self.sqlite_path != Path(":memory:"):
            self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        self.sqlite = sqlite3.connect(self.sqlite_path, check_same_thread=False)
        self.sqlite.row_factory = sqlite3.Row
        self.ensure_schema()

    def ensure_schema(self):
        self.sqlite.execute(
            """
            CREATE TABLE IF NOT EXISTS documents (
                document_id TEXT PRIMARY KEY,
                document_hash TEXT NOT NULL UNIQUE,
                filename TEXT NOT NULL,
                source TEXT NOT NULL,
                content_type TEXT,
                size_bytes INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'active',
                active_chunk_count INTEGER NOT NULL DEFAULT 0,
                total_chunk_count INTEGER NOT NULL DEFAULT 0,
                added_chunk_count INTEGER NOT NULL DEFAULT 0,
                reassigned_chunk_count INTEGER NOT NULL DEFAULT 0,
                operator TEXT NOT NULL DEFAULT 'admin',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                deleted_at TEXT
            )
            """
        )
        self.sqlite.execute(
            """
            CREATE TABLE IF NOT EXISTS chunks (
                chunk_id TEXT PRIMARY KEY,
                chunk_hash TEXT NOT NULL UNIQUE,
                document_id TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                text_length INTEGER NOT NULL DEFAULT 0,
                source TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                operator TEXT NOT NULL DEFAULT 'admin',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                deleted_at TEXT
            )
            """
        )
        self.sqlite.execute("CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status)")
        self.sqlite.execute("CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON chunks(document_id)")
        self.sqlite.execute("CREATE INDEX IF NOT EXISTS idx_chunks_status ON chunks(status)")
        self.sqlite.execute(
            "CREATE INDEX IF NOT EXISTS idx_chunks_document_index ON chunks(document_id, chunk_index)"
        )
        self.sqlite.commit()

    def close(self):
        self.sqlite.close()


class KnowledgeBaseService:
    def __init__(self, index_store: KnowledgeIndexStore, document_splitter: DocumentSplitter | None = None):
        rag_config = load_rag_config()
        storage_config = rag_config.get("storage", {})
        vector_store_config = rag_config.get("vector_store", {})
        qwen_config = rag_config.get("qwen", {})
        retriever_config = rag_config.get("retriever", {})

        self.index_store = index_store
        self.document_splitter = document_splitter or DocumentSplitter()
        self.default_top_k = retriever_config.get("default_top_k", 3)

        chroma_persist_dir = storage_config.get("chroma_persist_dir", "data/chroma")
        Path(chroma_persist_dir).mkdir(parents=True, exist_ok=True)

        self.vector_store = Chroma(
            collection_name=vector_store_config.get("collection_name", "knowledge_base_documents"),
            embedding_function=DashScopeEmbeddings(
                model=qwen_config.get("embedding_model", "text-embedding-v4"),
                dashscope_api_key=get_env("DASHSCOPE_API_KEY"),
            ),
            persist_directory=chroma_persist_dir,
        )

    def upload_document(
        self,
        text: str,
        filename: str,
        content_type: str | None = None,
        operator: str = "admin",
    ) -> dict:
        now = self._current_timestamp()
        filename = filename or "uploaded_document"
        document_hash = self._sha256(text)
        document_id = self._document_id(document_hash)
        chunks = self.document_splitter.split(text)
        unique_chunks = self._unique_chunks(chunks)
        unique_chunk_hashes = {chunk["chunk_hash"] for chunk in unique_chunks}
        sqlite = self.index_store.sqlite

        existing_document = sqlite.execute(
            """
            SELECT *
            FROM documents
            WHERE document_hash = ?
            """,
            (document_hash,),
        ).fetchone()

        if existing_document and existing_document["status"] == "active":
            active_chunk_hashes = {
                row["chunk_hash"]
                for row in sqlite.execute(
                    """
                    SELECT chunk_hash
                    FROM chunks
                    WHERE document_id = ? AND status = 'active'
                    """,
                    (existing_document["document_id"],),
                ).fetchall()
            }
            if active_chunk_hashes == unique_chunk_hashes:
                return {
                    "document_id": existing_document["document_id"],
                    "document_hash": existing_document["document_hash"],
                    "filename": existing_document["filename"],
                    "content_type": existing_document["content_type"],
                    "status": "duplicate",
                    "is_duplicate": True,
                    "chunk_count": len(chunks),
                    "active_chunk_count": existing_document["active_chunk_count"],
                    "added_chunk_count": 0,
                    "reassigned_chunk_count": 0,
                    "message": "文档 SHA-256 已存在，跳过重复入库。",
                }

        size_bytes = len(text.encode("utf-8"))
        added_chunk_count = 0
        reassigned_chunk_count = 0
        affected_document_ids: set[str] = set()

        with sqlite:
            if existing_document:
                sqlite.execute(
                    """
                    UPDATE documents
                    SET filename = ?,
                        source = ?,
                        content_type = ?,
                        size_bytes = ?,
                        status = 'active',
                        total_chunk_count = ?,
                        added_chunk_count = 0,
                        reassigned_chunk_count = 0,
                        operator = ?,
                        updated_at = ?,
                        deleted_at = NULL
                    WHERE document_id = ?
                    """,
                    (
                        filename,
                        filename,
                        content_type,
                        size_bytes,
                        len(chunks),
                        operator,
                        now,
                        document_id,
                    ),
                )
            else:
                sqlite.execute(
                    """
                    INSERT INTO documents (
                        document_id,
                        document_hash,
                        filename,
                        source,
                        content_type,
                        size_bytes,
                        status,
                        active_chunk_count,
                        total_chunk_count,
                        added_chunk_count,
                        reassigned_chunk_count,
                        operator,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, 'active', 0, ?, 0, 0, ?, ?, ?)
                    """,
                    (
                        document_id,
                        document_hash,
                        filename,
                        filename,
                        content_type,
                        size_bytes,
                        len(chunks),
                        operator,
                        now,
                        now,
                    ),
                )

            for chunk in unique_chunks:
                metadata = self._chunk_metadata(
                    chunk_id=chunk["chunk_id"],
                    chunk_hash=chunk["chunk_hash"],
                    document_id=document_id,
                    document_hash=document_hash,
                    chunk_index=chunk["chunk_index"],
                    source=filename,
                    created_at=now,
                    operator=operator,
                    text_length=len(chunk["text"]),
                )
                existing_chunk = sqlite.execute(
                    """
                    SELECT *
                    FROM chunks
                    WHERE chunk_hash = ?
                    """,
                    (chunk["chunk_hash"],),
                ).fetchone()

                if not existing_chunk:
                    self.vector_store.add_texts(
                        texts=[chunk["text"]],
                        metadatas=[metadata],
                        ids=[chunk["chunk_id"]],
                    )
                    sqlite.execute(
                        """
                        INSERT INTO chunks (
                            chunk_id,
                            chunk_hash,
                            document_id,
                            chunk_index,
                            text_length,
                            source,
                            status,
                            operator,
                            created_at,
                            updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
                        """,
                        (
                            chunk["chunk_id"],
                            chunk["chunk_hash"],
                            document_id,
                            chunk["chunk_index"],
                            len(chunk["text"]),
                            filename,
                            operator,
                            now,
                            now,
                        ),
                    )
                    added_chunk_count += 1
                    continue

                if existing_chunk["document_id"] != document_id and existing_chunk["status"] == "active":
                    affected_document_ids.add(existing_chunk["document_id"])
                    reassigned_chunk_count += 1
                elif existing_chunk["status"] != "active":
                    added_chunk_count += 1

                self._replace_vector_chunk(chunk["chunk_id"], chunk["text"], metadata)
                sqlite.execute(
                    """
                    UPDATE chunks
                    SET document_id = ?,
                        chunk_index = ?,
                        text_length = ?,
                        source = ?,
                        status = 'active',
                        operator = ?,
                        updated_at = ?,
                        deleted_at = NULL
                    WHERE chunk_id = ?
                    """,
                    (
                        document_id,
                        chunk["chunk_index"],
                        len(chunk["text"]),
                        filename,
                        operator,
                        now,
                        chunk["chunk_id"],
                    ),
                )

            for affected_document_id in affected_document_ids:
                self._refresh_document_counts(affected_document_id, now=now)

            active_chunk_count = self._active_chunk_count(document_id)
            document_status = self._document_status(active_chunk_count, len(chunks))
            sqlite.execute(
                """
                UPDATE documents
                SET status = ?,
                    active_chunk_count = ?,
                    total_chunk_count = ?,
                    added_chunk_count = ?,
                    reassigned_chunk_count = ?,
                    updated_at = ?,
                    deleted_at = NULL
                WHERE document_id = ?
                """,
                (
                    document_status,
                    active_chunk_count,
                    len(chunks),
                    added_chunk_count,
                    reassigned_chunk_count,
                    now,
                    document_id,
                ),
            )

        return {
            "document_id": document_id,
            "document_hash": document_hash,
            "filename": filename,
            "content_type": content_type,
            "status": document_status,
            "is_duplicate": False,
            "chunk_count": len(chunks),
            "active_chunk_count": active_chunk_count,
            "added_chunk_count": added_chunk_count,
            "reassigned_chunk_count": reassigned_chunk_count,
            "message": f"文档已入库：新增 {added_chunk_count} 个 chunks，转移 {reassigned_chunk_count} 个 chunks。",
        }

    def list_documents(self) -> list[dict]:
        rows = self.index_store.sqlite.execute(
            """
            SELECT *
            FROM documents
            WHERE status != 'deleted'
            ORDER BY updated_at DESC, document_id
            """
        ).fetchall()
        return [self._document_response(row) for row in rows]

    def get_document(self, document_id: str) -> dict | None:
        row = self.index_store.sqlite.execute(
            """
            SELECT *
            FROM documents
            WHERE document_id = ? AND status != 'deleted'
            """,
            (document_id.strip(),),
        ).fetchone()
        if not row:
            return None
        return self._document_response(row)

    def delete_document(self, document_id: str) -> dict | None:
        document_id = document_id.strip()
        if not document_id:
            return None

        sqlite = self.index_store.sqlite
        document = sqlite.execute(
            """
            SELECT *
            FROM documents
            WHERE document_id = ? AND status != 'deleted'
            """,
            (document_id,),
        ).fetchone()
        if not document:
            return None

        now = self._current_timestamp()
        active_chunks = sqlite.execute(
            """
            SELECT chunk_id
            FROM chunks
            WHERE document_id = ? AND status = 'active'
            """,
            (document_id,),
        ).fetchall()
        chunk_ids = [row["chunk_id"] for row in active_chunks]

        if chunk_ids:
            self.vector_store.delete(ids=chunk_ids)

        with sqlite:
            sqlite.execute(
                """
                UPDATE chunks
                SET status = 'deleted',
                    updated_at = ?,
                    deleted_at = ?
                WHERE document_id = ? AND status = 'active'
                """,
                (now, now, document_id),
            )
            sqlite.execute(
                """
                UPDATE documents
                SET status = 'deleted',
                    active_chunk_count = 0,
                    updated_at = ?,
                    deleted_at = ?
                WHERE document_id = ?
                """,
                (now, now, document_id),
            )

        return {
            "document_id": document_id,
            "deleted": True,
            "deleted_chunk_count": len(chunk_ids),
            "message": f"document 已删除，并从 Chroma 删除 {len(chunk_ids)} 个 active chunks。",
        }

    def delete_document_chunk(self, document_id: str, chunk_id: str) -> dict | None:
        document_id = document_id.strip()
        chunk_id = chunk_id.strip()
        if not document_id or not chunk_id:
            return None

        sqlite = self.index_store.sqlite
        chunk = sqlite.execute(
            """
            SELECT *
            FROM chunks
            WHERE document_id = ? AND chunk_id = ? AND status = 'active'
            """,
            (document_id, chunk_id),
        ).fetchone()
        if not chunk:
            return None

        now = self._current_timestamp()
        self.vector_store.delete(ids=[chunk_id])

        with sqlite:
            sqlite.execute(
                """
                UPDATE chunks
                SET status = 'deleted',
                    updated_at = ?,
                    deleted_at = ?
                WHERE chunk_id = ?
                """,
                (now, now, chunk_id),
            )
            document_status, remaining_chunks = self._refresh_document_counts(document_id, now=now)

        return {
            "document_id": document_id,
            "chunk_id": chunk_id,
            "deleted": True,
            "document_status": document_status,
            "remaining_chunks": remaining_chunks,
            "message": f"chunk 已从 document 和 Chroma 删除，当前 document 状态为 {document_status}。",
        }

    def retrieve(self, query: str, top_k: int | None = None) -> list[dict]:
        results = self.vector_store.similarity_search_with_score(query, k=top_k or self.default_top_k)
        retrieved = []
        for doc, score in results:
            metadata = doc.metadata or {}
            retrieved.append(
                {
                    "id": metadata.get("chunk_id", ""),
                    "text": doc.page_content,
                    "metadata": metadata,
                    "score": score,
                }
            )
        return retrieved

    def get_retriever(self, top_k: int | None = None):
        return self.vector_store.as_retriever(
            search_kwargs={"k": top_k or self.default_top_k}
        )

    def _document_response(self, row: sqlite3.Row) -> dict:
        document = dict(row)
        document["chunks"] = self._list_document_chunks(row["document_id"])
        return document

    def _list_document_chunks(self, document_id: str) -> list[dict]:
        rows = self.index_store.sqlite.execute(
            """
            SELECT *
            FROM chunks
            WHERE document_id = ? AND status = 'active'
            ORDER BY chunk_index, chunk_id
            """,
            (document_id,),
        ).fetchall()
        if not rows:
            return []

        ids = [row["chunk_id"] for row in rows]
        vector_result = self.vector_store.get(ids=ids, include=["documents", "metadatas"])
        vector_texts = {
            chunk_id: text
            for chunk_id, text in zip(vector_result.get("ids") or [], vector_result.get("documents") or [])
        }
        vector_metadatas = {
            chunk_id: metadata or {}
            for chunk_id, metadata in zip(vector_result.get("ids") or [], vector_result.get("metadatas") or [])
        }

        chunks = []
        for row in rows:
            metadata = vector_metadatas.get(row["chunk_id"]) or {
                "chunk_id": row["chunk_id"],
                "chunk_hash": row["chunk_hash"],
                "document_id": row["document_id"],
                "chunk_index": row["chunk_index"],
                "source": row["source"],
                "operator": row["operator"],
                "text_length": row["text_length"],
            }
            chunks.append(
                {
                    "id": row["chunk_id"],
                    "chunk_id": row["chunk_id"],
                    "chunk_hash": row["chunk_hash"],
                    "document_id": row["document_id"],
                    "chunk_index": row["chunk_index"],
                    "text": vector_texts.get(row["chunk_id"], ""),
                    "text_length": row["text_length"],
                    "source": row["source"],
                    "status": row["status"],
                    "operator": row["operator"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "deleted_at": row["deleted_at"],
                    "metadata": metadata,
                }
            )
        return chunks

    def _refresh_document_counts(self, document_id: str, now: str | None = None) -> tuple[str, int]:
        now = now or self._current_timestamp()
        document = self.index_store.sqlite.execute(
            """
            SELECT total_chunk_count, status
            FROM documents
            WHERE document_id = ?
            """,
            (document_id,),
        ).fetchone()
        if not document:
            return "deleted", 0
        if document["status"] == "deleted":
            return "deleted", 0

        active_chunk_count = self._active_chunk_count(document_id)
        document_status = self._document_status(active_chunk_count, document["total_chunk_count"])
        self.index_store.sqlite.execute(
            """
            UPDATE documents
            SET status = ?,
                active_chunk_count = ?,
                updated_at = ?,
                deleted_at = NULL
            WHERE document_id = ?
            """,
            (document_status, active_chunk_count, now, document_id),
        )
        return document_status, active_chunk_count

    def _active_chunk_count(self, document_id: str) -> int:
        row = self.index_store.sqlite.execute(
            """
            SELECT COUNT(*) AS count
            FROM chunks
            WHERE document_id = ? AND status = 'active'
            """,
            (document_id,),
        ).fetchone()
        return int(row["count"])

    def _replace_vector_chunk(self, chunk_id: str, text: str, metadata: dict):
        self.vector_store.delete(ids=[chunk_id])
        self.vector_store.add_texts(texts=[text], metadatas=[metadata], ids=[chunk_id])

    def _unique_chunks(self, chunks: list[str]) -> list[dict]:
        unique_by_hash = {}
        for index, text in enumerate(chunks):
            chunk_hash = self._sha256(text)
            unique_by_hash[chunk_hash] = {
                "text": text,
                "chunk_hash": chunk_hash,
                "chunk_id": self._chunk_id(chunk_hash),
                "chunk_index": index,
            }
        return sorted(unique_by_hash.values(), key=lambda chunk: chunk["chunk_index"])

    def _chunk_metadata(
        self,
        *,
        chunk_id: str,
        chunk_hash: str,
        document_id: str,
        document_hash: str,
        chunk_index: int,
        source: str,
        created_at: str,
        operator: str,
        text_length: int,
    ) -> dict:
        return {
            "chunk_id": chunk_id,
            "chunk_hash": chunk_hash,
            "document_id": document_id,
            "document_hash": document_hash,
            "chunk_index": chunk_index,
            "source": source,
            "created_at": created_at,
            "operator": operator,
            "text_length": text_length,
        }

    def _document_status(self, active_chunk_count: int, total_chunk_count: int) -> str:
        if active_chunk_count <= 0:
            return "empty"
        if active_chunk_count < total_chunk_count:
            return "partial"
        return "active"

    def _sha256(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _document_id(self, document_hash: str) -> str:
        return f"doc_{document_hash[:32]}"

    def _chunk_id(self, chunk_hash: str) -> str:
        return f"chk_{chunk_hash[:32]}"

    def _current_timestamp(self) -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
