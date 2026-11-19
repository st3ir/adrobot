"""ASGI middleware: security headers, body size limits, rate limiting."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import Settings
from app.core.logging import get_logger
from app.core.rate_limit import RateLimiter

logger = get_logger(__name__)

RequestResponseEndpoint = Callable[[Request], Awaitable[Response]]

#: The UI ships as external CSS/JS files, so no inline script/style is needed.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'none'; "
    "object-src 'none'"
)


class SecurityHeadersMiddleware:
    """Adds hardening headers to every response."""

    def __init__(self, app: ASGIApp, *, settings: Settings) -> None:
        self._app = app
        self._hsts = settings.environment != "local"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        path: str = scope.get("path", "")

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.setdefault("content-security-policy", CONTENT_SECURITY_POLICY)
                headers.setdefault("x-content-type-options", "nosniff")
                headers.setdefault("x-frame-options", "DENY")
                headers.setdefault("referrer-policy", "no-referrer")
                headers.setdefault(
                    "permissions-policy", "geolocation=(), camera=(), microphone=()"
                )
                headers.setdefault("cross-origin-opener-policy", "same-origin")
                headers.setdefault("cross-origin-resource-policy", "same-origin")
                if self._hsts:
                    headers.setdefault(
                        "strict-transport-security", "max-age=31536000; includeSubDomains"
                    )
                if path.startswith("/api/"):
                    headers.setdefault("cache-control", "no-store")
            await send(message)

        await self._app(scope, receive, send_with_headers)


class BodySizeLimitMiddleware:
    """Rejects request bodies larger than ``max_bytes`` with 413."""

    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self._app = app
        self._max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        if self._declared_too_large(scope):
            await self._reject(scope, receive, send)
            return

        received = 0
        too_large = False

        async def limited_receive() -> Message:
            nonlocal received, too_large
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self._max_bytes:
                    too_large = True
                    return {"type": "http.disconnect"}
            return message

        await self._app(scope, limited_receive, send)
        if too_large:  # pragma: no cover - defensive logging only
            logger.warning("Rejected oversized request body on %s", scope.get("path"))

    def _declared_too_large(self, scope: Scope) -> bool:
        for key, value in scope.get("headers", []):
            if key == b"content-length":
                try:
                    return int(value) > self._max_bytes
                except ValueError:
                    return True
        return False

    @staticmethod
    async def _reject(scope: Scope, receive: Receive, send: Send) -> None:
        response = JSONResponse(
            {"code": "payload_too_large", "message": "Request body is too large."},
            status_code=413,
        )
        await response(scope, receive, send)


class RateLimitMiddleware:
    """Per-client-IP rate limiting for the JSON API."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        limiter: RateLimiter,
        path_prefix: str = "/api/",
    ) -> None:
        self._app = app
        self._limiter = limiter
        self._prefix = path_prefix

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith(self._prefix):
            await self._app(scope, receive, send)
            return

        client_ip = client_address(scope)
        if not self._limiter.allow(client_ip):
            retry_after = self._limiter.retry_after(client_ip)
            response = JSONResponse(
                {"code": "rate_limited", "message": "Too many requests. Please slow down."},
                status_code=429,
                headers={"Retry-After": str(retry_after)},
            )
            await response(scope, receive, send)
            return

        await self._app(scope, receive, send)


def client_address(scope: Scope) -> str:
    """Best-effort client IP.

    ``X-Forwarded-For`` is deliberately ignored: it is attacker-controlled
    unless a trusted proxy rewrites it, and trusting it would let anyone
    bypass the rate limiter by rotating the header.
    """
    client = scope.get("client")
    if client:
        return str(client[0])
    return "unknown"
