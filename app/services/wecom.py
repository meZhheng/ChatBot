import hashlib
import hmac
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import WeComConfig


class WeComError(Exception):
    pass


class WeComConfigError(WeComError):
    pass


class WeComSignatureError(WeComError):
    pass


class WeComEncryptedCallbackUnsupported(WeComError):
    pass


class WeComClientError(WeComError):
    def __init__(self, message: str, raw: dict[str, Any] | None = None):
        super().__init__(message)
        self.raw = raw or {}


@dataclass(frozen=True)
class WeComIncomingMessage:
    to_user_name: str | None
    from_user_name: str | None
    create_time: str | None
    msg_type: str | None
    content: str | None
    msg_id: str | None
    agent_id: str | None
    raw: dict[str, str]


class WeComClient:
    token_url = "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
    send_url = "https://qyapi.weixin.qq.com/cgi-bin/message/send"

    def __init__(self, config: WeComConfig):
        self.config = config
        self._http = httpx.AsyncClient(timeout=10.0)
        self._access_token: str | None = None
        self._access_token_expires_at = 0.0

    async def close(self):
        await self._http.aclose()

    def verify_url(self, msg_signature: str, timestamp: str, nonce: str, echostr: str) -> str:
        self._ensure_callback_configured()
        self._ensure_plain_callback()
        self._verify_signature(msg_signature, timestamp, nonce, echostr)
        return echostr

    def parse_callback_message(
        self,
        msg_signature: str,
        timestamp: str,
        nonce: str,
        body: str,
    ) -> WeComIncomingMessage:
        self._ensure_callback_configured()
        self._ensure_plain_callback()
        message = self._parse_xml(body)
        encrypted_payload = message.get("Encrypt")
        signature_payload = encrypted_payload or body
        self._verify_signature(msg_signature, timestamp, nonce, signature_payload)
        return WeComIncomingMessage(
            to_user_name=message.get("ToUserName"),
            from_user_name=message.get("FromUserName"),
            create_time=message.get("CreateTime"),
            msg_type=message.get("MsgType"),
            content=message.get("Content"),
            msg_id=message.get("MsgId"),
            agent_id=message.get("AgentID"),
            raw=message,
        )

    async def send_text_message(
        self,
        *,
        content: str,
        touser: str | None = None,
        toparty: str | None = None,
        totag: str | None = None,
        safe: int = 0,
    ) -> dict[str, Any]:
        self._ensure_send_configured()
        access_token = await self._get_access_token()
        payload: dict[str, Any] = {
            "msgtype": "text",
            "agentid": self._agent_id(),
            "text": {"content": content},
            "safe": safe,
        }
        if touser:
            payload["touser"] = touser
        if toparty:
            payload["toparty"] = toparty
        if totag:
            payload["totag"] = totag

        try:
            response = await self._http.post(self.send_url, params={"access_token": access_token}, json=payload)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as exc:
            raise WeComClientError("企业微信发送消息请求失败。") from exc
        except ValueError as exc:
            raise WeComClientError("企业微信发送消息响应不是有效 JSON。") from exc
        if data.get("errcode", 0) != 0:
            raise WeComClientError(data.get("errmsg", "企业微信发送消息失败。"), raw=data)
        return self._sanitize_response(data)

    def _ensure_callback_configured(self):
        if not self.config.callback_configured:
            raise WeComConfigError("企业微信回调 Token 未配置。")

    def _ensure_plain_callback(self):
        if self.config.callback_encrypted:
            raise WeComEncryptedCallbackUnsupported("企业微信加密回调暂未实现，请先使用明文回调模式。")

    def _ensure_send_configured(self):
        if not self.config.send_configured:
            raise WeComConfigError("企业微信发送消息所需的 CorpID、AgentID 或 Secret 未配置。")

    def _verify_signature(self, msg_signature: str, timestamp: str, nonce: str, payload: str):
        expected = self._signature(timestamp, nonce, payload)
        if not msg_signature or not hmac.compare_digest(msg_signature, expected):
            raise WeComSignatureError("企业微信回调签名校验失败。")

    def _signature(self, timestamp: str, nonce: str, payload: str) -> str:
        pieces = [self.config.callback_token or "", timestamp, nonce, payload]
        return hashlib.sha1("".join(sorted(pieces)).encode("utf-8")).hexdigest()

    def _parse_xml(self, body: str) -> dict[str, str]:
        try:
            root = ET.fromstring(body)
        except ET.ParseError as exc:
            raise WeComClientError("企业微信回调 XML 解析失败。") from exc
        return {child.tag: child.text or "" for child in root}

    async def _get_access_token(self) -> str:
        now = time.time()
        if self._access_token and now < self._access_token_expires_at:
            return self._access_token

        try:
            response = await self._http.get(
                self.token_url,
                params={"corpid": self.config.corp_id, "corpsecret": self.config.corp_secret},
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as exc:
            raise WeComClientError("企业微信 access_token 获取请求失败。") from exc
        except ValueError as exc:
            raise WeComClientError("企业微信 access_token 响应不是有效 JSON。") from exc
        if data.get("errcode", 0) != 0:
            raise WeComClientError(data.get("errmsg", "企业微信 access_token 获取失败。"), raw=data)

        access_token = data.get("access_token")
        if not access_token:
            raise WeComClientError("企业微信 access_token 响应缺少 token。", raw=data)

        expires_in = int(data.get("expires_in", 7200))
        self._access_token = access_token
        self._access_token_expires_at = now + max(expires_in - 300, 60)
        return access_token

    def _agent_id(self) -> int | str:
        agent_id = self.config.agent_id or ""
        return int(agent_id) if agent_id.isdigit() else agent_id

    def _sanitize_response(self, data: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in data.items() if key.lower() not in {"access_token", "token", "secret"}}

