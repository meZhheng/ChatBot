import hashlib
from logging import config
import sqlite3
from pathlib import Path
from datetime import datetime
from langchain_chroma import Chroma
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from .config import MemoryConfig

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
        self.config = MemoryConfig()
        self.hash_service = hash_service
        self.vector_store = Chroma(
            collection_name=self.config.collection_name,
            embedding_function=DashScopeEmbeddings(
                model=self.config.qwen_embedding_model, 
                dashscope_api_key=self.config.qwen_api_key
            ),
            persist_directory=self.config.chroma_persist_dir,
        )
        self.spliter = RecursiveCharacterTextSplitter(
            chunk_size=self.config.chunk_size,
            chunk_overlap=self.config.chunk_overlap,
            separators=self.config.separators,
            length_function=len,
        )

    def update_by_text(self, text: str, filename: str) -> bool:
        if not self.hash_service.check_md5_hash(text):
            return False

        if len(text) > self.config.min_split_length:
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

    def get_retriever(self, top_k: int = 3):
        return self.vector_store.as_retriever(
            search_kwargs={"k": top_k}
        )
