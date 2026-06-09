import sqlite3

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import faq
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


def test_service_retrieve_uses_bm25_and_vector_sources():
    service = make_service()
    item = service.create_item(
        "如何开具发票",
        "请在订单详情申请电子发票。",
        category="invoice",
        variants=["我要开发票"],
    )

    results = service.retrieve("我要开发票", top_k=5)

    assert results[0]["faq_id"] == item["faq_id"]
    assert "bm25" in results[0]["sources"]
    assert "vector" in results[0]["sources"]
    assert results[0]["matched_doc_type"] in {"standard", "variant"}


def test_service_retrieve_filters_disabled_and_deleted_items():
    service = make_service()
    disabled = service.create_item("如何取消订单", "订单页取消。", variants=["不想买了"])
    active = service.create_item("如何查询订单", "订单页查询。", variants=["订单在哪"])
    service.update_item(
        disabled["faq_id"],
        disabled["question"],
        disabled["answer"],
        status="disabled",
        variants=["不想买了"],
    )

    results = service.retrieve("订单", top_k=5)

    assert {result["faq_id"] for result in results} == {active["faq_id"]}


def test_service_merge_hits_uses_rrf_scores():
    service = make_service()
    first = service.create_item("如何申请退款", "订单详情提交退款。")
    second = service.create_item("如何查询物流", "订单详情查看物流。")
    first_row = service._active_item(first["faq_id"])
    second_row = service._active_item(second["faq_id"])
    bm25_hits = [
        service._hit_from_row(first_row, source="bm25", score=0.9, doc_id="faq:first", doc_type="standard", matched_question="如何申请退款"),
        service._hit_from_row(second_row, source="bm25", score=0.8, doc_id="faq:second", doc_type="standard", matched_question="如何查询物流"),
    ]
    vector_hits = [
        service._hit_from_row(second_row, source="vector", score=0.9, doc_id="faq:second", doc_type="standard", matched_question="如何查询物流"),
        service._hit_from_row(first_row, source="vector", score=0.8, doc_id="faq:first", doc_type="standard", matched_question="如何申请退款"),
    ]

    merged = service._merge_hits(bm25_hits, vector_hits)

    assert merged[first["faq_id"]]["score"] == round(service._rrf_score(1) + service._rrf_score(2), 6)
    assert merged[second["faq_id"]]["score"] == round(service._rrf_score(2) + service._rrf_score(1), 6)
    assert merged[first["faq_id"]]["normalized_bm25_score"] == service._rrf_score(1)
    assert merged[first["faq_id"]]["normalized_vector_score"] == service._rrf_score(2)


def test_customer_faq_retrieve_endpoint_returns_answer_only_flow():
    service = make_service()
    item = service.create_item("如何联系客服", "请点击页面右下角在线客服。", variants=["找人工客服"])
    app = FastAPI()
    app.state.faq_service = service
    app.include_router(faq.router)
    client = TestClient(app)

    response = client.post("/api/faq/retrieve", json={"query": "找人工客服", "top_k": 1})

    assert response.status_code == 200
    data = response.json()
    assert data["results"][0]["faq_id"] == item["faq_id"]
    assert data["results"][0]["answer"] == "请点击页面右下角在线客服。"


def test_customer_faq_retrieve_rejects_blank_query():
    app = FastAPI()
    app.state.faq_service = make_service()
    app.include_router(faq.router)
    client = TestClient(app)

    response = client.post("/api/faq/retrieve", json={"query": "   ", "top_k": 1})

    assert response.status_code == 400
