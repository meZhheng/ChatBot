from utils.config_handler import load_prompts_config
from utils.path_tool import get_absolute_path
from utils.logger_handler import logger

prompts_config = load_prompts_config()

def load_prompts(prompt_name: str):
    try:
        prompt_path = get_absolute_path(prompts_config[prompt_name])
    except KeyError as e:
        logger.error(f"[读取提示{prompt_name}错误]在yaml配置项中没有main_prompt_path配置项, {str(e)}")
        raise e
    
    try:
        return open(prompt_path, "r", encoding="utf-8").read()
    except Exception as e:
        logger.error(f"[读取提示{prompt_name}错误]解析系统提示词错误, {str(e)}")
        raise e