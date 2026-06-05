import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "configs"


def _load_yaml(config_file: str | Path) -> dict:
    with open(config_file, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _config_path(filename: str) -> Path:
    return CONFIG_DIR / filename


def _get_nested(config: dict, keys: tuple[str, ...], default: Any = None) -> Any:
    value: Any = config
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            return default
        value = value[key]
    return value


def get_env(name: str, default: str | None = None) -> str | None:
    return os.getenv(name, default)


def env_override(value: Any, env_name: str) -> Any:
    return os.getenv(env_name, value)


def load_rag_config(config_file: str | Path | None = None) -> dict:
    return _load_yaml(config_file or _config_path("rag_config.yml"))


def load_prompts_config(config_file: str | Path | None = None) -> dict:
    return _load_yaml(config_file or _config_path("prompts_config.yml"))


def load_agent_config(config_file: str | Path | None = None) -> dict:
    return _load_yaml(config_file or _config_path("agent_config.yml"))


class MemoryConfig:
    def __init__(self):
        config = load_rag_config()

        self.chroma_persist_dir = env_override(
            _get_nested(config, ("storage", "chroma_persist_dir"), "data/chroma"),
            "CHROMA_PERSIST_DIR",
        )
        os.makedirs(self.chroma_persist_dir, exist_ok=True)

        self.sqlite_path = _get_nested(
            config,
            ("storage", "sqlite_path"),
            "data/sqlite/knowledge_base.sqlite",
        )
        self.history_store = _get_nested(
            config,
            ("storage", "history_store"),
            "memory/chat_history/{session_id}.json",
        )

        self.collection_name = _get_nested(
            config,
            ("vector_store", "collection_name"),
            "knowledge_base",
        )

        self.qwen_api_key = get_env("DASHSCOPE_API_KEY")
        self.qwen_base_url = env_override(
            _get_nested(
                config,
                ("qwen", "base_url"),
                "https://dashscope.aliyuncs.com/compatible-mode/v1",
            ),
            "QWEN_BASE_URL",
        )
        self.qwen_chat_model = env_override(
            _get_nested(config, ("qwen", "chat_model"), "qwen3.6-flash"),
            "QWEN_CHAT_MODEL",
        )
        self.qwen_embedding_model = env_override(
            _get_nested(config, ("qwen", "embedding_model"), "text-embedding-v4"),
            "QWEN_EMBEDDING_MODEL",
        )

        self.chunk_size = _get_nested(config, ("text_splitter", "chunk_size"), 1000)
        self.chunk_overlap = _get_nested(config, ("text_splitter", "chunk_overlap"), 200)
        self.separators = _get_nested(
            config,
            ("text_splitter", "separators"),
            ["\n\n", "\n", " ", ""],
        )
        self.min_split_length = _get_nested(config, ("text_splitter", "min_split_length"), 500)
        self.default_top_k = _get_nested(config, ("retriever", "default_top_k"), 3)
