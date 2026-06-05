from langchain_core.prompts import ChatPromptTemplate
from langchain_community.chat_models.tongyi import ChatTongyi
from langchain_core.runnables import RunnablePassthrough
from langchain_core.documents import Document
from memory.knowledge_base import KnowledgeBaseService


class RagService:
    def __init__(self, knowledge_base: KnowledgeBaseService):
        self.knowledge_base = knowledge_base
        
        self.prompt_template = ChatPromptTemplate.from_messages([
            ("system", "你是一个专业的客服，协助回答用户的问题。以我提供的参考资料为主，简洁和专业地回答用户的问题。如果参考资料中没有相关信息，可以直接说不知道。参考资料如下：{context}"),
            ("human", "用户的问题是：{query}"),
        ])
        
        self.chat_model = ChatTongyi(
            model = self.knowledge_base.config.qwen_chat_model,
        )
        
        self.chain = self.__get_chain()

    def __get_chain(self):
        retriever = self.knowledge_base.get_retriever()

        def format_documents(documents: list[Document]) -> str:
            if not documents:
                return "无参考资料。"
            
            formatted = []
            for idx, doc in enumerate(documents):
                source = doc.metadata.get("source", "未知来源")
                text = doc.page_content
                formatted.append(f"参考资料{idx+1}（来源：{source}）：\n{text}")
            return "\n\n".join(formatted)
        
        chain = (
            {
                "query": RunnablePassthrough(),
                "context": retriever | format_documents,
            } | self.prompt_template
        )
        
        return chain

if __name__ == "__main__":
    from memory.config import MemoryConfig
    from memory.knowledge_base import TextHashService
    
    config = MemoryConfig()
    hash_service = TextHashService("data/sqlite/knowledge_base.sqlite")
    knowledge_base = KnowledgeBaseService(hash_service)
    
    rag_service = RagService(knowledge_base)
    
    query = "什么是A股？"
    response = rag_service.chain.invoke(query)
    print("用户问题：", query)
    print("RAG回答：", response)