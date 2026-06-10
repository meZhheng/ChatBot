from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from app.core.dependencies import get_wecom_chat_service, get_wecom_client
from app.schemas.platforms import WeComSendMessageRequest, WeComSendMessageResponse
from app.services.wecom import (
    WeComClientError,
    WeComConfigError,
    WeComEncryptedCallbackUnsupported,
    WeComSignatureError,
)


router = APIRouter(prefix="/api/platforms/wecom", tags=["platforms:wecom"])


@router.get("/callback", response_class=PlainTextResponse)
def verify_callback(
    request: Request,
    msg_signature: str = Query(...),
    timestamp: str = Query(...),
    nonce: str = Query(...),
    echostr: str = Query(...),
):
    wecom_client = get_wecom_client(request)
    try:
        return PlainTextResponse(wecom_client.verify_url(msg_signature, timestamp, nonce, echostr))
    except WeComConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except WeComEncryptedCallbackUnsupported as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except WeComSignatureError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@router.post("/callback", response_class=PlainTextResponse)
async def receive_callback(
    request: Request,
    background_tasks: BackgroundTasks,
    msg_signature: str = Query(...),
    timestamp: str = Query(...),
    nonce: str = Query(...),
):
    try:
        body = (await request.body()).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="企业微信回调请求体必须是 UTF-8 XML。") from exc

    wecom_client = get_wecom_client(request)
    try:
        incoming = wecom_client.parse_callback_message(msg_signature, timestamp, nonce, body)
    except WeComConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except WeComEncryptedCallbackUnsupported as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except WeComSignatureError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except WeComClientError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    wecom_chat_service = get_wecom_chat_service(request)
    wecom_chat_service.schedule_message(incoming, background_tasks)
    return PlainTextResponse("success")


@router.post("/messages/send", response_model=WeComSendMessageResponse)
async def send_message(payload: WeComSendMessageRequest, request: Request):
    content = payload.content.strip()
    touser = payload.touser.strip() if payload.touser else None
    toparty = payload.toparty.strip() if payload.toparty else None
    totag = payload.totag.strip() if payload.totag else None
    if not content:
        raise HTTPException(status_code=400, detail="content 不能为空。")
    if payload.msgtype != "text":
        raise HTTPException(status_code=400, detail="当前只支持 text 消息。")
    if not any([touser, toparty, totag]):
        raise HTTPException(status_code=400, detail="touser、toparty、totag 至少需要提供一个。")

    wecom_client = get_wecom_client(request)
    try:
        raw = await wecom_client.send_text_message(
            content=content,
            touser=touser,
            toparty=toparty,
            totag=totag,
            safe=payload.safe,
        )
    except WeComConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except WeComClientError as exc:
        detail = {"message": str(exc), "wecom": exc.raw}
        raise HTTPException(status_code=502, detail=detail) from exc

    return {
        "errcode": int(raw.get("errcode", 0)),
        "errmsg": str(raw.get("errmsg", "ok")),
        "raw": raw,
    }
