from langchain.agents.middleware import before_agent, before_model, after_agent, after_model, wrap_model_call, wrap_tool_call
from langchain.agents import AgentState
from langgraph.runtime import Runtime

@before_agent
def log_before_agent(state: AgentState, runtime: Runtime):
    print(f"[Before Agent Middleware] 智能体开始工作，输入了{len(state['messages'])}条消息。")

@after_agent
def log_after_agent(state: AgentState, runtime: Runtime):
    print(f"[After Agent Middleware] 智能体工作完成，输出了{len(state['messages'])}条消息。")

@before_model
def log_before_model(state: AgentState, runtime: Runtime):
    print(f"[Before Model Middleware] 模型即将处理消息，当前消息总数：{len(state['messages'])}。")

@after_model
def log_after_model(state: AgentState, runtime: Runtime):
    print(f"[After Model Middleware] 模型处理完成，当前消息总数：{len(state['messages'])}。")

@wrap_model_call
def model_call_hook(request, hanlder):
    print(f"[Model Call Middleware] 当前消息总数：{len(request.messages)}")

    return hanlder(request)

@wrap_tool_call
def monitor_tool(request, hanlder):
    print(f"[Tool Call Middleware] 工具：{request.tool_call['name']}，参数：{request.tool_call['args']}")

    return hanlder(request)