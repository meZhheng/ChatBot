from __future__ import annotations

import hashlib
from typing import Any

from fastapi import BackgroundTasks
from starlette.concurrency import run_in_threadpool

from app.services.chat_runtime import ChatRuntimeService
from app.services.conversation_history import ConversationHistoryStore
from app.services.wecom import WeComClient, WeComIncomingMessage


class WeComChatService:
    platform = "wecom"

    def __init__(
        self,
        *,
        wecom_client: WeComClient,
        chat_runtime: ChatRuntimeService,
        history_store: ConversationHistoryStore,
        reply_mode: str = "complete",
    ):
        self.wecom_client = wecom_client
        self.chat_runtime = chat_runtime
        self.history_store = history_store
        self.reply_mode = reply_mode

    def schedule_message(self, incoming: WeComIncomingMessage, background_tasks: BackgroundTasks) -> None:
        session_id = self.session_id_for(incoming)
        user_id = self.user_id_for(incoming)
        platform_message_id = self.platform_message_id_for(incoming)
        platform_user_id = incoming.from_user_name or ""
        metadata = self.metadata_for(incoming)
        self.history_store.upsert_session(
            session_id=session_id,
            user_id=user_id,
            channel=self.platform,
            platform=self.platform,
            platform_user_id=platform_user_id,
            metadata=metadata,
        )

        if not self._is_supported_text(incoming):
            self._record_ignored(incoming, session_id, user_id, platform_message_id)
            return

        inserted = self.history_store.mark_inbound_received(
            platform=self.platform,
            platform_message_id=platform_message_id,
            session_id=session_id,
            user_id=user_id,
            raw=incoming.raw,
        )
        if not inserted:
            return

        background_tasks.add_task(self.process_message, incoming, session_id, user_id, platform_message_id)

    async def process_message(
        self,
        incoming: WeComIncomingMessage,
        session_id: str,
        user_id: str,
        platform_message_id: str,
    ) -> None:
        content = (incoming.content or "").strip()
        platform_user_id = incoming.from_user_name or ""
        metadata = self.metadata_for(incoming)
        self.history_store.update_inbound_status(
            platform=self.platform,
            platform_message_id=platform_message_id,
            status="processing",
        )
        try:
            if self.reply_mode == "stream":
                answer, reply_parts = await run_in_threadpool(
                    self._collect_streaming_reply_parts,
                    content,
                    session_id,
                    user_id,
                    platform_user_id,
                    platform_message_id,
                    metadata,
                )
                for reply_part in reply_parts:
                    await self._send_reply(platform_user_id, reply_part)
            else:
                completion = await run_in_threadpool(
                    self.chat_runtime.complete,
                    message=content,
                    session_id=session_id,
                    user_id=user_id,
                    channel=self.platform,
                    platform=self.platform,
                    platform_user_id=platform_user_id,
                    platform_message_id=platform_message_id,
                    metadata=metadata,
                )
                answer = completion.content
                await self._send_reply(platform_user_id, answer)
            self.history_store.update_inbound_status(
                platform=self.platform,
                platform_message_id=platform_message_id,
                status="completed",
            )
        except Exception as exc:
            self.history_store.update_inbound_status(
                platform=self.platform,
                platform_message_id=platform_message_id,
                status="failed",
                error=str(exc),
            )

    def user_id_for(self, incoming: WeComIncomingMessage) -> str:
        return f"wecom:{self._digest(incoming.from_user_name or '')}"

    def session_id_for(self, incoming: WeComIncomingMessage) -> str:
        agent_id = incoming.agent_id or "default"
        digest = self._digest(":".join([incoming.to_user_name or "", agent_id, incoming.from_user_name or ""]))
        return f"wecom:{agent_id}:{digest}"

    def platform_message_id_for(self, incoming: WeComIncomingMessage) -> str:
        if incoming.msg_id:
            return incoming.msg_id
        raw = "|".join(f"{key}={value}" for key, value in sorted(incoming.raw.items()))
        return f"missing:{self._digest(raw)}"

    def metadata_for(self, incoming: WeComIncomingMessage) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "to_user_name": incoming.to_user_name,
            "from_user_name": incoming.from_user_name,
            "create_time": incoming.create_time,
            "msg_type": incoming.msg_type,
            "msg_id": incoming.msg_id,
            "agent_id": incoming.agent_id,
        }

    async def _send_reply(self, touser: str, content: str) -> None:
        for part in self._split_text(content or "抱歉，我暂时无法生成回复。"):
            await self.wecom_client.send_text_message(touser=touser, content=part)

    def _collect_streaming_reply_parts(
        self,
        content: str,
        session_id: str,
        user_id: str,
        platform_user_id: str,
        platform_message_id: str,
        metadata: dict[str, Any],
    ) -> tuple[str, list[str]]:
        parts: list[str] = []
        reply_parts: list[str] = []
        buffer = ""
        for event in self.chat_runtime.stream(
            message=content,
            session_id=session_id,
            user_id=user_id,
            channel=self.platform,
            platform=self.platform,
            platform_user_id=platform_user_id,
            platform_message_id=platform_message_id,
            metadata=metadata,
        ):
            if event.get("type") != "output_delta":
                continue
            chunk = str(event.get("content") or "")
            parts.append(chunk)
            buffer += chunk
            if len(buffer) >= 500 and len(reply_parts) < 8:
                reply_parts.append(buffer)
                buffer = ""
        if buffer:
            reply_parts.append(buffer)
        return "".join(parts).strip(), reply_parts

    def _record_ignored(
        self,
        incoming: WeComIncomingMessage,
        session_id: str,
        user_id: str,
        platform_message_id: str,
    ) -> None:
        inserted = self.history_store.mark_inbound_received(
            platform=self.platform,
            platform_message_id=platform_message_id,
            session_id=session_id,
            user_id=user_id,
            raw=incoming.raw,
        )
        if not inserted:
            return
        reason = "unsupported_message_type" if incoming.msg_type != "text" else "blank_content"
        self.history_store.update_inbound_status(
            platform=self.platform,
            platform_message_id=platform_message_id,
            status="ignored",
            error=reason,
        )

    @staticmethod
    def _is_supported_text(incoming: WeComIncomingMessage) -> bool:
        return incoming.msg_type == "text" and bool((incoming.content or "").strip())

    @staticmethod
    def _digest(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]

    @staticmethod
    def _split_text(content: str, limit: int = 1800) -> list[str]:
        text = content.strip()
        if not text:
            return ["抱歉，我暂时无法生成回复。"]
        return [text[index : index + limit] for index in range(0, len(text), limit)]
