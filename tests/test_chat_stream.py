import json
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, ToolMessage

from app.api.chat import router
from agent.bot import AgentService


class FakeAgentService:
    def __init__(self):
        self.calls = []
        self.deleted = []

    def execute_stream(self, query, session_id):
        self.calls.append((query, session_id))
        yield {"type": "thinking", "session_id": session_id, "seq": 1, "content": "thinking"}
        yield {"type": "output", "session_id": session_id, "seq": 2, "content": query}
        yield {"type": "done", "session_id": session_id, "seq": 3, "metadata": {}}

    def delete_session(self, session_id):
        self.deleted.append(session_id)


class FailingAgentService(FakeAgentService):
    def execute_stream(self, query, session_id):
        raise RuntimeError("boom")
        yield


def make_client(service):
    app = FastAPI()
    app.state.agent_service = service
    app.include_router(router)
    return TestClient(app)


def test_chat_requires_session_id():
    client = make_client(FakeAgentService())

    response = client.post("/api/chat", json={"message": "hello"})

    assert response.status_code == 422


def test_chat_rejects_blank_session_id():
    client = make_client(FakeAgentService())

    response = client.post("/api/chat", json={"message": "hello", "session_id": "   "})

    assert response.status_code == 400


def test_chat_streams_ndjson_and_passes_session_id():
    service = FakeAgentService()
    client = make_client(service)

    response = client.post("/api/chat", json={"message": "hello", "session_id": "chat-1"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    events = [json.loads(line) for line in response.text.strip().splitlines()]
    assert [event["type"] for event in events] == ["thinking", "output", "done"]
    assert service.calls == [("hello", "chat-1")]


def test_chat_stream_error_is_structured_event():
    client = make_client(FailingAgentService())

    response = client.post("/api/chat", json={"message": "hello", "session_id": "chat-1"})

    event = json.loads(response.text.strip())
    assert response.status_code == 200
    assert event["type"] == "error"
    assert "boom" in event["content"]


def test_delete_chat_session_calls_agent_service():
    service = FakeAgentService()
    client = make_client(service)

    response = client.delete("/api/chat/sessions/chat-1")

    assert response.status_code == 200
    assert response.json() == {"deleted": True, "session_id": "chat-1"}
    assert service.deleted == ["chat-1"]


def test_tool_call_events_include_type():
    message = AIMessage(
        content="",
        tool_calls=[{"id": "call-1", "name": "get_current_time", "args": {}}],
    )

    events = AgentService._extract_tool_call_events(AgentService, message, {}, {}, set())

    assert events == [
        {
            "type": "tool_call",
            "role": "tool",
            "name": "get_current_time",
            "tool_call_id": "call-1",
            "args": {},
            "content": "调用工具 get_current_time",
        }
    ]


def test_tool_result_events_include_args_and_content():
    data = {
        "tools": {
            "messages": [ToolMessage(content="2026-06-09 12:00:00", tool_call_id="call-1")]
        }
    }

    service = object.__new__(AgentService)

    events = service._extract_update_events(
        data,
        {"call-1": "get_current_time"},
        {"call-1": {"timezone": "local"}},
        set(),
        set(),
        1200,
    )

    assert events == [
        {
            "type": "tool_result",
            "role": "tool",
            "name": "get_current_time",
            "tool_call_id": "call-1",
            "args": {"timezone": "local"},
            "content": "2026-06-09 12:00:00",
            "metadata": {"truncated": False},
        }
    ]
