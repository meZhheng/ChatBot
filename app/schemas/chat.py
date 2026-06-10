from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str
    session_id: str = Field(..., min_length=1, max_length=128)
    user_id: str | None = None
    stream: bool = True


class ChatResponse(BaseModel):
    session_id: str
    user_id: str | None = None
    role: str = "assistant"
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    usage: dict[str, Any] = Field(default_factory=dict)
