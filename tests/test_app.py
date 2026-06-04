from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from memory.knowledge_base import get_md5_hash


KNOWLEDGE_TEXT = "这是一份知识库测试文档。"


def test_homepage_renders_chat_and_knowledge_base_sections():
    with TestClient(create_app()) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "智能对话智能体" in response.text
    assert "对话机器人" in response.text
    assert "RAG 知识库" in response.text
    assert "选择文件上传到知识库" in response.text


def test_chat_endpoint_returns_placeholder_bot_reply():
    with TestClient(create_app()) as client:
        response = client.post("/api/chat", json={"message": "你好"})

    assert response.status_code == 200
    assert response.json() == {
        "reply": "已收到你的消息：你好。后续会接入 LangChain + 千问 + Chroma 实现 RAG 回复。"
    }


def test_upload_endpoint_records_text_md5_in_sqlite_index(tmp_path: Path):
    sample_file = tmp_path / "guide.txt"
    sample_file.write_text(KNOWLEDGE_TEXT, encoding="utf-8")
    expected_hash = get_md5_hash(KNOWLEDGE_TEXT)

    with TestClient(create_app(tmp_path / "test.sqlite")) as client:
        with sample_file.open("rb") as file_handle:
            response = client.post(
                "/api/knowledge/upload",
                files={"file": ("guide.txt", file_handle, "text/plain")},
            )

        assert response.status_code == 200
        assert response.json() == {
            "filename": "guide.txt",
            "content_type": "text/plain",
            "content_hash": expected_hash,
            "is_duplicate": False,
            "status": "indexed",
            "message": "文本 MD5 已记录，后续可写入 Chroma 向量库。",
        }

        md5_records = client.app.state.knowledge_base.list_md5_records()

    assert md5_records == [
        {
            "content_hash": expected_hash,
            "source_name": "guide.txt",
            "content_type": "text/plain",
        }
    ]


def test_upload_endpoint_detects_duplicate_text_by_md5(tmp_path: Path):
    first_file = tmp_path / "guide.txt"
    second_file = tmp_path / "copy.txt"
    first_file.write_text(KNOWLEDGE_TEXT, encoding="utf-8")
    second_file.write_text(KNOWLEDGE_TEXT, encoding="utf-8")
    expected_hash = get_md5_hash(KNOWLEDGE_TEXT)

    with TestClient(create_app(tmp_path / "test.sqlite")) as client:
        with first_file.open("rb") as file_handle:
            client.post(
                "/api/knowledge/upload",
                files={"file": ("guide.txt", file_handle, "text/plain")},
            )

        with second_file.open("rb") as file_handle:
            response = client.post(
                "/api/knowledge/upload",
                files={"file": ("copy.txt", file_handle, "text/plain")},
            )

        assert response.status_code == 200
        assert response.json() == {
            "filename": "copy.txt",
            "content_type": "text/plain",
            "content_hash": expected_hash,
            "is_duplicate": True,
            "status": "duplicate",
            "message": "文本 MD5 已存在，跳过重复入库。",
        }

        md5_records = client.app.state.knowledge_base.list_md5_records()

    assert md5_records == [
        {
            "content_hash": expected_hash,
            "source_name": "guide.txt",
            "content_type": "text/plain",
        }
    ]
