from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from agent.bot import AgentService
from agent.rag.rag_service import RagService
from app.api import admin_faq, admin_rag, chat, faq, pages
from app.api.platforms import wecom
from app.core.config import DEFAULT_SQLITE_PATH, get_wecom_config
from app.services.chat_orchestrator import ChatOrchestrator
from app.services.chat_runtime import ChatRuntimeService
from app.services.conversation_history import ConversationHistoryStore
from app.services.wecom import WeComClient
from app.services.wecom_chat import WeComChatService
from faq.service import FaqService


def create_app(sqlite_path: str | Path = DEFAULT_SQLITE_PATH) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db_path = Path(sqlite_path)
        if db_path.parent != Path(""):
            db_path.parent.mkdir(parents=True, exist_ok=True)

        rag_service = RagService(db_path)
        faq_service = FaqService(rag_service.sqlite)
        agent_service = AgentService(rag_service.sqlite)
        chat_orchestrator = ChatOrchestrator(agent_service=agent_service, faq_service=faq_service)
        history_store = ConversationHistoryStore(rag_service.sqlite)
        chat_runtime = ChatRuntimeService(chat_orchestrator=chat_orchestrator, history_store=history_store)
        wecom_client = WeComClient(get_wecom_config())
        wecom_chat_service = WeComChatService(
            wecom_client=wecom_client,
            chat_runtime=chat_runtime,
            history_store=history_store,
        )

        app.state.sqlite = rag_service.sqlite
        app.state.rag_service = rag_service
        app.state.faq_service = faq_service
        app.state.agent_service = agent_service
        app.state.chat_orchestrator = chat_orchestrator
        app.state.conversation_history = history_store
        app.state.chat_runtime = chat_runtime
        app.state.wecom_client = wecom_client
        app.state.wecom_chat_service = wecom_chat_service

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
    app.include_router(admin_faq.router)
    app.include_router(faq.router)
    app.include_router(wecom.router)
    return app


app = create_app()
