from fastapi import Request
from app.services.chat_runtime import ChatRuntimeService

def get_rag_service(request: Request):
    return request.app.state.rag_service


def get_faq_service(request: Request):
    return request.app.state.faq_service


def get_agent_service(request: Request):
    return request.app.state.agent_service


def get_chat_orchestrator(request: Request):
    return request.app.state.chat_orchestrator


def get_conversation_history(request: Request):
    return request.app.state.conversation_history


def get_chat_runtime(request: Request) -> ChatRuntimeService:
    return request.app.state.chat_runtime


def get_wecom_client(request: Request):
    return request.app.state.wecom_client


def get_wecom_chat_service(request: Request):
    return request.app.state.wecom_chat_service
