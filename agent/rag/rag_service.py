from pathlib import Path

from langchain_chroma import Chroma
from langchain_community.embeddings import DashScopeEmbeddings

from agent.rag.knowledge_base import KnowledgeBaseService, KnowledgeIndexStore
from agent.rag.retrieval_pipeline import RetrievalPipeline
from agent.rag.splitter import DocumentSplitter
from agent.utils.config_handler import get_env, prompts_config, rag_config

class RagService:
    def __init__(self, sqlite_path: str | Path):
        self.rag_config = rag_config
        self.prompts_config = prompts_config

        storage_config = self.rag_config.get("storage", {})
        vector_store_config = self.rag_config.get("vector_store", {})
        qwen_config = self.rag_config.get("qwen", {})
        retriever_config = self.rag_config.get("retriever", {})

        chroma_persist_dir = storage_config.get("chroma_persist_dir", "data/chroma")
        Path(chroma_persist_dir).mkdir(parents=True, exist_ok=True)

        self.index_store = KnowledgeIndexStore(sqlite_path)
        self.document_splitter = DocumentSplitter(self.rag_config.get("text_splitter", {}))
        self.vector_store = Chroma(
            collection_name=vector_store_config.get("collection_name", "knowledge_base_documents"),
            embedding_function=DashScopeEmbeddings(
                model=qwen_config.get("embedding_model", "text-embedding-v4"),
                dashscope_api_key=get_env("DASHSCOPE_API_KEY"),
            ),
            persist_directory=chroma_persist_dir,
        )
        self.knowledge_base = KnowledgeBaseService(
            self.index_store,
            self.document_splitter,
            self.vector_store,
            default_top_k=retriever_config.get("default_top_k", 3),
        )
        self.retrieval_pipeline = RetrievalPipeline(self.knowledge_base)

    @property
    def sqlite(self):
        return self.index_store.sqlite

    def close(self):
        self.index_store.close()

    def upload_document(
        self,
        text: str,
        filename: str,
        content_type: str | None = None,
        operator: str = "admin",
    ) -> dict:
        return self.knowledge_base.upload_document(text, filename, content_type=content_type, operator=operator)

    def list_documents(self) -> list[dict]:
        return self.knowledge_base.list_documents()

    def get_document(self, document_id: str) -> dict | None:
        return self.knowledge_base.get_document(document_id)

    def delete_document(self, document_id: str) -> dict | None:
        return self.knowledge_base.delete_document(document_id)

    def delete_chunk(self, document_id: str, chunk_id: str) -> dict | None:
        return self.knowledge_base.delete_chunk(document_id, chunk_id)

    def retrieve(self, query: str, top_k: int | None = None) -> list[dict]:
        return self.retrieval_pipeline.retrieve(query, top_k=top_k)
