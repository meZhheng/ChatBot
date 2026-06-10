from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterator

from app.services.conversation_history import ConversationHistoryStore


SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


@dataclass(frozen=True)
class ChatCompletion:
    session_id: str
    user_id: str | None
    role: str = "assistant"
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    usage: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "role": self.role,
            "content": self.content,
            "metadata": self.metadata,
            "usage": self.usage,
        }


class ChatRuntimeService:
    def __init__(self, chat_orchestrator, history_store: ConversationHistoryStore | None = None):
        self.chat_orchestrator = chat_orchestrator
        self.history_store = history_store

    def validate(self, *, message: str, session_id: str) -> tuple[str, str]:
        return self._validate_message(message), self._validate_session_id(session_id)

    def stream(
        self,
        *,
        message: str,
        session_id: str,
        user_id: str | None = None,
        channel: str = "web",
        platform: str | None = None,
        platform_user_id: str | None = None,
        platform_message_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Iterator[dict[str, Any]]:
        query = self._validate_message(message)
        session_id = self._validate_session_id(session_id)
        self._record_session(
            session_id=session_id,
            user_id=user_id,
            channel=channel,
            platform=platform,
            platform_user_id=platform_user_id,
            metadata=metadata,
        )
        self._record_message(
            session_id=session_id,
            user_id=user_id,
            role="user",
            content=query,
            channel=channel,
            platform=platform,
            platform_message_id=platform_message_id,
            event_type="input",
            raw={"type": "input", "session_id": session_id, "role": "user", "content": query},
        )
        last_output_event: dict[str, Any] | None = None

        try:
            for event in self.chat_orchestrator.execute_stream(query, session_id):
                if not event:
                    continue
                if event.get("type") == "output":
                    last_output_event = event
                yield event
            if last_output_event is not None:
                self._record_message(
                    session_id=session_id,
                    user_id=user_id,
                    role="assistant",
                    content=str(last_output_event.get("content") or ""),
                    channel=channel,
                    platform=platform,
                    event_type="output",
                    raw=last_output_event,
                )
        except Exception as exc:
            error_event = {
                "type": "error",
                "session_id": session_id,
                "role": "assistant",
                "content": f"抱歉，回复生成失败：{exc}",
            }
            self._record_message(
                session_id=session_id,
                user_id=user_id,
                role="assistant",
                content=error_event["content"],
                channel=channel,
                platform=platform,
                event_type="error",
                raw=error_event,
            )
            yield error_event

    def stream_ndjson(self, **kwargs) -> Iterator[str]:
        for event in self.stream(**kwargs):
            yield json.dumps(event, ensure_ascii=False) + "\n"

    def complete(self, **kwargs) -> ChatCompletion:
        output = ""
        output_deltas: list[str] = []
        metadata: dict[str, Any] = {}
        usage: dict[str, Any] = {}
        user_id = kwargs.get("user_id")
        session_id = ""

        for event in self.stream(**kwargs):
            session_id = str(event.get("session_id") or kwargs.get("session_id") or "")
            event_type = event.get("type")
            if event_type == "output_delta":
                output_deltas.append(str(event.get("content") or ""))
                if isinstance(event.get("metadata"), dict):
                    metadata = event["metadata"]
            elif event_type == "output":
                output = str(event.get("content") or "")
                if isinstance(event.get("metadata"), dict):
                    metadata = event["metadata"]
            elif event_type == "done":
                event_metadata = event.get("metadata")
                if isinstance(event_metadata, dict):
                    if isinstance(event_metadata.get("usage"), dict):
                        usage = event_metadata["usage"]
                    elif event_metadata:
                        metadata = event_metadata
            elif event_type == "error":
                output = str(event.get("content") or "")
                metadata = {"error": True}

        if not output:
            output = "".join(output_deltas).strip()
        if not session_id:
            session_id = str(kwargs.get("session_id") or "")
        return ChatCompletion(
            session_id=session_id,
            user_id=user_id,
            content=output,
            metadata=metadata,
            usage=usage,
        )

    def _record_session(
        self,
        *,
        session_id: str,
        user_id: str | None,
        channel: str,
        platform: str | None,
        platform_user_id: str | None,
        metadata: dict[str, Any] | None,
    ) -> None:
        if not self.history_store:
            return
        self.history_store.upsert_session(
            session_id=session_id,
            user_id=user_id,
            channel=channel,
            platform=platform,
            platform_user_id=platform_user_id,
            metadata=metadata,
        )

    def _record_message(
        self,
        *,
        session_id: str,
        user_id: str | None,
        role: str,
        content: str,
        channel: str,
        platform: str | None,
        platform_message_id: str | None = None,
        event_type: str | None = None,
        raw: dict[str, Any] | None = None,
    ) -> None:
        if not self.history_store:
            return
        self.history_store.add_message(
            session_id=session_id,
            user_id=user_id,
            role=role,
            content=content,
            channel=channel,
            platform=platform,
            platform_message_id=platform_message_id,
            event_type=event_type,
            raw=raw,
        )

    @staticmethod
    def _validate_message(message: str) -> str:
        query = message.strip()
        if not query:
            raise ValueError("消息不能为空。")
        return query

    @staticmethod
    def _validate_session_id(session_id: str) -> str:
        value = session_id.strip()
        if not SESSION_ID_PATTERN.fullmatch(value):
            raise ValueError("session_id 格式无效。")
        return value
