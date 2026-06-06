import os
from pathlib import Path

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


def get_env(name: str, default: str | None = None) -> str | None:
    return os.getenv(name, default)


def load_rag_config(config_file: str | Path | None = None) -> dict:
    return _load_yaml(config_file or _config_path("rag_config.yml"))


def load_prompts_config(config_file: str | Path | None = None) -> dict:
    return _load_yaml(config_file or _config_path("prompts_config.yml"))


def load_agent_config(config_file: str | Path | None = None) -> dict:
    return _load_yaml(config_file or _config_path("agent_config.yml"))
