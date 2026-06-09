from __future__ import annotations

import random
import sqlite3
import threading
from collections.abc import AsyncIterator, Iterator, Sequence
from datetime import datetime, timezone
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    WRITES_IDX_MAP,
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    PendingWrite,
    get_checkpoint_id,
    get_checkpoint_metadata,
)


class SQLiteCheckpointSaver(BaseCheckpointSaver[str]):
    def __init__(self, sqlite: sqlite3.Connection):
        super().__init__()
        self.sqlite = sqlite
        self.sqlite.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self._lock:
            self.sqlite.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_checkpoints (
                    thread_id TEXT NOT NULL,
                    checkpoint_ns TEXT NOT NULL DEFAULT '',
                    checkpoint_id TEXT NOT NULL,
                    parent_checkpoint_id TEXT,
                    checkpoint_type TEXT NOT NULL,
                    checkpoint_blob BLOB NOT NULL,
                    metadata_type TEXT NOT NULL,
                    metadata_blob BLOB NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
                )
                """
            )
            self.sqlite.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_checkpoint_blobs (
                    thread_id TEXT NOT NULL,
                    checkpoint_ns TEXT NOT NULL DEFAULT '',
                    channel TEXT NOT NULL,
                    version TEXT NOT NULL,
                    type TEXT NOT NULL,
                    blob BLOB NOT NULL,
                    PRIMARY KEY (thread_id, checkpoint_ns, channel, version)
                )
                """
            )
            self.sqlite.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_checkpoint_writes (
                    thread_id TEXT NOT NULL,
                    checkpoint_ns TEXT NOT NULL DEFAULT '',
                    checkpoint_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    idx INTEGER NOT NULL,
                    channel TEXT NOT NULL,
                    type TEXT NOT NULL,
                    blob BLOB NOT NULL,
                    task_path TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
                )
                """
            )
            self.sqlite.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_session_stats (
                    session_id TEXT PRIMARY KEY,
                    current_input_tokens INTEGER NOT NULL DEFAULT 0,
                    current_output_tokens INTEGER NOT NULL DEFAULT 0,
                    current_total_tokens INTEGER NOT NULL DEFAULT 0,
                    last_model_name TEXT,
                    message_count INTEGER NOT NULL DEFAULT 0,
                    overflow_triggered INTEGER NOT NULL DEFAULT 0,
                    overflow_reason TEXT,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            self.sqlite.execute(
                "CREATE INDEX IF NOT EXISTS idx_agent_checkpoints_thread ON agent_checkpoints(thread_id, checkpoint_ns, checkpoint_id)"
            )
            self.sqlite.commit()

    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = get_checkpoint_id(config)

        with self._lock:
            if checkpoint_id:
                row = self.sqlite.execute(
                    """
                    SELECT *
                    FROM agent_checkpoints
                    WHERE thread_id = ? AND checkpoint_ns = ? AND checkpoint_id = ?
                    """,
                    (thread_id, checkpoint_ns, checkpoint_id),
                ).fetchone()
            else:
                row = self.sqlite.execute(
                    """
                    SELECT *
                    FROM agent_checkpoints
                    WHERE thread_id = ? AND checkpoint_ns = ?
                    ORDER BY checkpoint_id DESC
                    LIMIT 1
                    """,
                    (thread_id, checkpoint_ns),
                ).fetchone()

            if row is None:
                return None

            return self._row_to_tuple(row)

    def list(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> Iterator[CheckpointTuple]:
        params: list[Any] = []
        where: list[str] = []

        if config:
            where.append("thread_id = ?")
            params.append(config["configurable"]["thread_id"])
            checkpoint_ns = config["configurable"].get("checkpoint_ns")
            if checkpoint_ns is not None:
                where.append("checkpoint_ns = ?")
                params.append(checkpoint_ns)
            checkpoint_id = get_checkpoint_id(config)
            if checkpoint_id:
                where.append("checkpoint_id = ?")
                params.append(checkpoint_id)

        if before and (before_checkpoint_id := get_checkpoint_id(before)):
            where.append("checkpoint_id < ?")
            params.append(before_checkpoint_id)

        sql = "SELECT * FROM agent_checkpoints"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY checkpoint_id DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)

        with self._lock:
            rows = self.sqlite.execute(sql, params).fetchall()
            tuples = [self._row_to_tuple(row) for row in rows]

        for checkpoint_tuple in tuples:
            if filter and not all(
                checkpoint_tuple.metadata.get(key) == value for key, value in filter.items()
            ):
                continue
            yield checkpoint_tuple

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        parent_checkpoint_id = config["configurable"].get("checkpoint_id")
        checkpoint_copy = checkpoint.copy()
        values: dict[str, Any] = checkpoint_copy.pop("channel_values")

        with self._lock:
            for channel, version in new_versions.items():
                blob_type, blob = (
                    self.serde.dumps_typed(values[channel])
                    if channel in values
                    else ("empty", b"")
                )
                self.sqlite.execute(
                    """
                    INSERT OR REPLACE INTO agent_checkpoint_blobs (
                        thread_id, checkpoint_ns, channel, version, type, blob
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (thread_id, checkpoint_ns, channel, str(version), blob_type, blob),
                )

            checkpoint_type, checkpoint_blob = self.serde.dumps_typed(checkpoint_copy)
            metadata_type, metadata_blob = self.serde.dumps_typed(
                get_checkpoint_metadata(config, metadata)
            )
            self.sqlite.execute(
                """
                INSERT OR REPLACE INTO agent_checkpoints (
                    thread_id,
                    checkpoint_ns,
                    checkpoint_id,
                    parent_checkpoint_id,
                    checkpoint_type,
                    checkpoint_blob,
                    metadata_type,
                    metadata_blob,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    thread_id,
                    checkpoint_ns,
                    checkpoint["id"],
                    parent_checkpoint_id,
                    checkpoint_type,
                    checkpoint_blob,
                    metadata_type,
                    metadata_blob,
                    self._now(),
                ),
            )
            self.sqlite.commit()

        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint["id"],
            }
        }

    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = config["configurable"]["checkpoint_id"]

        with self._lock:
            for idx, (channel, value) in enumerate(writes):
                write_idx = WRITES_IDX_MAP.get(channel, idx)
                if write_idx >= 0:
                    exists = self.sqlite.execute(
                        """
                        SELECT 1
                        FROM agent_checkpoint_writes
                        WHERE thread_id = ?
                          AND checkpoint_ns = ?
                          AND checkpoint_id = ?
                          AND task_id = ?
                          AND idx = ?
                        """,
                        (thread_id, checkpoint_ns, checkpoint_id, task_id, write_idx),
                    ).fetchone()
                    if exists:
                        continue

                value_type, blob = self.serde.dumps_typed(value)
                self.sqlite.execute(
                    """
                    INSERT OR REPLACE INTO agent_checkpoint_writes (
                        thread_id,
                        checkpoint_ns,
                        checkpoint_id,
                        task_id,
                        idx,
                        channel,
                        type,
                        blob,
                        task_path
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        thread_id,
                        checkpoint_ns,
                        checkpoint_id,
                        task_id,
                        write_idx,
                        channel,
                        value_type,
                        blob,
                        task_path,
                    ),
                )
            self.sqlite.commit()

    def delete_thread(self, thread_id: str) -> None:
        with self._lock:
            self.sqlite.execute("DELETE FROM agent_checkpoint_writes WHERE thread_id = ?", (thread_id,))
            self.sqlite.execute("DELETE FROM agent_checkpoint_blobs WHERE thread_id = ?", (thread_id,))
            self.sqlite.execute("DELETE FROM agent_checkpoints WHERE thread_id = ?", (thread_id,))
            self.sqlite.execute("DELETE FROM agent_session_stats WHERE session_id = ?", (thread_id,))
            self.sqlite.commit()

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        return self.get_tuple(config)

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        for checkpoint_tuple in self.list(config, filter=filter, before=before, limit=limit):
            yield checkpoint_tuple

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        return self.put(config, checkpoint, metadata, new_versions)

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        return self.put_writes(config, writes, task_id, task_path)

    async def adelete_thread(self, thread_id: str) -> None:
        return self.delete_thread(thread_id)

    def get_next_version(self, current: str | None, channel: None) -> str:
        if current is None:
            current_version = 0
        else:
            current_version = int(str(current).split(".")[0])
        return f"{current_version + 1:032}.{random.random():016}"

    def update_session_usage(
        self,
        session_id: str,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        total_tokens: int = 0,
        model_name: str | None = None,
        message_count: int | None = None,
    ) -> None:
        with self._lock:
            existing = self.get_session_stats(session_id)
            self.sqlite.execute(
                """
                INSERT INTO agent_session_stats (
                    session_id,
                    current_input_tokens,
                    current_output_tokens,
                    current_total_tokens,
                    last_model_name,
                    message_count,
                    overflow_triggered,
                    overflow_reason,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    current_input_tokens = excluded.current_input_tokens,
                    current_output_tokens = excluded.current_output_tokens,
                    current_total_tokens = excluded.current_total_tokens,
                    last_model_name = excluded.last_model_name,
                    message_count = excluded.message_count,
                    updated_at = excluded.updated_at
                """,
                (
                    session_id,
                    input_tokens,
                    output_tokens,
                    total_tokens,
                    model_name,
                    message_count if message_count is not None else existing.get("message_count", 0),
                    existing.get("overflow_triggered", 0),
                    existing.get("overflow_reason"),
                    self._now(),
                ),
            )
            self.sqlite.commit()

    def update_message_count(self, session_id: str, message_count: int) -> None:
        with self._lock:
            existing = self.get_session_stats(session_id)
            self.sqlite.execute(
                """
                INSERT INTO agent_session_stats (
                    session_id,
                    current_input_tokens,
                    current_output_tokens,
                    current_total_tokens,
                    last_model_name,
                    message_count,
                    overflow_triggered,
                    overflow_reason,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    message_count = excluded.message_count,
                    updated_at = excluded.updated_at
                """,
                (
                    session_id,
                    existing.get("current_input_tokens", 0),
                    existing.get("current_output_tokens", 0),
                    existing.get("current_total_tokens", 0),
                    existing.get("last_model_name"),
                    message_count,
                    existing.get("overflow_triggered", 0),
                    existing.get("overflow_reason"),
                    self._now(),
                ),
            )
            self.sqlite.commit()

    def mark_overflow(self, session_id: str, reason: str, message_count: int | None = None) -> None:
        with self._lock:
            existing = self.get_session_stats(session_id)
            self.sqlite.execute(
                """
                INSERT INTO agent_session_stats (
                    session_id,
                    current_input_tokens,
                    current_output_tokens,
                    current_total_tokens,
                    last_model_name,
                    message_count,
                    overflow_triggered,
                    overflow_reason,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    message_count = excluded.message_count,
                    overflow_triggered = 1,
                    overflow_reason = excluded.overflow_reason,
                    updated_at = excluded.updated_at
                """,
                (
                    session_id,
                    existing.get("current_input_tokens", 0),
                    existing.get("current_output_tokens", 0),
                    existing.get("current_total_tokens", 0),
                    existing.get("last_model_name"),
                    message_count if message_count is not None else existing.get("message_count", 0),
                    reason,
                    self._now(),
                ),
            )
            self.sqlite.commit()

    def get_session_stats(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            row = self.sqlite.execute(
                """
                SELECT *
                FROM agent_session_stats
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
        return dict(row) if row else {}

    def _row_to_tuple(self, row: sqlite3.Row) -> CheckpointTuple:
        thread_id = row["thread_id"]
        checkpoint_ns = row["checkpoint_ns"]
        checkpoint_id = row["checkpoint_id"]
        checkpoint = self.serde.loads_typed((row["checkpoint_type"], row["checkpoint_blob"]))
        metadata = self.serde.loads_typed((row["metadata_type"], row["metadata_blob"]))
        checkpoint = {
            **checkpoint,
            "channel_values": self._load_blobs(
                thread_id,
                checkpoint_ns,
                checkpoint.get("channel_versions", {}),
            ),
        }
        writes = self._load_writes(thread_id, checkpoint_ns, checkpoint_id)
        parent_checkpoint_id = row["parent_checkpoint_id"]
        return CheckpointTuple(
            config={
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": checkpoint_id,
                }
            },
            checkpoint=checkpoint,
            metadata=metadata,
            parent_config=(
                {
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_ns": checkpoint_ns,
                        "checkpoint_id": parent_checkpoint_id,
                    }
                }
                if parent_checkpoint_id
                else None
            ),
            pending_writes=writes,
        )

    def _load_blobs(
        self,
        thread_id: str,
        checkpoint_ns: str,
        versions: ChannelVersions,
    ) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for channel, version in versions.items():
            row = self.sqlite.execute(
                """
                SELECT type, blob
                FROM agent_checkpoint_blobs
                WHERE thread_id = ? AND checkpoint_ns = ? AND channel = ? AND version = ?
                """,
                (thread_id, checkpoint_ns, channel, str(version)),
            ).fetchone()
            if row is None or row["type"] == "empty":
                continue
            values[channel] = self.serde.loads_typed((row["type"], row["blob"]))
        return values

    def _load_writes(
        self,
        thread_id: str,
        checkpoint_ns: str,
        checkpoint_id: str,
    ) -> list[PendingWrite]:
        rows = self.sqlite.execute(
            """
            SELECT task_id, channel, type, blob
            FROM agent_checkpoint_writes
            WHERE thread_id = ? AND checkpoint_ns = ? AND checkpoint_id = ?
            ORDER BY task_id, idx
            """,
            (thread_id, checkpoint_ns, checkpoint_id),
        ).fetchall()
        return [
            (row["task_id"], row["channel"], self.serde.loads_typed((row["type"], row["blob"])))
            for row in rows
        ]

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
