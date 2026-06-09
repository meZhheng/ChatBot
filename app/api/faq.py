from fastapi import APIRouter, HTTPException, Request

from app.core.dependencies import get_faq_service
from app.schemas.faq import FaqRetrieveRequest, FaqRetrieveResponse

router = APIRouter()


@router.post("/api/faq/retrieve", response_model=FaqRetrieveResponse)
def retrieve_faq(payload: FaqRetrieveRequest, request: Request):
    query = payload.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="query 不能为空。")
    if payload.top_k < 1:
        raise HTTPException(status_code=400, detail="top_k 必须大于 0。")

    faq_service = get_faq_service(request)
    try:
        results = faq_service.retrieve(query, top_k=payload.top_k, category=payload.category)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"query": query, "top_k": payload.top_k, "category": payload.category, "results": results}
