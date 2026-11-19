"""Exception handlers that keep internals out of HTTP responses."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse

from app.core.exceptions import AdrobotError, RateLimitedError
from app.core.logging import get_logger
from app.services.naming import InvalidCampaignNameError

logger = get_logger(__name__)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AdrobotError)
    async def _domain_error(_: Request, exc: AdrobotError) -> JSONResponse:
        if exc.detail:
            logger.warning("%s: %s", exc.code, exc.detail)
        headers = {}
        if isinstance(exc, RateLimitedError):
            headers["Retry-After"] = str(exc.retry_after)
        return JSONResponse(
            {"code": exc.code, "message": exc.safe_message},
            status_code=exc.status_code,
            headers=headers,
        )

    @app.exception_handler(InvalidCampaignNameError)
    async def _invalid_name(_: Request, exc: InvalidCampaignNameError) -> JSONResponse:
        return JSONResponse(
            {"code": "invalid_campaign_name", "message": str(exc)}, status_code=422
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            {"code": "validation_error", "message": _first_message(exc)}, status_code=422
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return JSONResponse(
            {"code": f"http_{exc.status_code}", "message": detail},
            status_code=exc.status_code,
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            {"code": "internal_error", "message": "Unexpected server error."},
            status_code=500,
        )


def _first_message(exc: RequestValidationError) -> str:
    """Turn pydantic's error list into one short, safe sentence."""
    for error in exc.errors():
        location = ".".join(str(part) for part in error.get("loc", ()) if part != "body")
        message = str(error.get("msg", "invalid value"))
        message = message.removeprefix("Value error, ")
        return f"{location}: {message}" if location else message
    return "Invalid request payload."
