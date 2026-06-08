from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from app.core.dependencies import get_rag_service
from app.schemas.rag import (
    DeleteDocumentChunkResponse,
    DeleteDocumentResponse,
    DocumentItem,
    DocumentListResponse,
    RetrieveRequest,
    RetrieveResponse,
    UploadDocumentResponse,
)


router = APIRouter()


@router.post("/api/knowledge/upload", response_model=UploadDocumentResponse)
async def upload_knowledge_file(request: Request, file: UploadFile = File(...)):
    file_name = file.filename or "uploaded_document"
    content = await file.read()
    try:
        content_text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="当前只支持 UTF-8 文本文档。") from exc

    rag_service = get_rag_service(request)
    return rag_service.upload_document(
        content_text,
        file_name,
        content_type=file.content_type,
        operator="admin",
    )


@router.get("/api/admin/rag/documents", response_model=DocumentListResponse)
def admin_rag_documents(request: Request):
    rag_service = get_rag_service(request)
    documents = rag_service.list_documents()
    return {"count": len(documents), "documents": documents}


@router.get("/api/admin/rag/documents/{document_id}", response_model=DocumentItem)
def admin_rag_document(document_id: str, request: Request):
    rag_service = get_rag_service(request)
    document = rag_service.get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="document 不存在或已被删除。")
    return document


@router.delete("/api/admin/rag/documents/{document_id}", response_model=DeleteDocumentResponse)
def admin_delete_rag_document(document_id: str, request: Request):
    rag_service = get_rag_service(request)
    result = rag_service.delete_document(document_id)
    if not result:
        raise HTTPException(status_code=404, detail="document 不存在或已被删除。")
    return result


@router.delete(
    "/api/admin/rag/documents/{document_id}/chunks/{chunk_id}",
    response_model=DeleteDocumentChunkResponse,
)
def admin_delete_rag_document_chunk(document_id: str, chunk_id: str, request: Request):
    rag_service = get_rag_service(request)
    result = rag_service.delete_chunk(document_id, chunk_id)
    if not result:
        raise HTTPException(status_code=404, detail="chunk 不存在、已被删除或不属于该 document。")
    return result


@router.post("/api/admin/rag/retrieve", response_model=RetrieveResponse)
def admin_rag_retrieve(payload: RetrieveRequest, request: Request):
    query = payload.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="query 不能为空。")
    if payload.top_k < 1:
        raise HTTPException(status_code=400, detail="top_k 必须大于 0。")

    rag_service = get_rag_service(request)
    results = rag_service.retrieve(query, top_k=payload.top_k)
    return {"query": query, "top_k": payload.top_k, "results": results}
