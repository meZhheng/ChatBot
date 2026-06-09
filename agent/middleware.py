from typing import Callable

from langchain.agents import AgentState
from langchain.agents.middleware import after_agent, after_model, before_agent, before_model, dynamic_prompt, ModelRequest, wrap_model_call, wrap_tool_call
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.runtime import Runtime
from langgraph.types import Command

from agent.utils.config_handler import agent_config
from agent.utils.logger_handler import logger
from agent.utils.prompt_loader import load_prompts

@before_agent
def log_before_agent(state: AgentState, runtime: Runtime):
    logger.debug(f"[Before Agent Middleware] 智能体开始工作，输入了{len(state['messages'])}条消息。")

@after_agent
def log_after_agent(state: AgentState, runtime: Runtime):
    logger.debug(f"[After Agent Middleware] 智能体工作完成，输出了{len(state['messages'])}条消息。")

@before_model
def context_overflow_hook(state: AgentState, runtime: Runtime):
    context = getattr(runtime, "context", None)
    checkpointer = getattr(context, "checkpointer", None)
    memory_config = getattr(context, "memory_config", None) or agent_config.get("memory", {})
    session_id = getattr(getattr(runtime, "execution_info", None), "thread_id", None)

    if not checkpointer or not session_id:
        return None

    messages = state.get("messages", [])
    message_count = len(messages)
    checkpointer.update_message_count(session_id, message_count)

    max_messages = int(memory_config.get("max_messages_before_compression", 40))
    max_tokens = int(memory_config.get("max_tokens_before_compression", 8000))
    stats = checkpointer.get_session_stats(session_id)
    total_tokens = int(stats.get("current_total_tokens") or 0)

    reason = None
    if message_count > max_messages:
        reason = "message_count"
    elif total_tokens and total_tokens > max_tokens:
        reason = "token_count"

    if reason:
        checkpointer.mark_overflow(session_id, reason, message_count=message_count)
        logger.info(
            f"[短期记忆]会话{session_id}触发压缩钩子，原因：{reason}，消息数：{message_count}，当前token：{total_tokens}。"
        )

    return None

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

    result = hanlder(request)
    _record_usage(request, result)
    return result

def _record_usage(request, result):
    context = getattr(getattr(request, "runtime", None), "context", None)
    checkpointer = getattr(context, "checkpointer", None)
    session_id = getattr(getattr(getattr(request, "runtime", None), "execution_info", None), "thread_id", None)
    if not checkpointer or not session_id:
        return

    message = _usage_message(result)
    if not message:
        return

    usage = getattr(message, "usage_metadata", None) or {}
    response_metadata = getattr(message, "response_metadata", None) or {}
    token_usage = response_metadata.get("token_usage") or {}
    input_tokens = usage.get("input_tokens") or token_usage.get("prompt_tokens") or token_usage.get("input_tokens") or 0
    output_tokens = usage.get("output_tokens") or token_usage.get("completion_tokens") or token_usage.get("output_tokens") or 0
    total_tokens = usage.get("total_tokens") or token_usage.get("total_tokens") or (input_tokens + output_tokens)
    model_name = response_metadata.get("model_name") or response_metadata.get("model")

    if not total_tokens:
        return

    checkpointer.update_session_usage(
        session_id,
        input_tokens=int(input_tokens),
        output_tokens=int(output_tokens),
        total_tokens=int(total_tokens),
        model_name=model_name,
        message_count=len(getattr(request, "messages", [])),
    )


def _usage_message(result):
    if isinstance(result, AIMessage):
        return result
    model_response = getattr(result, "model_response", None)
    if model_response is not None:
        result = model_response
    messages = getattr(result, "result", None)
    if messages:
        for message in reversed(messages):
            if isinstance(message, AIMessage):
                return message
    return None


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