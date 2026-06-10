from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.core.dependencies import get_agent_service, get_chat_runtime
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.chat_runtime import SESSION_ID_PATTERN


router = APIRouter()


@router.post("/api/chat", response_model=ChatResponse | None)
def chat(payload: ChatRequest, request: Request):
    chat_runtime = get_chat_runtime(request)
    try:
        chat_runtime.validate(message=payload.message, session_id=payload.session_id)
        if payload.stream:
            return StreamingResponse(
                chat_runtime.stream_ndjson(
                    message=payload.message,
                    session_id=payload.session_id,
                    user_id=payload.user_id,
                    channel="web",
                ),
                media_type="application/x-ndjson; charset=utf-8",
            )
        return chat_runtime.complete(
            message=payload.message,
            session_id=payload.session_id,
            user_id=payload.user_id,
            channel="web",
        ).as_dict()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/api/chat/sessions/{session_id}")
def delete_chat_session(session_id: str, request: Request):
    session_id = session_id.strip()
    if not SESSION_ID_PATTERN.fullmatch(session_id):
        raise HTTPException(status_code=400, detail="session_id 格式无效。")

    agent_service = get_agent_service(request)
    agent_service.delete_session(session_id)
    return {"deleted": True, "session_id": session_id}
