from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from memory.knowledge_base import KnowledgeBaseService, TextHashService


KNOWLEDGE_TEXT = "这是一份知识库测试文档。"


def test_text_hash_service_calculates_and_persists_md5(tmp_path: Path):
    text_hash_service = TextHashService(tmp_path / "hash.sqlite")
    content_hash = text_hash_service.get_md5_hash("hello")

    assert content_hash == "5d41402abc4b2a76b9719d911017c592"
    assert text_hash_service.check_md5_hash("hello") is True
    assert text_hash_service.check_md5_hash("hello") is False
    assert text_hash_service.list_md5_hashes() == [content_hash]

    text_hash_service.close()


def test_knowledge_base_service_delegates_md5_check(tmp_path: Path):
    text_hash_service = TextHashService(tmp_path / "hash.sqlite")
    knowledge_base = KnowledgeBaseService(text_hash_service)

    assert knowledge_base.check_md5_hash("hello") is True
    assert knowledge_base.check_md5_hash("hello") is False

    text_hash_service.close()


def test_user_homepage_and_admin_page_are_separated():
    with TestClient(create_app()) as client:
        homepage = client.get("/")
        admin_page = client.get("/admin/rag")

    assert homepage.status_code == 200
    assert "智能对话智能体" in homepage.text
    assert "对话机器人" in homepage.text
    assert "RAG 管理（临时）" in homepage.text
    assert "当前 chunks" not in homepage.text
    assert "Retrieve Test" not in homepage.text

    assert admin_page.status_code == 200
    assert "RAG 管理" in admin_page.text
    assert "返回聊天页" in admin_page.text
    assert "当前 chunks" in admin_page.text
    assert "Retrieve Test" in admin_page.text
    assert "queryInput" in admin_page.text
    assert "topKInput" in admin_page.text
    assert "对话机器人" not in admin_page.text
    assert "选择文件上传到知识库" not in admin_page.text


def test_homepage_and_admin_page_show_temporary_navigation_links():
    with TestClient(create_app()) as client:
        homepage = client.get("/")
        admin_page = client.get("/admin/rag")

    assert homepage.status_code == 200
    assert 'href="/admin/rag"' in homepage.text
    assert "RAG 管理（临时）" in homepage.text
    assert "temp-entry" in homepage.text

    assert admin_page.status_code == 200
    assert 'href="/"' in admin_page.text
    assert "返回聊天页" in admin_page.text
    assert "temp-entry" in admin_page.text


def test_homepage_and_admin_page_load_separate_javascript_files():
    with TestClient(create_app()) as client:
        homepage = client.get("/")
        admin_page = client.get("/admin/rag")

    assert homepage.status_code == 200
    assert '/static/chat.js' in homepage.text
    assert '/static/admin_rag.js' not in homepage.text

    assert admin_page.status_code == 200
    assert '/static/admin_rag.js' in admin_page.text
    assert '/static/chat.js' not in admin_page.text


class FakeKnowledgeBaseService:
    def __init__(self):
        self.retrieve_calls: list[tuple[str, int]] = []

    def list_chunks(self):
        return [
            {
                "id": "chunk-1",
                "text": "第一段 chunk",
                "metadata": {
                    "source": "guide.txt",
                    "created_at": "2026-06-05 10:00:00",
                    "operator": "admin",
                },
            }
        ]

    def retrive(self, query: str, top_k: int = 5):
        self.retrieve_calls.append((query, top_k))
        return [
            {
                "id": "chunk-1",
                "text": "第一段 chunk",
                "metadata": {
                    "source": "guide.txt",
                    "created_at": "2026-06-05 10:00:00",
                    "operator": "admin",
                },
                "score": 0.123,
            }
        ]


