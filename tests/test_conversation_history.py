import sqlite3

from app.services.conversation_history import ConversationHistoryStore


def test_conversation_history_stores_session_and_messages_by_user():
    sqlite = sqlite3.connect(":memory:", check_same_thread=False)
    store = ConversationHistoryStore(sqlite)

    store.upsert_session(
        session_id="chat-1",
        user_id="user-1",
        channel="web",
        platform=None,
        metadata={"source": "test"},
    )
    store.add_message(
        session_id="chat-1",
        user_id="user-1",
        role="user",
        content="hello",
        channel="web",
        event_type="input",
    )
    store.add_message(
        session_id="chat-1",
        user_id="user-1",
        role="assistant",
        content="hi",
        channel="web",
        event_type="output",
    )

    by_session = store.list_messages_by_session("chat-1")
    by_user = store.list_messages_by_user("user-1")

    assert [message["content"] for message in by_session] == ["hello", "hi"]
    assert [message["role"] for message in by_user] == ["user", "assistant"]


def test_conversation_history_deduplicates_platform_inbound_messages():
    sqlite = sqlite3.connect(":memory:", check_same_thread=False)
    store = ConversationHistoryStore(sqlite)

    first = store.mark_inbound_received(
        platform="wecom",
        platform_message_id="msg-1",
        session_id="session-1",
        user_id="user-1",
        raw={"MsgId": "msg-1"},
    )
    second = store.mark_inbound_received(
        platform="wecom",
        platform_message_id="msg-1",
        session_id="session-1",
        user_id="user-1",
        raw={"MsgId": "msg-1"},
    )

    assert first is True
    assert second is False
