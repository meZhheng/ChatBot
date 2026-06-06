from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

from agent.middleware import *
from agent.tools import get_current_time, get_distance, get_weight
from agent.utils.config_handler import get_env, load_agent_config, load_prompts_config


agent_config = load_agent_config()
prompts_config = load_prompts_config()
qwen_config = agent_config.get("qwen", {})
agent_prompts = prompts_config.get("agent", {})

agent = create_agent(
    model=ChatOpenAI(
        model=qwen_config.get("chat_model", "qwen3.6-flash"),
        api_key=get_env("DASHSCOPE_API_KEY"),
        base_url=qwen_config.get("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    ),
    tools=[get_current_time, get_weight, get_distance],
    middleware=[log_before_agent, log_after_agent, log_before_model, log_after_model, model_call_hook, monitor_tool],
    system_prompt=agent_prompts.get(
        "system_prompt",
        "你是一个严格遵循ReAct框架的客服智能体，必须按“思考->行动->观察->再思考”的流程解决问题。你需要尽可能利用现有的工具解决问题。",
    )
)


if __name__ == "__main__":
    query = {
        "messages": [
            {"role": "user", "content": "我想问一下商品k003的重量，以及从J001点到J002点的距离是多少？"}
        ]
    }

    for chunk in agent.stream(query, stream_mode="values"):
        latest_message = chunk["messages"][-1]
        if latest_message.content:
            print(f"{type(latest_message).__name__}: {latest_message.content}")
        tool_calls = getattr(latest_message, "tool_calls", None)
        if tool_calls:
            for tool_call in tool_calls:
                tool_name = tool_call.get("name")
                tool_args = tool_call.get("args")
                print(f"Tool Call: {tool_name}，参数：{tool_args}")
        print("-" * 50)
