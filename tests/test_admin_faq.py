import sqlite3
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.templating import Jinja2Templates

from app.api import admin_faq, pages
from faq.service import FaqService


class FakeDocument:
    def __init__(self, page_content, metadata):
        self.page_content = page_content
        self.metadata = metadata


class FakeVectorStore:
    def __init__(self):
        self.docs = {}

    def add_texts(self, texts, metadatas, ids):
        for text, metadata, doc_id in zip(texts, metadatas, ids):
            self.docs[doc_id] = (text, metadata)

    def delete(self, ids):
        for doc_id in ids:
            self.docs.pop(doc_id, None)

    def similarity_search_with_score(self, query, k):
        query_chars = set(query.lower())
        scored = []
        for text, metadata in self.docs.values():
            overlap = len(query_chars & set(text.lower()))
            distance = 1 / (overlap + 1)
            scored.append((FakeDocument(text, metadata), distance))
        return sorted(scored, key=lambda item: item[1])[:k]


def make_service():
    sqlite = sqlite3.connect(":memory:", check_same_thread=False)
    return FaqService(sqlite, vector_store=FakeVectorStore())


def make_client(service=None):
    app = FastAPI()
    app.state.faq_service = service or make_service()
    app.include_router(admin_faq.router)
    return TestClient(app)


def test_create_list_update_delete_faq_item():
    client = make_client()

    response = client.post(
        "/api/admin/faq/items",
        json={
            "question": "如何申请退款",
            "answer": "在订单详情提交退款申请。",
            "category": "order",
            "tags": ["退款", "订单"],
            "priority": 5,
            "variants": ["退款怎么操作", "订单能退吗"],
        },
    )

    assert response.status_code == 200
    item = response.json()
    assert item["question"] == "如何申请退款"
    assert item["variant_count"] == 2

    faq_id = item["faq_id"]
    list_response = client.get("/api/admin/faq/items?category=order")
    assert list_response.status_code == 200
    assert list_response.json()["count"] == 1

    update_response = client.put(
        f"/api/admin/faq/items/{faq_id}",
        json={
            "question": "如何办理退款",
            "answer": "请在订单详情提交退款申请。",
            "category": "order",
            "tags": ["退款"],
            "priority": 8,
            "status": "active",
            "variants": ["我要退款"],
        },
    )
    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["question"] == "如何办理退款"
    assert updated["variant_count"] == 1

    delete_response = client.delete(f"/api/admin/faq/items/{faq_id}")
    assert delete_response.status_code == 200
    assert delete_response.json()["deleted"] is True

    missing_response = client.get(f"/api/admin/faq/items/{faq_id}")
    assert missing_response.status_code == 404


def test_variant_crud():
    service = make_service()
    item = service.create_item("如何修改地址", "在订单页修改地址。")
    client = make_client(service)

    create_response = client.post(
        f"/api/admin/faq/items/{item['faq_id']}/variants",
        json={"question": "收货地址怎么改"},
    )
    assert create_response.status_code == 200
    variant = create_response.json()
    assert variant["question"] == "收货地址怎么改"

    update_response = client.put(
        f"/api/admin/faq/items/{item['faq_id']}/variants/{variant['variant_id']}",
        json={"question": "地址可以改吗", "status": "active"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["question"] == "地址可以改吗"

    delete_response = client.delete(f"/api/admin/faq/items/{item['faq_id']}/variants/{variant['variant_id']}")
    assert delete_response.status_code == 200
    assert delete_response.json()["deleted"] is True


def test_admin_retrieve_matches_variant_and_counts_hit():
    client = make_client()
    item = client.post(
        "/api/admin/faq/items",
        json={
            "question": "如何查询物流",
            "answer": "打开订单详情查看物流轨迹。",
            "category": "logistics",
            "variants": ["快递到哪里了"],
        },
    ).json()

    response = client.post("/api/admin/faq/retrieve", json={"query": "快递到哪里了", "top_k": 3})

    assert response.status_code == 200
    data = response.json()
    assert data["results"][0]["faq_id"] == item["faq_id"]
    assert data["results"][0]["matched_doc_type"] in {"standard", "variant"}
    assert data["results"][0]["hit_count"] == 1


def test_admin_faq_page_route():
    app = FastAPI()
    pages.templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / "app" / "templates"))
    app.include_router(pages.router)
    client = TestClient(app)

    response = client.get("/admin/faq")

    assert response.status_code == 200
    assert "/static/admin_faq.js" in response.text
