"""Low-level HTTP transport for the Keitaro Admin API.

Single responsibility: authenticate, send, retry, map upstream failures onto
our own exception hierarchy. It knows nothing about campaigns or offers.
"""

from __future__ import annotations

import asyncio
import re
from types import TracebackType
from typing import Any, Final, Self

import httpx

from app.core.exceptions import (
    KeitaroAuthError,
    KeitaroError,
    KeitaroNotFoundError,
    KeitaroUnavailableError,
    KeitaroValidationError,
)
from app.core.logging import get_logger

logger = get_logger(__name__)

#: Paths are built by this package only; this guard makes sure a caller can
#: never smuggle a different host, a traversal segment or a query string in
#: through a relative path (SSRF defence).
_SAFE_SEGMENT: Final = re.compile(r"[A-Za-z0-9_~-][A-Za-z0-9_.~-]*")

_RETRYABLE_STATUS: Final = frozenset({429, 502, 503, 504})
_IDEMPOTENT_METHODS: Final = frozenset({"GET", "HEAD", "PUT", "DELETE"})
_MAX_RESPONSE_BYTES: Final = 8 * 1024 * 1024


class KeitaroClient:
    """Thin async HTTP client for ``/admin_api/v1``."""

    def __init__(
        self,
        *,
        api_root: str,
        api_key: str,
        timeout_seconds: float = 20.0,
        max_retries: int = 2,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key:
            logger.warning("Keitaro API key is empty; every request will fail with 401.")
        self._api_root = api_root.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._api_root,
            timeout=httpx.Timeout(timeout_seconds),
            headers={
                "Api-Key": api_key,
                "Accept": "application/json",
                "User-Agent": "adrobot/1.0",
            },
            transport=transport,
            follow_redirects=False,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
        self._max_retries = max_retries

    # -- lifecycle ---------------------------------------------------------
    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    # -- requests ----------------------------------------------------------
    async def get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        return await self.request("GET", path, params=params)

    async def post(self, path: str, *, json: Any = None) -> Any:
        return await self.request("POST", path, json=json)

    async def put(self, path: str, *, json: Any = None) -> Any:
        return await self.request("PUT", path, json=json)

    async def delete(self, path: str) -> Any:
        return await self.request("DELETE", path)

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Send a request and return the decoded JSON body."""
        self._assert_safe_path(path)
        attempts = self._max_retries + 1 if method.upper() in _IDEMPOTENT_METHODS else 1
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                response = await self._client.request(
                    method, path, json=json, params=self._clean_params(params)
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                logger.warning(
                    "Keitaro %s %s failed (attempt %s/%s): %s",
                    method,
                    path,
                    attempt,
                    attempts,
                    type(exc).__name__,
                )
                if attempt == attempts:
                    raise KeitaroUnavailableError(detail=str(exc)) from exc
                await self._backoff(attempt)
                continue

            if response.status_code in _RETRYABLE_STATUS and attempt < attempts:
                await self._backoff(attempt)
                continue

            return self._handle_response(method, path, response)

        raise KeitaroUnavailableError(detail=str(last_error))  # pragma: no cover

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def _assert_safe_path(path: str) -> None:
        """Reject anything that is not a plain absolute path segment chain."""
        segments = path[1:].split("/") if path.startswith("/") else []
        if (
            not path.startswith("/")
            or path.startswith("//")
            or not segments
            or any(not _SAFE_SEGMENT.fullmatch(segment) for segment in segments)
        ):
            msg = f"Unsafe Keitaro API path: {path!r}"
            raise ValueError(msg)

    @staticmethod
    def _clean_params(params: dict[str, Any] | None) -> dict[str, Any] | None:
        if not params:
            return None
        return {key: value for key, value in params.items() if value is not None}

    @staticmethod
    async def _backoff(attempt: int) -> None:
        await asyncio.sleep(min(0.25 * 2 ** (attempt - 1), 2.0))

    def _handle_response(self, method: str, path: str, response: httpx.Response) -> Any:
        status = response.status_code

        if status == httpx.codes.UNAUTHORIZED or status == httpx.codes.FORBIDDEN:
            raise KeitaroAuthError(detail=f"{method} {path} -> {status}")
        if httpx.codes.MULTIPLE_CHOICES <= status < httpx.codes.BAD_REQUEST:
            # Redirects are not followed; a tracker that answers with one is
            # misconfigured and replaying the Api-Key elsewhere is unsafe.
            raise KeitaroError(detail=f"{method} {path} -> unexpected redirect {status}")
        if status == httpx.codes.NOT_FOUND:
            raise KeitaroNotFoundError(detail=f"{method} {path} -> 404")
        if status in _RETRYABLE_STATUS or status >= httpx.codes.INTERNAL_SERVER_ERROR:
            raise KeitaroUnavailableError(detail=f"{method} {path} -> {status}")
        if status >= httpx.codes.BAD_REQUEST:
            raise KeitaroValidationError(
                self._extract_message(response) or KeitaroValidationError.safe_message,
                detail=f"{method} {path} -> {status}: {response.text[:500]}",
            )

        if not response.content:
            return None
        if len(response.content) > _MAX_RESPONSE_BYTES:
            raise KeitaroError(detail="Keitaro response exceeded the size limit")
        try:
            return response.json()
        except ValueError as exc:
            raise KeitaroError(detail=f"Malformed JSON from {method} {path}") from exc

    @staticmethod
    def _extract_message(response: httpx.Response) -> str | None:
        """Pull a short, user-safe message out of a Keitaro error body."""
        try:
            body = response.json()
        except ValueError:
            return None
        if isinstance(body, dict):
            for key in ("error", "message", "detail"):
                value = body.get(key)
                if isinstance(value, str) and value:
                    return f"Keitaro: {value[:200]}"
            errors = body.get("errors")
            if isinstance(errors, list) and errors:
                parts = [str(item)[:80] for item in errors[:3]]
                return f"Keitaro: {'; '.join(parts)}"
            if isinstance(errors, dict) and errors:
                return KeitaroClient._format_field_errors(errors)
            # Keitaro also answers with {"field": ["message", ...]} directly.
            field_errors = {
                key: value
                for key, value in body.items()
                if isinstance(value, list) and value
            }
            if field_errors:
                return KeitaroClient._format_field_errors(field_errors)
        return None

    @staticmethod
    def _format_field_errors(errors: dict[str, Any]) -> str:
        """Render Keitaro's per-field error lists as one short sentence."""
        parts = []
        for field, messages in list(errors.items())[:3]:
            first = messages[0] if isinstance(messages, list) and messages else messages
            parts.append(f"{field}: {str(first)[:80]}")
        return f"Keitaro: {'; '.join(parts)}"
