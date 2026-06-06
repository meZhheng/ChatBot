import hashlib
import sqlite3
from pathlib import Path
from datetime import datetime

from langchain_chroma import Chroma
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from agent.utils.config_handler import get_env, load_rag_config


class TextHashService:
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
            CREATE TABLE IF NOT EXISTS processed_text_hashes (
                content_hash TEXT PRIMARY KEY,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self.sqlite.commit()

    def get_md5_hash(self, text: str) -> str:
        return hashlib.md5(text.encode()).hexdigest()

    def check_md5_hash(self, text: str) -> bool:
        content_hash = self.get_md5_hash(text)
        cursor = self.sqlite.execute(
            """
            INSERT INTO processed_text_hashes (content_hash)
            VALUES (?)
            ON CONFLICT(content_hash) DO NOTHING
            """,
            (content_hash,),
        )
        self.sqlite.commit()
        return cursor.rowcount == 1

    def list_md5_hashes(self) -> list[str]:
        rows = self.sqlite.execute(
            """
            SELECT content_hash, created_at
            FROM processed_text_hashes
            ORDER BY created_at, content_hash
            """
        ).fetchall()
        return [row["content_hash"] for row in rows]

    def close(self):
        self.sqlite.close()


class KnowledgeBaseService:
    def __init__(self, hash_service: TextHashService):
        rag_config = load_rag_config()
        storage_config = rag_config.get("storage", {})
        vector_store_config = rag_config.get("vector_store", {})
        qwen_config = rag_config.get("qwen", {})
        splitter_config = rag_config.get("text_splitter", {})
        retriever_config = rag_config.get("retriever", {})

        self.hash_service = hash_service
        self.min_split_length = splitter_config.get("min_split_length", 500)
        self.default_top_k = retriever_config.get("default_top_k", 3)

        chroma_persist_dir = storage_config.get("chroma_persist_dir", "data/chroma")
        Path(chroma_persist_dir).mkdir(parents=True, exist_ok=True)

        self.vector_store = Chroma(
            collection_name=vector_store_config.get("collection_name", "knowledge_base"),
            embedding_function=DashScopeEmbeddings(
                model=qwen_config.get("embedding_model", "text-embedding-v4"),
                dashscope_api_key=get_env("DASHSCOPE_API_KEY"),
            ),
            persist_directory=chroma_persist_dir,
        )
        self.spliter = RecursiveCharacterTextSplitter(
            chunk_size=splitter_config.get("chunk_size", 1000),
            chunk_overlap=splitter_config.get("chunk_overlap", 200),
            separators=splitter_config.get("separators", ["\n\n", "\n", " ", ""]),
            length_function=len,
        )

    def check_md5_hash(self, text: str) -> bool:
        return self.hash_service.check_md5_hash(text)

    def update_by_text(self, text: str, filename: str) -> bool:
        if not self.hash_service.check_md5_hash(text):
            return False

        if len(text) > self.min_split_length:
            chunks = self.spliter.split_text(text)
        else:
            chunks = [text]

        metadatas = [{
            "source": filename,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "operator": "admin"
        }] * len(chunks)

        self.vector_store.add_texts(
            texts=chunks,
            metadatas=metadatas
        )

        return True

    def list_chunks(self) -> list[dict]:
        result = self.vector_store.get(include=["documents", "metadatas"])
        ids = result.get("ids") or []
        documents = result.get("documents") or []
        metadatas = result.get("metadatas") or []

        chunks: list[dict] = []
        for chunk_id, text, metadata in zip(ids, documents, metadatas):
            chunks.append(
                {
                    "id": chunk_id,
                    "text": text,
                    "metadata": metadata or {},
                }
            )

        return chunks

    def retrieve(self, query: str, top_k: int | None = None) -> list[dict]:
        results = self.vector_store.similarity_search_with_score(query, k=top_k or self.default_top_k)
        retrieved = []
        for doc, score in results:
            retrieved.append(
                {
                    "id": doc.metadata.get("id", ""),
                    "text": doc.page_content,
                    "metadata": doc.metadata,
                    "score": score,
                }
            )
        return retrieved

    def get_retriever(self, top_k: int | None = None):
        return self.vector_store.as_retriever(
            search_kwargs={"k": top_k or self.default_top_k}
        )
