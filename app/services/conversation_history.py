from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from typing import Any


class ConversationHistoryStore:
    def __init__(self, sqlite: sqlite3.Connection):
        self.sqlite = sqlite
        self.sqlite.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self._lock:
            self.sqlite.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT,
                    channel TEXT NOT NULL,
                    platform TEXT,
                    platform_user_id TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            self.sqlite.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_messages (
                    message_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    user_id TEXT,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    platform TEXT,
                    platform_message_id TEXT,
                    event_type TEXT,
                    raw_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            self.sqlite.execute(
                """
                CREATE TABLE IF NOT EXISTS platform_inbound_messages (
                    platform TEXT NOT NULL,
                    platform_message_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    user_id TEXT,
                    status TEXT NOT NULL,
                    error TEXT,
                    raw_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (platform, platform_message_id)
                )
                """
            )
            self.sqlite.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_chat_messages_session_created
                ON chat_messages(session_id, created_at)
                """
            )
            self.sqlite.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_chat_messages_user_created
                ON chat_messages(user_id, created_at)
                """
            )
            self.sqlite.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_messages_platform_msg
                ON chat_messages(platform, platform_message_id)
                WHERE platform_message_id IS NOT NULL
                """
            )
            self.sqlite.commit()

    def upsert_session(
        self,
        *,
        session_id: str,
        user_id: str | None = None,
        channel: str,
        platform: str | None = None,
        platform_user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        metadata_json = self._json(metadata or {})
        with self._lock:
            self.sqlite.execute(
                """
                INSERT INTO chat_sessions (
                    session_id, user_id, channel, platform, platform_user_id, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    user_id = COALESCE(excluded.user_id, chat_sessions.user_id),
                    channel = excluded.channel,
                    platform = COALESCE(excluded.platform, chat_sessions.platform),
                    platform_user_id = COALESCE(excluded.platform_user_id, chat_sessions.platform_user_id),
                    updated_at = CURRENT_TIMESTAMP,
                    metadata_json = excluded.metadata_json
                """,
                (session_id, user_id, channel, platform, platform_user_id, metadata_json),
            )
            self.sqlite.commit()

    def add_message(
        self,
        *,
        session_id: str,
        role: str,
        content: str,
        channel: str,
        user_id: str | None = None,
        platform: str | None = None,
        platform_message_id: str | None = None,
        event_type: str | None = None,
        raw: dict[str, Any] | None = None,
        message_id: str | None = None,
    ) -> str:
        message_id = message_id or uuid.uuid4().hex
        with self._lock:
            self.sqlite.execute(
                """
                INSERT OR IGNORE INTO chat_messages (
                    message_id,
                    session_id,
                    user_id,
                    role,
                    content,
                    channel,
                    platform,
                    platform_message_id,
                    event_type,
                    raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    session_id,
                    user_id,
                    role,
                    content,
                    channel,
                    platform,
                    platform_message_id,
                    event_type,
                    self._json(raw or {}),
                ),
            )
            self.sqlite.execute(
                "UPDATE chat_sessions SET updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
                (session_id,),
            )
            self.sqlite.commit()
        return message_id

    def mark_inbound_received(
        self,
        *,
        platform: str,
        platform_message_id: str,
        session_id: str,
        user_id: str | None = None,
        raw: dict[str, Any] | None = None,
    ) -> bool:
        with self._lock:
            cursor = self.sqlite.execute(
                """
                INSERT OR IGNORE INTO platform_inbound_messages (
                    platform, platform_message_id, session_id, user_id, status, raw_json
                ) VALUES (?, ?, ?, ?, 'received', ?)
                """,
                (platform, platform_message_id, session_id, user_id, self._json(raw or {})),
            )
            inserted = cursor.rowcount > 0
            self.sqlite.commit()
        return inserted

    def update_inbound_status(
        self,
        *,
        platform: str,
        platform_message_id: str,
        status: str,
        error: str | None = None,
    ) -> None:
        with self._lock:
            self.sqlite.execute(
                """
                UPDATE platform_inbound_messages
                SET status = ?, error = ?, updated_at = CURRENT_TIMESTAMP
                WHERE platform = ? AND platform_message_id = ?
                """,
                (status, error, platform, platform_message_id),
            )
            self.sqlite.commit()

    def list_messages_by_session(self, session_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.sqlite.execute(
                """
                SELECT * FROM chat_messages
                WHERE session_id = ?
                ORDER BY rowid
                """,
                (session_id,),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def list_messages_by_user(self, user_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.sqlite.execute(
                """
                SELECT * FROM chat_messages
                WHERE user_id = ?
                ORDER BY rowid
                """,
                (user_id,),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    @staticmethod
    def _json(value: dict[str, Any]) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        for key in ("metadata_json", "raw_json"):
            if key in data:
                try:
                    data[key] = json.loads(data[key] or "{}")
                except json.JSONDecodeError:
                    data[key] = {}
        return data