def test_admin_rag_api_exposes_chunks_and_retrieve_results():
    fake_knowledge_base = FakeKnowledgeBaseService()

    with TestClient(create_app()) as client:
        client.app.state.knowledge_base = fake_knowledge_base

        chunks_response = client.get("/api/admin/rag/chunks")
        retrieve_response = client.post(
            "/api/admin/rag/retrieve",
            json={"query": "A股市场什么时候成立的？", "top_k": 3},
        )

    assert chunks_response.status_code == 200
    assert chunks_response.json() == {
        "count": 1,
        "chunks": [
            {
                "id": "chunk-1",
                "text": "第一段 chunk",
                "metadata": {
                    "source": "guide.txt",
                    "created_at": "2026-06-05 10:00:00",
                    "operator": "admin",
                },
            }
        ],
    }

    assert retrieve_response.status_code == 200
    assert retrieve_response.json() == {
        "query": "A股市场什么时候成立的？",
        "top_k": 3,
        "results": [
            {
                "id": "chunk-1",
                "text": "第一段 chunk",
                "metadata": {
                    "source": "guide.txt",
                    "created_at": "2026-06-05 10:00:00",
                    "operator": "admin",
                },
                "score": 0.123,
            }
        ],
    }
    assert fake_knowledge_base.retrieve_calls == [("A股市场什么时候成立的？", 3)]


class FakeRagChain:
    def __init__(self):
        self.stream_calls: list[tuple[dict, dict]] = []

    def stream(self, inputs: dict, config: dict):
        self.stream_calls.append((inputs, config))
        yield "第一段"
        yield "第二段"


class FakeRagService:
    def __init__(self):
        self.chain = FakeRagChain()


def test_chat_endpoint_streams_rag_reply():
    fake_rag_service = FakeRagService()

    with TestClient(create_app()) as client:
        client.app.state.rag_service = fake_rag_service
        response = client.post(
            "/api/chat",
            json={"message": "  你好  ", "session_id": "browser-session"},
        )

    assert response.status_code == 200
    assert response.text == "第一段第二段"
    assert response.headers["content-type"].startswith("text/plain")
    assert fake_rag_service.chain.stream_calls == [
        (
            {"query": "你好"},
            {
                "configurable": {
                    "session_id": "memory/chat_history/browser-session.json"
                }
            },
        )
    ]


def test_chat_endpoint_sanitizes_session_id_for_history_path():
    fake_rag_service = FakeRagService()

    with TestClient(create_app()) as client:
        client.app.state.rag_service = fake_rag_service
        response = client.post(
            "/api/chat",
            json={"message": "你好", "session_id": "../bad/path"},
        )

    assert response.status_code == 200
    _, config = fake_rag_service.chain.stream_calls[0]
    assert config["configurable"]["session_id"] == "memory/chat_history/---bad-path.json"


def test_chat_endpoint_rejects_blank_message():
    with TestClient(create_app()) as client:
        response = client.post("/api/chat", json={"message": "   "})

    assert response.status_code == 400
    assert response.json() == {"detail": "消息不能为空。"}


def test_upload_endpoint_records_text_md5_in_sqlite_index(tmp_path: Path):
    sample_file = tmp_path / "guide.txt"
    sample_file.write_text(KNOWLEDGE_TEXT, encoding="utf-8")
    expected_hash = TextHashService(tmp_path / "hash.sqlite").get_md5_hash(KNOWLEDGE_TEXT)

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
            "is_new_text": True,
            "status": "indexed",
            "message": "文本已写入 Chroma 向量库。",
        }


def test_upload_endpoint_detects_duplicate_text_by_md5(tmp_path: Path):
    first_file = tmp_path / "guide.txt"
    second_file = tmp_path / "copy.txt"
    first_file.write_text(KNOWLEDGE_TEXT, encoding="utf-8")
    second_file.write_text(KNOWLEDGE_TEXT, encoding="utf-8")
    expected_hash = TextHashService(tmp_path / "hash.sqlite").get_md5_hash(KNOWLEDGE_TEXT)

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
            "is_new_text": False,
            "status": "duplicate",
            "message": "文本 MD5 已存在，跳过重复入库。",
        }


def test_text_hash_service_atomic_insert_writes_only_once(tmp_path: Path):
    text_hash_service = TextHashService(tmp_path / "hash.sqlite")

    assert text_hash_service.check_md5_hash("hello") is True
    assert text_hash_service.check_md5_hash("hello") is False
    assert text_hash_service.list_md5_hashes() == [text_hash_service.get_md5_hash("hello")]

    text_hash_service.close()
