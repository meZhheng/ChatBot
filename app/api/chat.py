from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.core.dependencies import get_agent_service
from app.schemas.chat import ChatRequest


router = APIRouter()


@router.post("/api/chat")
def chat(payload: ChatRequest, request: Request):
    query = payload.message.strip()
    if not query:
        raise HTTPException(status_code=400, detail="消息不能为空。")

    agent_service = get_agent_service(request)

    def stream_reply():
        try:
            for chunk in agent_service.execute_stream(query):
                if chunk:
                    yield chunk
        except Exception as e:
            yield f"\n\n抱歉，RAG 回复生成失败：{e}"

    return StreamingResponse(stream_reply(), media_type="text/plain; charset=utf-8")
