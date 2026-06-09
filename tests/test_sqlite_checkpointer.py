import sqlite3

from langgraph.checkpoint.base import empty_checkpoint

from agent.sqlite_checkpointer import SQLiteCheckpointSaver


def test_sqlite_checkpointer_persists_checkpoint_across_instances():
    sqlite = sqlite3.connect(":memory:", check_same_thread=False)
    saver = SQLiteCheckpointSaver(sqlite)
    config = {"configurable": {"thread_id": "chat-test", "checkpoint_ns": ""}}
    checkpoint = empty_checkpoint()
    checkpoint["channel_values"] = {"messages": ["hello"]}
    checkpoint["channel_versions"] = {"messages": "00000000000000000000000000000001.1"}

    saved_config = saver.put(config, checkpoint, {"source": "test"}, {"messages": "00000000000000000000000000000001.1"})
    saver.put_writes(saved_config, [("messages", "world")], task_id="task-1")

    restored = SQLiteCheckpointSaver(sqlite).get_tuple({"configurable": {"thread_id": "chat-test"}})

    assert restored is not None
    assert restored.checkpoint["id"] == checkpoint["id"]
    assert restored.checkpoint["channel_values"]["messages"] == ["hello"]
    assert restored.metadata["source"] == "test"
    assert restored.pending_writes == [("task-1", "messages", "world")]


def test_delete_thread_removes_checkpoints_and_stats():
    sqlite = sqlite3.connect(":memory:", check_same_thread=False)
    saver = SQLiteCheckpointSaver(sqlite)
    config = {"configurable": {"thread_id": "chat-test", "checkpoint_ns": ""}}
    checkpoint = empty_checkpoint()
    checkpoint["channel_values"] = {"messages": ["hello"]}
    checkpoint["channel_versions"] = {"messages": "00000000000000000000000000000001.1"}

    saver.put(config, checkpoint, {}, {"messages": "00000000000000000000000000000001.1"})
    saver.update_session_usage("chat-test", input_tokens=10, output_tokens=5, total_tokens=15)

    saver.delete_thread("chat-test")

    assert saver.get_tuple({"configurable": {"thread_id": "chat-test"}}) is None
    assert saver.get_session_stats("chat-test") == {}
