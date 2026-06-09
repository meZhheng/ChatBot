from __future__ import annotations

import json
import re
import sqlite3
import threading
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langchain_openai import ChatOpenAI

from agent.middleware import (
    context_overflow_hook,
    log_after_agent,
    log_after_model,
    log_before_agent,
    log_before_model,
    model_call_hook,
    monitor_tool,
)
from agent.sqlite_checkpointer import SQLiteCheckpointSaver
from agent.tools import get_current_time, retrieve_knowledge_base, search_internet
from agent.utils.config_handler import agent_config, get_env, prompts_config


@dataclass
class AgentRuntimeContext:
    checkpointer: SQLiteCheckpointSaver
    memory_config: dict[str, Any]


class AgentService:
    SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")

    def __init__(self, sqlite: sqlite3.Connection):
        qwen_config = agent_config.get("qwen", {})
        system_prompt = prompts_config.get("system", {})

        self.memory_config = agent_config.get("memory", {})
        self.stream_config = agent_config.get("stream", {})
        self.checkpointer = SQLiteCheckpointSaver(sqlite)
        self._session_locks: defaultdict[str, threading.RLock] = defaultdict(threading.RLock)

        self.agent = create_agent(
            model=ChatOpenAI(
                model=qwen_config.get("chat_model", "qwen3.6-flash"),
                api_key=get_env("DASHSCOPE_API_KEY"),
                base_url=qwen_config.get("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            ),
            tools=[get_current_time, retrieve_knowledge_base, search_internet],
            middleware=[
                log_before_agent,
                log_after_agent,
                context_overflow_hook,
                log_before_model,
                log_after_model,
                model_call_hook,
                monitor_tool,
            ],
            system_prompt=system_prompt,
            checkpointer=self.checkpointer,
            context_schema=AgentRuntimeContext,
        )

    def execute_stream(self, query: str, session_id: str):
        self._validate_session_id(session_id)

        seq = 0
        final_text_parts: list[str] = []
        final_output = ""
        tool_names: dict[str, str] = {}
        emitted_tool_calls: set[str] = set()
        emitted_tool_results: set[str] = set()
        last_usage: dict[str, Any] = {}
        max_tool_result_chars = int(self.stream_config.get("max_tool_result_chars", 1200))
        context = AgentRuntimeContext(
            checkpointer=self.checkpointer,
            memory_config=self.memory_config,
        )
        config = {"configurable": {"thread_id": session_id}}
        input_dict = {"messages": [{"role": "user", "content": query}]}

        def event(event_type: str, **payload):
            nonlocal seq
            seq += 1
            return {
                "type": event_type,
                "session_id": session_id,
                "seq": seq,
                **payload,
            }

        lock = self._session_locks[session_id]
        with lock:
            yield event("thinking", role="assistant", content="模型正在思考...")
            yield event("input", role="user", content=query)

            for chunk in self.agent.stream(
                input_dict,
                config=config,
                context=context,
                stream_mode=["messages", "updates"],
            ):
                mode, data = self._normalize_stream_chunk(chunk)
                if mode == "messages":
                    message, metadata = data
                    for tool_event in self._extract_tool_call_events(
                        message,
                        session_id,
                        tool_names,
                        emitted_tool_calls,
                    ):
                        yield event("tool_call", **tool_event)

                    content = self._message_text(message)
                    if content and isinstance(message, (AIMessage, AIMessageChunk)):
                        final_text_parts.append(content)
                        yield event("output_delta", role="assistant", content=content)

                    usage = self._extract_usage(message, metadata)
                    if usage:
                        last_usage = usage
                elif mode == "updates":
                    for update_event in self._extract_update_events(
                        data,
                        session_id,
                        tool_names,
                        emitted_tool_calls,
                        emitted_tool_results,
                        max_tool_result_chars,
                    ):
                        update_type = update_event.pop("type")
                        if update_type == "output" and update_event.get("content"):
                            final_output = update_event["content"]
                        yield event(update_type, **update_event)

            if not final_output:
                final_output = "".join(final_text_parts).strip()

            stats = self.checkpointer.get_session_stats(session_id)
            if last_usage:
                self.checkpointer.update_session_usage(
                    session_id,
                    input_tokens=int(last_usage.get("input_tokens") or 0),
                    output_tokens=int(last_usage.get("output_tokens") or 0),
                    total_tokens=int(last_usage.get("total_tokens") or 0),
                    model_name=last_usage.get("model_name"),
                    message_count=stats.get("message_count"),
                )
                stats = self.checkpointer.get_session_stats(session_id)

            if stats.get("overflow_triggered"):
                yield event(
                    "memory",
                    role="assistant",
                    content="会话上下文达到阈值，已触发压缩钩子；压缩功能暂未实现。",
                    metadata={"reason": stats.get("overflow_reason")},
                )

            yield event("output", role="assistant", content=final_output)
            yield event("done", role="assistant", metadata={"usage": stats})

    def delete_session(self, session_id: str) -> None:
        self._validate_session_id(session_id)
        with self._session_locks[session_id]:
            self.checkpointer.delete_thread(session_id)

    def _validate_session_id(self, session_id: str) -> None:
        if not session_id or not self.SESSION_ID_PATTERN.fullmatch(session_id):
            raise ValueError("session_id 格式无效。")

    def _normalize_stream_chunk(self, chunk: Any) -> tuple[str, Any]:
        if isinstance(chunk, tuple) and len(chunk) == 2:
            return chunk
        return "values", chunk

    def _extract_update_events(
        self,
        data: Any,
        session_id: str,
        tool_names: dict[str, str],
        emitted_tool_calls: set[str],
        emitted_tool_results: set[str],
        max_tool_result_chars: int,
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        messages = self._collect_messages(data)
        for message in messages:
            events.extend(
                self._extract_tool_call_events(
                    message,
                    session_id,
                    tool_names,
                    emitted_tool_calls,
                )
            )
            if isinstance(message, ToolMessage):
                tool_call_id = getattr(message, "tool_call_id", None) or getattr(message, "id", None)
                if not tool_call_id or tool_call_id in emitted_tool_results:
                    continue
                emitted_tool_results.add(tool_call_id)
                content, truncated = self._truncate(self._message_text(message), max_tool_result_chars)
                events.append(
                    {
                        "type": "tool_result",
                        "role": "tool",
                        "name": tool_names.get(tool_call_id, getattr(message, "name", None) or "tool"),
                        "tool_call_id": tool_call_id,
                        "content": content,
                        "metadata": {"truncated": truncated},
                    }
                )
            elif isinstance(message, AIMessage):
                content = self._message_text(message)
                if content and not getattr(message, "tool_calls", None):
                    events.append({"type": "output", "role": "assistant", "content": content})
        return events

    def _extract_tool_call_events(
        self,
        message: Any,
        session_id: str,
        tool_names: dict[str, str],
        emitted_tool_calls: set[str],
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        tool_calls = getattr(message, "tool_calls", None) or []
        for index, tool_call in enumerate(tool_calls):
            tool_call_id = tool_call.get("id") or f"{getattr(message, 'id', session_id)}:{index}"
            if tool_call_id in emitted_tool_calls:
                continue
            emitted_tool_calls.add(tool_call_id)
            name = tool_call.get("name") or "tool"
            tool_names[tool_call_id] = name
            events.append(
                {
                    "role": "tool",
                    "name": name,
                    "tool_call_id": tool_call_id,
                    "args": tool_call.get("args") or {},
                    "content": f"调用工具 {name}",
                }
            )
        return events

    def _collect_messages(self, data: Any) -> list[Any]:
        if isinstance(data, dict):
            messages: list[Any] = []
            for key, value in data.items():
                if key == "messages" and isinstance(value, list):
                    messages.extend(item for item in value if hasattr(item, "content"))
                elif isinstance(value, dict) and "messages" in value:
                    messages.extend(value["messages"])
                elif isinstance(value, list):
                    messages.extend(item for item in value if hasattr(item, "content"))
                elif hasattr(value, "content"):
                    messages.append(value)
            return messages
        if isinstance(data, list):
            return [item for item in data if hasattr(item, "content")]
        if hasattr(data, "content"):
            return [data]
        return []

    def _extract_usage(self, message: Any, metadata: Any = None) -> dict[str, Any]:
        usage = getattr(message, "usage_metadata", None) or {}
        response_metadata = getattr(message, "response_metadata", None) or {}
        token_usage = response_metadata.get("token_usage") or {}
        model_name = response_metadata.get("model_name") or response_metadata.get("model")

        if not usage and metadata and isinstance(metadata, dict):
            usage = metadata.get("usage_metadata") or {}
            model_name = model_name or metadata.get("model_name")

        input_tokens = usage.get("input_tokens") or token_usage.get("prompt_tokens") or token_usage.get("input_tokens")
        output_tokens = usage.get("output_tokens") or token_usage.get("completion_tokens") or token_usage.get("output_tokens")
        total_tokens = usage.get("total_tokens") or token_usage.get("total_tokens")

        if not any(value is not None for value in (input_tokens, output_tokens, total_tokens)):
            return {}

        return {
            "input_tokens": input_tokens or 0,
            "output_tokens": output_tokens or 0,
            "total_tokens": total_tokens or (input_tokens or 0) + (output_tokens or 0),
            "model_name": model_name,
        }

    def _message_text(self, message: Any) -> str:
        content = getattr(message, "content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    text = item.get("text") or item.get("content")
                    if text:
                        parts.append(str(text))
            return "".join(parts)
        return str(content) if content else ""

    def _truncate(self, text: str, max_chars: int) -> tuple[str, bool]:
        if max_chars <= 0 or len(text) <= max_chars:
            return text, False
        return f"{text[:max_chars]}...", True

    def event_to_line(self, event: dict[str, Any]) -> str:
        return json.dumps(event, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    pass
