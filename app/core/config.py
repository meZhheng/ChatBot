from dataclasses import dataclass
from pathlib import Path

from agent.utils.config_handler import get_env, load_rag_config


rag_config = load_rag_config()
storage_config = rag_config.get("storage", {})
DEFAULT_SQLITE_PATH = Path(storage_config.get("sqlite_path", "data/sqlite/knowledge_base.sqlite"))


@dataclass(frozen=True)
class WeComConfig:
    corp_id: str | None
    agent_id: str | None
    corp_secret: str | None
    callback_token: str | None
    encoding_aes_key: str | None
    callback_encrypted: bool

    @property
    def callback_configured(self) -> bool:
        return bool(self.callback_token)

    @property
    def send_configured(self) -> bool:
        return bool(self.corp_id and self.agent_id and self.corp_secret)


def _parse_bool(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def get_wecom_config() -> WeComConfig:
    return WeComConfig(
        corp_id=get_env("WECOM_CORP_ID"),
        agent_id=get_env("WECOM_AGENT_ID"),
        corp_secret=get_env("WECOM_CORP_SECRET"),
        callback_token=get_env("WECOM_CALLBACK_TOKEN"),
        encoding_aes_key=get_env("WECOM_ENCODING_AES_KEY"),
        callback_encrypted=_parse_bool(get_env("WECOM_CALLBACK_ENCRYPTED", "false")),
    )
