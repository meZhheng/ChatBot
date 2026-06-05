from datetime import datetime

from langchain.tools import tool
from langchain_tavily import TavilySearch

from agent.utils.config_handler import load_agent_config


agent_config = load_agent_config()
tavily_config = agent_config.get("tools", {}).get("tavily", {})
tavilySearch = TavilySearch(
  max_results=tavily_config.get("max_results", 5),
  topic=tavily_config.get("topic", "general")
)

@tool
def InternetSearchTool(query: str) -> str:
  """
  Search the internet for the given query.
  Args:
    query: the query to search for
  """
  return tavilySearch.invoke(query)

@tool
def VirtualSearchTool(query: str) -> str:
    """
    A virtual search tool that simulates searching the internet.
    Args:
        query: the query to search for
    """
    return f"这是一个虚拟搜索工具，模拟搜索互联网。你搜索的内容是：{query}。"

@tool
def get_current_time() -> str:
    """
    获取当前时间
    """
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

@tool
def get_weight(query: str) -> str:
    """
    获取重量信息的工具，返回query的重量信息。
    """
    return f"{query}的重量是10公斤。"

@tool
def get_distance(source: str, target: str) -> str:
    """
    获取两个地点之间的距离。
    """
    return f"{source}到{target}的距离是100公里。"