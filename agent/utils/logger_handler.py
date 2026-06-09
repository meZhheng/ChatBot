from agent.utils.path_tool import get_absolute_path
import os
import logging
from datetime import datetime

LOG_ROOT = get_absolute_path("logs")

os.makedirs(LOG_ROOT, exist_ok=True)

DEFAULT_LOG_FORMAT = logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s"
)

def get_logger(
    name: str = "agent",
    level=logging.INFO,
    file_level=logging.DEBUG,
    log_file=None,
)-> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(min(level, file_level))
    logger.propagate = False

    if logger.handlers:
        return logger

    # 控制台日志处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(DEFAULT_LOG_FORMAT)

    logger.addHandler(console_handler)

    # 文件日志处理器
    if log_file is None:
        log_file = os.path.join(LOG_ROOT, f"{name}_{datetime.now().strftime('%Y%m%d')}.log")

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(file_level)
    file_handler.setFormatter(DEFAULT_LOG_FORMAT)

    logger.addHandler(file_handler)

    return logger

logger = get_logger()