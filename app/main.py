from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from agent.bot import AgentService
from agent.rag.rag_service import RagService
from app.api import admin_rag, chat, pages
from app.api.platforms import wecom
from app.core.config import DEFAULT_SQLITE_PATH, get_wecom_config
from app.services.wecom import WeComClient


def create_app(sqlite_path: str | Path = DEFAULT_SQLITE_PATH) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db_path = Path(sqlite_path)
        if db_path.parent != Path(""):
            db_path.parent.mkdir(parents=True, exist_ok=True)

        rag_service = RagService(db_path)
        agent_service = AgentService()
        wecom_client = WeComClient(get_wecom_config())

        app.state.sqlite = rag_service.sqlite
        app.state.rag_service = rag_service
        app.state.agent_service = agent_service
        app.state.wecom_client = wecom_client

        try:
            yield
        finally:
            await wecom_client.close()
            rag_service.close()

    app = FastAPI(title="智能对话智能体", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory="app/static"), name="static")
    app.include_router(pages.router)
    app.include_router(chat.router)
    app.include_router(admin_rag.router)
    app.include_router(wecom.router)
    return app


app = create_app()
