from datetime import datetime
from pathlib import Path
from typing import Any

from langchain.tools import tool
from langchain_tavily import TavilySearch
from pydantic import BaseModel, Field

from agent.rag.rag_service import RagService
from agent.utils.config_handler import agent_config, rag_config


tavily_config = agent_config.get("tools", {}).get("tavily", {})
tavily_search = TavilySearch(
    max_results=tavily_config.get("max_results", 5),
    topic=tavily_config.get("topic", "general"),
)

storage_config = rag_config.get("storage", {})
rag = RagService(Path(storage_config.get("sqlite_path", "data/sqlite/knowledge_base.sqlite")))


class SearchInternetInput(BaseModel):
    query: str = Field(
        min_length=2,
        description="要联网检索的问题或关键词，建议包含限定词、时间范围或目标来源。",
    )


class RetrieveKnowledgeBaseInput(BaseModel):
    query: str = Field(
        min_length=2,
        description="要在本地知识库中检索的问题或关键词，应尽量贴近用户原始问题。",
    )
    top_k: int = Field(
        default=5,
        ge=1,
        le=20,
        description="返回的最相关知识片段数量，默认 5，范围 1-20。",
    )


class CurrentTimeInput(BaseModel):
    pass


@tool(
    "search_internet",
    args_schema=SearchInternetInput,
    description=(
        "联网搜索工具。用于回答需要最新信息、公开网页资料、新闻、政策、版本变化或本地知识库没有覆盖的问题。"
        "输入 query，输出 Tavily 搜索结果，通常包含标题、URL、摘要或相关内容。"
    ),
)
def search_internet(query: str) -> Any:
    return tavily_search.invoke(query)


@tool(
    "retrieve_knowledge_base",
    args_schema=RetrieveKnowledgeBaseInput,
    description=(
        "本地知识库检索工具。用于从已上传到 RAG 知识库的文档中查找与问题相关的片段。"
        "适合回答项目资料、内部文档、用户上传文件中的事实；不适合查询实时互联网信息。"
        "输入 query 和可选 top_k，输出结果列表；每条结果包含 text、metadata 和 score。"
    ),
)
def retrieve_knowledge_base(query: str, top_k: int = 5) -> list[dict]:
    return rag.retrieve(query=query, top_k=top_k)


@tool(
    "get_current_time",
    args_schema=CurrentTimeInput,
    description=(
        "获取当前本地日期和时间。用于用户询问现在时间、今天日期，或需要将相对时间转换为绝对时间时。"
        "无需输入参数，输出格式为 YYYY-MM-DD HH:MM:SS。"
    ),
)
def get_current_time() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
