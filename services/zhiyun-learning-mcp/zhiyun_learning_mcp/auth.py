# meeting_assistant/auth.py
"""多租户鉴权：MCP API key -> principal 的解析与请求级上下文。"""
from dataclasses import dataclass
from contextvars import ContextVar
from typing import Optional

from .config import Settings

@dataclass(frozen=True)
class Principal:
    key_id: int
    phone: str


# 每个 HTTP 请求独立且可跨 await 安全传播；没有凭证时绝不回退默认用户。
_principal_ctx: ContextVar[Optional[Principal]] = ContextVar(
    "mcp_principal", default=None)


def set_principal(principal: Optional[Principal]):
    """中间件在鉴权通过后调用，绑定本次请求的可信身份。"""
    return _principal_ctx.set(principal)


def current_principal() -> Principal:
    principal = _principal_ctx.get()
    if principal is None:
        raise PermissionError("MCP request has no authenticated principal")
    return principal


def current_phone(_settings: Settings | None = None) -> str:
    """返回已鉴权租户；保留可选参数仅兼容现有工具调用签名。"""
    return current_principal().phone


class ApiKeyMiddleware:
    """ASGI/Starlette 中间件：从请求头取 API key -> 解析 phone -> 绑定到请求上下文。

    key 取自 `Authorization: Bearer <key>` 或 `X-API-Key`。
    无 key 或 key 无效始终返回 401；不支持默认租户回退。
    """

    def __init__(self, app, settings: Settings, key_repo):
        self.app = app
        self.settings = settings
        self.key_repo = key_repo

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)

        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        key = self._extract(headers)

        try:
            principal_data = await self.key_repo.verify(key) if key else None
        except Exception:
            return await self._reject_unavailable(scope, send)
        if principal_data is None:
            return await self._reject(scope, send)

        principal = Principal(**principal_data)
        token = set_principal(principal)
        try:
            await self.app(scope, receive, send)
        finally:
            _principal_ctx.reset(token)

    @staticmethod
    def _extract(headers) -> str | None:
        auth = headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            return auth[7:].strip() or None
        xk = headers.get("x-api-key")
        return xk.strip() if xk else None

    @staticmethod
    async def _reject(scope, send):
        body = b'{"error":"missing or invalid api key"}'
        await send({"type": "http.response.start", "status": 401,
                    "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": body})

    @staticmethod
    async def _reject_unavailable(scope, send):
        body = b'{"error":"authentication backend unavailable"}'
        await send({"type": "http.response.start", "status": 503,
                    "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": body})
