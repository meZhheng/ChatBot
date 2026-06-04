import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from memory.knowledge_base import KnowledgeBaseService


DEFAULT_SQLITE_PATH = Path("data/knowledge_base.sqlite")
templates = Jinja2Templates(directory="app/templates")


class ChatRequest(BaseModel):
    message: str


def create_app(sqlite_path: str | Path = DEFAULT_SQLITE_PATH) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db_path = Path(sqlite_path)
        if db_path.parent != Path(""):
            db_path.parent.mkdir(parents=True, exist_ok=True)

        sqlite = sqlite3.connect(db_path, check_same_thread=False)
        app.state.sqlite = sqlite
        app.state.knowledge_base = KnowledgeBaseService(sqlite)

        try:
            yield
        finally:
            sqlite.close()

    app = FastAPI(title="智能对话智能体", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory="app/static"), name="static")

    @app.get("/", response_class=HTMLResponse)
    def homepage(request: Request):
        return templates.TemplateResponse(request, "index.html")

    @app.post("/api/chat")
    def chat(payload: ChatRequest):
        return {
            "reply": f"已收到你的消息：{payload.message}。后续会接入 LangChain + 千问 + Chroma 实现 RAG 回复。"
        }

    @app.post("/api/knowledge/upload")
    async def upload_knowledge_file(request: Request, file: UploadFile = File(...)):
        file_name = file.filename or "uploaded_file"
        content = await file.read()
        content_text = content.decode("utf-8")
        md5_record = request.app.state.knowledge_base.record_text_hash(
            text=content_text,
            source_name=file_name,
            content_type=file.content_type,
        )
        is_duplicate = md5_record["is_duplicate"]

        return {
            "filename": file_name,
            "content_type": file.content_type,
            "content_hash": md5_record["content_hash"],
            "is_duplicate": is_duplicate,
            "status": "duplicate" if is_duplicate else "indexed",
            "message": "文本 MD5 已存在，跳过重复入库。" if is_duplicate else "文本 MD5 已记录，后续可写入 Chroma 向量库。",
        }

    return app


app = create_app()
