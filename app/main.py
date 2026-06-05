from contextlib import asynccontextmanager
from pathlib import Path
import re

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from memory.knowledge_base import KnowledgeBaseService, TextHashService
from memory.rag import RagService


DEFAULT_SQLITE_PATH = Path("data/sqlite/knowledge_base.sqlite")
templates = Jinja2Templates(directory="app/templates")


def sanitize_session_id(session_id: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "-", session_id.strip())[:64]
    return cleaned or "default"


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"


class ChunkMetadata(BaseModel):
    source: str | None = None
    created_at: str | None = None
    operator: str | None = None


class ChunkItem(BaseModel):
    id: str
    text: str
    metadata: ChunkMetadata


class ChunkListResponse(BaseModel):
    count: int
    chunks: list[ChunkItem]


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


def create_app(sqlite_path: str | Path = DEFAULT_SQLITE_PATH) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db_path = Path(sqlite_path)
        if db_path.parent != Path(""):
            db_path.parent.mkdir(parents=True, exist_ok=True)

        text_hash_service = TextHashService(db_path)
        knowledge_base = KnowledgeBaseService(text_hash_service)

        app.state.sqlite = text_hash_service.sqlite
        app.state.text_hash_service = text_hash_service
        app.state.knowledge_base = knowledge_base
        app.state.rag_service = RagService(knowledge_base)

        try:
            yield
        finally:
            text_hash_service.close()

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
        history_path = app.state.knowledge_base.config.history_store.format(session_id=session_id)
        chat_config = {
            "configurable": {
                "session_id": history_path,
            }
        }

        def stream_reply():
            try:
                for chunk in app.state.rag_service.chain.stream({"query": query}, chat_config):
                    if chunk:
                        yield chunk
            except Exception as exc:
                yield f"\n\n抱歉，RAG 回复生成失败：{exc}"

        return StreamingResponse(stream_reply(), media_type="text/plain; charset=utf-8")

    @app.post("/api/knowledge/upload")
    async def upload_knowledge_file(request: Request, file: UploadFile = File(...)):
        file_name = file.filename
        content = await file.read()
        content_text = content.decode("utf-8")

        content_hash = app.state.text_hash_service.get_md5_hash(content_text)
        is_updated = app.state.knowledge_base.update_by_text(content_text, file_name)

        return {
            "filename": file_name,
            "content_type": file.content_type,
            "content_hash": content_hash,
            "is_duplicate": not is_updated,
            "is_new_text": is_updated,
            "status": "indexed" if is_updated else "duplicate",
            "message": "文本已写入 Chroma 向量库。" if is_updated else "文本 MD5 已存在，跳过重复入库。",
        }

    @app.get("/api/knowledge/chunks", response_model=ChunkListResponse)
    def list_knowledge_chunks():
        chunks = app.state.knowledge_base.list_chunks()
        return {"count": len(chunks), "chunks": chunks}

    @app.get("/api/admin/rag/chunks", response_model=ChunkListResponse)
    def admin_rag_chunks():
        chunks = app.state.knowledge_base.list_chunks()
        return {"count": len(chunks), "chunks": chunks}

    @app.post("/api/admin/rag/retrieve", response_model=RetrieveResponse)
    def admin_rag_retrieve(payload: RetrieveRequest):
        results = app.state.knowledge_base.retrive(payload.query, top_k=payload.top_k)
        return {"query": payload.query, "top_k": payload.top_k, "results": results}

    return app

app = create_app()
