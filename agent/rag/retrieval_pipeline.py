from agent.rag.knowledge_base import KnowledgeBaseService


class RetrievalPipeline:
    def __init__(self, knowledge_base: KnowledgeBaseService):
        self.knowledge_base = knowledge_base

    def retrieve(self, query: str, top_k: int | None = None) -> list[dict]:
        return self.knowledge_base.retrieve(query, top_k=top_k)

    def get_retriever(self, top_k: int | None = None):
        return self.knowledge_base.get_retriever(top_k=top_k)
