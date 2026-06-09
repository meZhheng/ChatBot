import json
import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.core.dependencies import get_agent_service
from app.schemas.chat import ChatRequest


router = APIRouter()
SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


@router.post("/api/chat")
def chat(payload: ChatRequest, request: Request):
    query = payload.message.strip()
    session_id = payload.session_id.strip()
    if not query:
        raise HTTPException(status_code=400, detail="消息不能为空。")
    if not SESSION_ID_PATTERN.fullmatch(session_id):
        raise HTTPException(status_code=400, detail="session_id 格式无效。")

    agent_service = get_agent_service(request)

    def stream_reply():
        try:
            for event in agent_service.execute_stream(query, session_id):
                if event:
                    yield json.dumps(event, ensure_ascii=False) + "\n"
        except Exception as e:
            yield json.dumps(
                {
                    "type": "error",
                    "session_id": session_id,
                    "role": "assistant",
                    "content": f"抱歉，回复生成失败：{e}",
                },
                ensure_ascii=False,
            ) + "\n"

    return StreamingResponse(stream_reply(), media_type="application/x-ndjson; charset=utf-8")


@router.delete("/api/chat/sessions/{session_id}")
def delete_chat_session(session_id: str, request: Request):
    session_id = session_id.strip()
    if not SESSION_ID_PATTERN.fullmatch(session_id):
        raise HTTPException(status_code=400, detail="session_id 格式无效。")

    agent_service = get_agent_service(request)
    agent_service.delete_session(session_id)
    return {"deleted": True, "session_id": session_id}
