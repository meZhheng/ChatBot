from langchain_core.prompts import ChatPromptTemplate
from langchain_core.prompts.chat import ChatPromptValue
from langchain_openai import ChatOpenAI
from langchain_core.runnables import RunnableLambda, RunnablePassthrough, RunnableWithMessageHistory
from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_community.chat_message_histories.file import FileChatMessageHistory

from agent.rag.retriever import KnowledgeBaseService
from agent.utils.config_handler import get_env, load_prompts_config, load_rag_config


class RagService:
    def __init__(self, knowledge_base: KnowledgeBaseService):
        self.knowledge_base = knowledge_base

        rag_config = load_rag_config()
        qwen_config = rag_config.get("qwen", {})
        prompts_config = load_prompts_config()
        rag_prompts = prompts_config.get("rag", {})
        self.prompt_template = ChatPromptTemplate.from_messages([
            (
                "system",
                rag_prompts.get(
                    "system_message",
                    "你是一个专业的客服，协助回答用户的问题。以我提供的参考资料为主，简洁和专业地回答用户的问题。如果参考资料中没有相关信息，可以直接说不知道。参考资料如下：{context}",
                ),
            ),
            ("placeholder", "{chat_history}"),
            ("human", rag_prompts.get("human_message", "用户的问题是：{query}")),
        ])

        self.chat_model = ChatOpenAI(
            model=qwen_config.get("chat_model", "qwen3.6-flash"),
            api_key=get_env("DASHSCOPE_API_KEY"),
            base_url=qwen_config.get("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        )

        self.chain = self.__get_chain()

    def __get_chain(self) -> RunnableWithMessageHistory:
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

        def print_prompt(prompt: ChatPromptValue) -> dict:
            print("===== Model Inputs =====")
            print(prompt.to_string())
            print("========================")
            return prompt

        def format_to_retriever(query: str) -> str:
            return query['query']

        def format_to_template(data: dict) -> dict:
            return {
                "chat_history": data['query']['chat_history'],
                "context": data['context'],
                "query": data['query']['query'],
            }

        chain = (
            {
                "query": RunnablePassthrough(),
                "context": format_to_retriever | retriever | format_documents,
            } | RunnableLambda(format_to_template) | self.prompt_template | print_prompt | self.chat_model | StrOutputParser()
        )

        history_chain = RunnableWithMessageHistory(
            chain,
            FileChatMessageHistory,
            input_messages_key="query",
            history_messages_key="chat_history"
        )

        return history_chain


if __name__ == "__main__":
    from agent.rag.retriever import TextHashService

    rag_config = load_rag_config()
    storage_config = rag_config.get("storage", {})
    hash_service = TextHashService(storage_config.get("sqlite_path", "data/sqlite/knowledge_base.sqlite"))
    knowledge_base = KnowledgeBaseService(hash_service)

    rag_service = RagService(knowledge_base)

    chat_config = {
        "configurable": {
            "session_id": storage_config.get(
                "history_store",
                "memory/chat_history/{session_id}.json",
            ).format(session_id="admin")
        }
    }

    query = "你好，我叫张横。"
    response = rag_service.chain.invoke(
        {"query": query},
        chat_config
    )
    print("用户问题：", query)
    print("Agent回答: ", response)

    query = "我叫什么名字？"
    response = rag_service.chain.invoke(
        {"query": query},
        chat_config
    )
    print("用户问题：", query)
    print("Agent回答: ", response)
