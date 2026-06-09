import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, ToolMessage

from agent.bot import AgentService
from app.api.chat import router
from app.services.chat_orchestrator import ChatOrchestrator


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


class FakeFaqService:
    def __init__(self, results=None, error=None):
        self.results = results or []
        self.error = error
        self.calls = []

    def retrieve(self, query, top_k=5, category=None):
        self.calls.append((query, top_k, category))
        if self.error:
            raise self.error
        return self.results


def faq_result(
    answer="FAQ answer",
    score=1.0,
    question="hello",
    matched_question="hello",
    sources=None,
):
    return SimpleNamespace(
        faq_id="faq-1",
        question=question,
        answer=answer,
        category="default",
        sources=sources or ["bm25", "vector"],
        score=score,
        matched_question=matched_question,
        matched_doc_type="standard",
        matched_doc_id="faq-1:standard",
    )


def make_client(service, faq_service=None):
    app = FastAPI()
    app.state.agent_service = service
    app.state.chat_orchestrator = ChatOrchestrator(
        agent_service=service,
        faq_service=faq_service or FakeFaqService(),
    )
    app.include_router(router)
    return TestClient(app)


def stream_events(response):
    return [json.loads(line) for line in response.text.strip().splitlines()]


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
    faq_service = FakeFaqService()
    client = make_client(service, faq_service)

    response = client.post("/api/chat", json={"message": "hello", "session_id": "chat-1"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    events = stream_events(response)
    assert [event["type"] for event in events] == ["thinking", "output", "done"]
    assert service.calls == [("hello", "chat-1")]
    assert faq_service.calls == [("hello", 3, None)]


def test_chat_returns_faq_hit_without_calling_agent():
    service = FakeAgentService()
    faq_service = FakeFaqService([faq_result(answer="这是 FAQ 答案。", score=0.032522)])
    client = make_client(service, faq_service)

    response = client.post("/api/chat", json={"message": "hello", "session_id": "chat-1"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    events = stream_events(response)
    assert [event["type"] for event in events] == ["thinking", "input", "output_delta", "output", "done"]
    assert events[2]["content"] == "这是 FAQ 答案。"
    assert events[3]["content"] == "这是 FAQ 答案。"
    assert events[4]["metadata"]["route"] == "faq"
    assert events[4]["metadata"]["faq_id"] == "faq-1"
    assert service.calls == []
    assert faq_service.calls == [("hello", 3, None)]


def test_chat_accepts_real_faq_service_list_results():
    service = FakeAgentService()
    faq_service = FakeFaqService([faq_result(answer="真实 FAQ 返回。", score=0.032522).__dict__])
    client = make_client(service, faq_service)

    response = client.post("/api/chat", json={"message": "hello", "session_id": "chat-1"})

    events = stream_events(response)
    assert response.status_code == 200
    assert events[3]["content"] == "真实 FAQ 返回。"
    assert events[4]["metadata"]["faq_id"] == "faq-1"
    assert service.calls == []


def test_chat_falls_back_for_non_exact_single_source_faq_candidate():
    service = FakeAgentService()
    faq_service = FakeFaqService([
        faq_result(score=0.016393, question="如何退款", matched_question="如何退款", sources=["bm25"]),
    ])
    client = make_client(service, faq_service)

    response = client.post("/api/chat", json={"message": "物流在哪里", "session_id": "chat-1"})

    events = stream_events(response)
    assert response.status_code == 200
    assert [event["type"] for event in events] == ["thinking", "output", "done"]
    assert service.calls == [("物流在哪里", "chat-1")]


def test_chat_returns_exact_single_source_faq_candidate():
    service = FakeAgentService()
    faq_service = FakeFaqService([
        faq_result(answer="订单详情可查询物流。", score=0.016393, question="物流在哪里", matched_question="物流在哪里", sources=["bm25"]),
    ])
    client = make_client(service, faq_service)

    response = client.post("/api/chat", json={"message": "物流在哪里", "session_id": "chat-1"})

    events = stream_events(response)
    assert response.status_code == 200
    assert events[3]["content"] == "订单详情可查询物流。"
    assert service.calls == []


def test_chat_falls_back_to_agent_for_low_score_faq():
    service = FakeAgentService()
    faq_service = FakeFaqService([
        faq_result(score=0.02, question="other", matched_question="other"),
    ])
    client = make_client(service, faq_service)

    response = client.post("/api/chat", json={"message": "hello", "session_id": "chat-1"})

    assert response.status_code == 200
    events = stream_events(response)
    assert [event["type"] for event in events] == ["thinking", "output", "done"]
    assert service.calls == [("hello", "chat-1")]


def test_chat_falls_back_to_agent_when_faq_retrieve_fails():
    service = FakeAgentService()
    faq_service = FakeFaqService(error=RuntimeError("faq down"))
    client = make_client(service, faq_service)

    response = client.post("/api/chat", json={"message": "hello", "session_id": "chat-1"})

    assert response.status_code == 200
    events = stream_events(response)
    assert [event["type"] for event in events] == ["thinking", "output", "done"]
    assert service.calls == [("hello", "chat-1")]
    assert faq_service.calls == [("hello", 3, None)]


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
