from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

from agent.middleware import *
from agent.tools import get_current_time, retrieve_knowledge_base, search_internet
from agent.utils.config_handler import get_env, agent_config, prompts_config

class AgentService:
    def __init__(self):
        qwen_config = agent_config.get("qwen", {})
        system_prompt = prompts_config.get("system", {})

        self.agent = create_agent(
            model=ChatOpenAI(
                model=qwen_config.get("chat_model", "qwen3.6-flash"),
                api_key=get_env("DASHSCOPE_API_KEY"),
                base_url=qwen_config.get("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            ),
            tools=[get_current_time, retrieve_knowledge_base, search_internet],
            middleware=[log_before_agent, log_after_agent, log_before_model, log_after_model, model_call_hook, monitor_tool],
            system_prompt=system_prompt
        )
    
    def execute_stream(self, query: str):
        input_dict = {
            "messages": [
                {"role": "user", "content": query}
            ]
        }
        
        for chunk in self.agent.stream(input_dict, stream_mode="values"):
            latest_message = chunk["messages"][-1]
            if latest_message.content:
                yield latest_message.content.strip() + "\n"


if __name__ == "__main__":
    pass
