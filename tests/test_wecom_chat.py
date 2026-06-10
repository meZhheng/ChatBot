import asyncio
import sqlite3

from fastapi import BackgroundTasks, FastAPI
from fastapi.testclient import TestClient

from app.api.platforms.wecom import router
from app.services.conversation_history import ConversationHistoryStore
from app.services.wecom import WeComIncomingMessage
from app.services.wecom_chat import WeComChatService


class FakeChatRuntime:
    def __init__(self, history_store=None):
        self.calls = []
        self.history_store = history_store

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        if self.history_store:
            self.history_store.add_message(
                session_id=kwargs["session_id"],
                user_id=kwargs["user_id"],
                role="user",
                content=kwargs["message"],
                channel=kwargs["channel"],
                platform=kwargs["platform"],
                platform_message_id=kwargs["platform_message_id"],
                event_type="input",
            )
            self.history_store.add_message(
                session_id=kwargs["session_id"],
                user_id=kwargs["user_id"],
                role="assistant",
                content=f"reply:{kwargs['message']}",
                channel=kwargs["channel"],
                platform=kwargs["platform"],
                event_type="output",
            )
        return type("Completion", (), {"content": f"reply:{kwargs['message']}"})()


class FakeWeComClient:
    def __init__(self, incoming=None):
        self.incoming = incoming
        self.sent = []

    def parse_callback_message(self, msg_signature, timestamp, nonce, body):
        return self.incoming

    async def send_text_message(self, *, content, touser=None, toparty=None, totag=None, safe=0):
        self.sent.append({"touser": touser, "content": content})
        return {"errcode": 0, "errmsg": "ok"}


def incoming_message(**overrides):
    data = {
        "to_user_name": "corp",
        "from_user_name": "zhangsan",
        "create_time": "1710000000",
        "msg_type": "text",
        "content": "你好",
        "msg_id": "msg-1",
        "agent_id": "1000002",
        "raw": {"MsgId": "msg-1", "Content": "你好"},
    }
    data.update(overrides)
    return WeComIncomingMessage(**data)


def make_service(reply_mode="complete"):
    sqlite = sqlite3.connect(":memory:", check_same_thread=False)
    store = ConversationHistoryStore(sqlite)
    chat_runtime = FakeChatRuntime(store)
    wecom_client = FakeWeComClient()
    service = WeComChatService(
        wecom_client=wecom_client,
        chat_runtime=chat_runtime,
        history_store=store,
        reply_mode=reply_mode,
    )
    return service, store, chat_runtime, wecom_client


def test_wecom_chat_schedules_text_message_and_processes_reply():
    service, store, chat_runtime, wecom_client = make_service()
    message = incoming_message()
    tasks = BackgroundTasks()

    service.schedule_message(message, tasks)
    asyncio.run(service.process_message(message, service.session_id_for(message), service.user_id_for(message), "msg-1"))

    assert chat_runtime.calls[0]["message"] == "你好"
    assert chat_runtime.calls[0]["channel"] == "wecom"
    assert chat_runtime.calls[0]["platform_message_id"] == "msg-1"
    assert wecom_client.sent == [{"touser": "zhangsan", "content": "reply:你好"}]
    rows = store.list_messages_by_session(service.session_id_for(message))
    assert [row["role"] for row in rows] == ["user", "assistant"]


def test_wecom_chat_ignores_non_text_message():
    service, store, chat_runtime, _ = make_service()
    message = incoming_message(msg_type="image", content="", msg_id="msg-image")

    service.schedule_message(message, BackgroundTasks())

    assert chat_runtime.calls == []
    row = store.sqlite.execute(
        "SELECT status, error FROM platform_inbound_messages WHERE platform = 'wecom' AND platform_message_id = 'msg-image'"
    ).fetchone()
    assert dict(row) == {"status": "ignored", "error": "unsupported_message_type"}


def test_wecom_chat_deduplicates_message_id():
    service, _, chat_runtime, _ = make_service()
    message = incoming_message()
    first_tasks = BackgroundTasks()
    second_tasks = BackgroundTasks()

    service.schedule_message(message, first_tasks)
    service.schedule_message(message, second_tasks)

    assert len(first_tasks.tasks) == 1
    assert len(second_tasks.tasks) == 0
    assert chat_runtime.calls == []


def test_wecom_callback_passes_incoming_message_to_chat_service():
    message = incoming_message()
    wecom_client = FakeWeComClient(message)
    calls = []

    class FakeWeComChatService:
        def schedule_message(self, incoming, background_tasks):
            calls.append((incoming, background_tasks))

    app = FastAPI()
    app.state.wecom_client = wecom_client
    app.state.wecom_chat_service = FakeWeComChatService()
    app.include_router(router)
    client = TestClient(app)

    response = client.post(
        "/api/platforms/wecom/callback?msg_signature=sig&timestamp=1&nonce=n",
        content="<xml></xml>",
    )

    assert response.status_code == 200
    assert response.text == "success"
    assert calls[0][0] is message
