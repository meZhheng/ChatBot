from agent.rag.retrieval_pipeline import RetrievalPipeline


class RagService:
    def __init__(self, retrieval_pipeline: RetrievalPipeline):
        self.retrieval_pipeline = retrieval_pipeline

    def retrieve(self, query: str, top_k: int | None = None) -> list[dict]:
        return self.retrieval_pipeline.retrieve(query, top_k=top_k)

    def search_knowledge(self, query: str, top_k: int | None = None) -> list[dict]:
        return self.retrieve(query, top_k=top_k)
