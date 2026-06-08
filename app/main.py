from contextlib import asynccontextmanager
from pathlib import Path
import re

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from agent.rag.chat_chain import RagChatChain
from agent.rag.knowledge_base import KnowledgeBaseService, KnowledgeIndexStore
from agent.rag.rag_service import RagService
from agent.rag.retrieval_pipeline import RetrievalPipeline
from agent.utils.config_handler import load_rag_config


rag_config = load_rag_config()
storage_config = rag_config.get("storage", {})
DEFAULT_SQLITE_PATH = Path(storage_config.get("sqlite_path", "data/sqlite/knowledge_base.sqlite"))
DEFAULT_HISTORY_STORE = storage_config.get("history_store", "memory/chat_history/{session_id}.json")
templates = Jinja2Templates(directory="app/templates")


def sanitize_session_id(session_id: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "-", session_id.strip())[:64]
    return cleaned or "default"


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"


class ChunkMetadata(BaseModel):
    chunk_id: str | None = None
    chunk_hash: str | None = None
    document_id: str | None = None
    document_hash: str | None = None
    chunk_index: int | None = None
    source: str | None = None
    created_at: str | None = None
    operator: str | None = None
    text_length: int | None = None


class ChunkItem(BaseModel):
    id: str
    chunk_id: str
    chunk_hash: str
    document_id: str
    chunk_index: int
    text: str
    text_length: int
    source: str
    status: str
    operator: str
    created_at: str
    updated_at: str
    deleted_at: str | None = None
    metadata: ChunkMetadata


class DocumentItem(BaseModel):
    document_id: str
    document_hash: str
    filename: str
    source: str
    content_type: str | None = None
    size_bytes: int
    status: str
    active_chunk_count: int
    total_chunk_count: int
    added_chunk_count: int
    reassigned_chunk_count: int
    operator: str
    created_at: str
    updated_at: str
    deleted_at: str | None = None
    chunks: list[ChunkItem]


class DocumentListResponse(BaseModel):
    count: int
    documents: list[DocumentItem]


class UploadDocumentResponse(BaseModel):
    document_id: str
    document_hash: str
    filename: str
    content_type: str | None = None
    status: str
    is_duplicate: bool
    chunk_count: int
    active_chunk_count: int
    added_chunk_count: int
    reassigned_chunk_count: int
    message: str


class RetrieveRequest(BaseModel):
    query: str
    top_k: int = 5


class RetrieveResultItem(BaseModel):
    id: str
    text: str
    metadata: ChunkMetadata
    score: float


class RetrieveResponse(BaseModel):
    query: str
    top_k: int
    results: list[RetrieveResultItem]


class DeleteDocumentResponse(BaseModel):
    document_id: str
    deleted: bool
    deleted_chunk_count: int
    message: str


class DeleteDocumentChunkResponse(BaseModel):
    document_id: str
    chunk_id: str
    deleted: bool
    document_status: str
    remaining_chunks: int
    message: str


def create_app(sqlite_path: str | Path = DEFAULT_SQLITE_PATH) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db_path = Path(sqlite_path)
        if db_path.parent != Path(""):
            db_path.parent.mkdir(parents=True, exist_ok=True)

        knowledge_index_store = KnowledgeIndexStore(db_path)
        knowledge_base = KnowledgeBaseService(knowledge_index_store)
        retrieval_pipeline = RetrievalPipeline(knowledge_base)
        rag_service = RagService(retrieval_pipeline)
        rag_chat_chain = RagChatChain(retrieval_pipeline)

        app.state.sqlite = knowledge_index_store.sqlite
        app.state.knowledge_index_store = knowledge_index_store
        app.state.knowledge_base = knowledge_base
        app.state.retrieval_pipeline = retrieval_pipeline
        app.state.rag_service = rag_service
        app.state.rag_chat_chain = rag_chat_chain

        try:
            yield
        finally:
            knowledge_index_store.close()

    app = FastAPI(title="智能对话智能体", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory="app/static"), name="static")

    @app.get("/", response_class=HTMLResponse)
    def homepage(request: Request):
        return templates.TemplateResponse(request, "index.html")

    @app.get("/admin/rag", response_class=HTMLResponse)
    def rag_admin_page(request: Request):
        return templates.TemplateResponse(request, "admin_rag.html")

    @app.post("/api/chat")
    def chat(payload: ChatRequest):
        query = payload.message.strip()
        if not query:
            raise HTTPException(status_code=400, detail="消息不能为空。")

        session_id = sanitize_session_id(payload.session_id)
        history_path = DEFAULT_HISTORY_STORE.format(session_id=session_id)
        chat_config = {
            "configurable": {
                "session_id": history_path,
            }
        }

        def stream_reply():
            try:
                for chunk in app.state.rag_chat_chain.chain.stream({"query": query}, chat_config):
                    if chunk:
                        yield chunk
            except Exception as exc:
                yield f"\n\n抱歉，RAG 回复生成失败：{exc}"

        return StreamingResponse(stream_reply(), media_type="text/plain; charset=utf-8")

    @app.post("/api/knowledge/upload", response_model=UploadDocumentResponse)
    async def upload_knowledge_file(file: UploadFile = File(...)):
        file_name = file.filename or "uploaded_document"
        content = await file.read()
        try:
            content_text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=400, detail="当前只支持 UTF-8 文本文档。") from exc

        return app.state.knowledge_base.upload_document(
            content_text,
            file_name,
            content_type=file.content_type,
            operator="admin",
        )

    @app.get("/api/admin/rag/documents", response_model=DocumentListResponse)
    def admin_rag_documents():
        documents = app.state.knowledge_base.list_documents()
        return {"count": len(documents), "documents": documents}

    @app.get("/api/admin/rag/documents/{document_id}", response_model=DocumentItem)
    def admin_rag_document(document_id: str):
        document = app.state.knowledge_base.get_document(document_id)
        if not document:
            raise HTTPException(status_code=404, detail="document 不存在或已被删除。")
        return document

    @app.delete("/api/admin/rag/documents/{document_id}", response_model=DeleteDocumentResponse)
    def admin_delete_rag_document(document_id: str):
        result = app.state.knowledge_base.delete_document(document_id)
        if not result:
            raise HTTPException(status_code=404, detail="document 不存在或已被删除。")
        return result

    @app.delete(
        "/api/admin/rag/documents/{document_id}/chunks/{chunk_id}",
        response_model=DeleteDocumentChunkResponse,
    )
    def admin_delete_rag_document_chunk(document_id: str, chunk_id: str):
        result = app.state.knowledge_base.delete_document_chunk(document_id, chunk_id)
        if not result:
            raise HTTPException(status_code=404, detail="chunk 不存在、已被删除或不属于该 document。")
        return result

    @app.post("/api/admin/rag/retrieve", response_model=RetrieveResponse)
    def admin_rag_retrieve(payload: RetrieveRequest):
        query = payload.query.strip()
        if not query:
            raise HTTPException(status_code=400, detail="query 不能为空。")
        if payload.top_k < 1:
            raise HTTPException(status_code=400, detail="top_k 必须大于 0。")

        results = app.state.rag_service.retrieve(query, top_k=payload.top_k)
        return {"query": query, "top_k": payload.top_k, "results": results}

    return app


app = create_app()
