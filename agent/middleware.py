from langchain.agents.middleware import before_agent, before_model, after_agent, after_model, wrap_model_call, wrap_tool_call, dynamic_prompt, ModelRequest
from langchain.agents import AgentState
from langgraph.runtime import Runtime
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command
from typing import Callable

from agent.utils.logger_handler import logger
from agent.utils.prompt_loader import load_prompts

@before_agent
def log_before_agent(state: AgentState, runtime: Runtime):
    logger.debug(f"[Before Agent Middleware] 智能体开始工作，输入了{len(state['messages'])}条消息。")

@after_agent
def log_after_agent(state: AgentState, runtime: Runtime):
    logger.debug(f"[After Agent Middleware] 智能体工作完成，输出了{len(state['messages'])}条消息。")

@before_model
def log_before_model(state: AgentState, runtime: Runtime):
    logger.info(f"[模型调用前]模型即将处理消息，当前消息总数：{len(state['messages'])}。")
    logger.debug(f"[模型调用前]{type(state['messages'][-1]).__name__}：{state['messages'][-1].content.strip()}")

    return None

@after_model
def log_after_model(state: AgentState, runtime: Runtime):
    logger.debug(f"[模型调用后] 模型处理完成，当前消息总数：{len(state['messages'])}。")

@wrap_model_call
def model_call_hook(request, hanlder):
    logger.debug(f"[模型调用] 当前消息总数：{len(request.messages)}")

    return hanlder(request)

@wrap_tool_call
def monitor_tool(
    request: ToolCallRequest,
    hanlder: Callable[[ToolCallRequest], ToolMessage | Command]
):
    logger.info(f"[工具调用]执行工具：{request.tool_call['name']}")
    logger.info(f"[工具调用]传入参数：{request.tool_call['args']}")

    try:
        result = hanlder(request)
        logger.info(f"[工具调用]工具{request.tool_call['name']}调用成功")
        return result
    except Exception as e:
        logger.error(f"工具{request.tool_call['name']}调用失败，原因：{str(e)}")
        raise e

@dynamic_prompt
def switch_prompt(request: ModelRequest):
    return load_prompts("system")