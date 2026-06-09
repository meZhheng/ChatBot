from fastapi import APIRouter, HTTPException, Query, Request

from app.core.dependencies import get_faq_service
from app.schemas.faq import (
    FaqDeleteResponse,
    FaqItem,
    FaqItemCreateRequest,
    FaqItemListResponse,
    FaqItemUpdateRequest,
    FaqRetrieveRequest,
    FaqRetrieveResponse,
    FaqVariantDeleteResponse,
    FaqVariantItem,
    FaqVariantRequest,
)

router = APIRouter()


def _bad_request(exc: ValueError):
    raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/admin/faq/items", response_model=FaqItemListResponse)
def admin_list_faq_items(
    request: Request,
    query: str | None = None,
    category: str | None = None,
    status: str | None = "active",
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    faq_service = get_faq_service(request)
    try:
        return faq_service.list_items(query=query, category=category, status=status, limit=limit, offset=offset)
    except ValueError as exc:
        _bad_request(exc)


@router.post("/api/admin/faq/items", response_model=FaqItem)
def admin_create_faq_item(payload: FaqItemCreateRequest, request: Request):
    faq_service = get_faq_service(request)
    try:
        return faq_service.create_item(
            payload.question,
            payload.answer,
            category=payload.category,
            tags=payload.tags,
            priority=payload.priority,
            operator=payload.operator,
            variants=payload.variants,
        )
    except ValueError as exc:
        _bad_request(exc)


@router.get("/api/admin/faq/items/{faq_id}", response_model=FaqItem)
def admin_get_faq_item(faq_id: str, request: Request):
    faq_service = get_faq_service(request)
    item = faq_service.get_item(faq_id)
    if not item:
        raise HTTPException(status_code=404, detail="FAQ 不存在或已被删除。")
    return item


@router.put("/api/admin/faq/items/{faq_id}", response_model=FaqItem)
def admin_update_faq_item(faq_id: str, payload: FaqItemUpdateRequest, request: Request):
    faq_service = get_faq_service(request)
    try:
        item = faq_service.update_item(
            faq_id,
            payload.question,
            payload.answer,
            category=payload.category,
            tags=payload.tags,
            priority=payload.priority,
            status=payload.status,
            operator=payload.operator,
            variants=payload.variants,
        )
    except ValueError as exc:
        _bad_request(exc)
    if not item:
        raise HTTPException(status_code=404, detail="FAQ 不存在或已被删除。")
    return item


@router.delete("/api/admin/faq/items/{faq_id}", response_model=FaqDeleteResponse)
def admin_delete_faq_item(faq_id: str, request: Request):
    faq_service = get_faq_service(request)
    result = faq_service.delete_item(faq_id)
    if not result:
        raise HTTPException(status_code=404, detail="FAQ 不存在或已被删除。")
    return result


@router.post("/api/admin/faq/items/{faq_id}/variants", response_model=FaqVariantItem)
def admin_create_faq_variant(faq_id: str, payload: FaqVariantRequest, request: Request):
    faq_service = get_faq_service(request)
    try:
        variant = faq_service.create_variant(faq_id, payload.question, operator=payload.operator)
    except ValueError as exc:
        _bad_request(exc)
    if not variant:
        raise HTTPException(status_code=404, detail="FAQ 不存在或已被删除。")
    return variant


@router.put("/api/admin/faq/items/{faq_id}/variants/{variant_id}", response_model=FaqVariantItem)
def admin_update_faq_variant(faq_id: str, variant_id: str, payload: FaqVariantRequest, request: Request):
    faq_service = get_faq_service(request)
    try:
        variant = faq_service.update_variant(
            faq_id,
            variant_id,
            payload.question,
            status=payload.status,
            operator=payload.operator,
        )
    except ValueError as exc:
        _bad_request(exc)
    if not variant:
        raise HTTPException(status_code=404, detail="扩展问不存在或已被删除。")
    return variant


@router.delete("/api/admin/faq/items/{faq_id}/variants/{variant_id}", response_model=FaqVariantDeleteResponse)
def admin_delete_faq_variant(faq_id: str, variant_id: str, request: Request):
    faq_service = get_faq_service(request)
    result = faq_service.delete_variant(faq_id, variant_id)
    if not result:
        raise HTTPException(status_code=404, detail="扩展问不存在或已被删除。")
    return result


@router.post("/api/admin/faq/retrieve", response_model=FaqRetrieveResponse)
def admin_retrieve_faq(payload: FaqRetrieveRequest, request: Request):
    query = payload.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="query 不能为空。")
    if payload.top_k < 1:
        raise HTTPException(status_code=400, detail="top_k 必须大于 0。")

    faq_service = get_faq_service(request)
    try:
        results = faq_service.retrieve(query, top_k=payload.top_k, category=payload.category)
    except ValueError as exc:
        _bad_request(exc)
    return {"query": query, "top_k": payload.top_k, "category": payload.category, "results": results}
