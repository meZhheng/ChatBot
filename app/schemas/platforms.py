from typing import Any

from pydantic import BaseModel


class WeComSendMessageRequest(BaseModel):
    touser: str | None = None
    toparty: str | None = None
    totag: str | None = None
    msgtype: str = "text"
    content: str
    safe: int = 0


class WeComSendMessageResponse(BaseModel):
    errcode: int
    errmsg: str
    raw: dict[str, Any]
