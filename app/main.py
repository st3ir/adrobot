"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.error_handlers import register_error_handlers
from app.api.middleware import (
    BodySizeLimitMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
)
from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.container import Container, build_container
from app.core.logging import configure_logging, get_logger
from app.core.rate_limit import SlidingWindowRateLimiter
from app.services.bootstrap import ensure_bootstrap_user

logger = get_logger(__name__)

WEB_DIR = Path(__file__).parent / "web"
STATIC_DIR = WEB_DIR / "static"


def create_app(
    settings: Settings | None = None,
    *,
    container_factory: Callable[[Settings], Container] | None = None,
) -> FastAPI:
    """Build the FastAPI application.

    ``container_factory`` lets tests swap the Keitaro integration without
    touching module globals.
    """
    settings = settings or get_settings()
    make_container = container_factory or build_container
    configure_logging(
        level="DEBUG" if settings.debug else "INFO",
        secrets=[
            settings.keitaro_api_key.get_secret_value(),
            settings.session_secret.get_secret_value(),
        ],
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        container: Container = make_container(settings)
        application.state.container = container
        await ensure_bootstrap_user(container)
        logger.info(
            "Adrobot started (environment=%s, keitaro=%s)",
            settings.environment,
            settings.keitaro_base_url,
        )
        try:
            yield
        finally:
            await container.aclose()

    application = FastAPI(
        title=f"{settings.app_name} — Keitaro wrapper",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.environment != "production" else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.environment != "production" else None,
    )

    register_error_handlers(application)
    application.include_router(api_router)

    @application.get("/health", tags=["system"], include_in_schema=False)
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    _mount_ui(application)
    _add_middleware(application, settings)
    return application


def _mount_ui(application: FastAPI) -> None:
    if not STATIC_DIR.is_dir():  # pragma: no cover - only in trimmed deployments
        logger.warning("Static directory %s is missing; UI disabled", STATIC_DIR)
        return

    application.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @application.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")


def _add_middleware(application: FastAPI, settings: Settings) -> None:
    """Register middleware.

    Starlette runs the *last* registered middleware first, so security headers
    are added last and therefore wrap every response, including the 429 and
    413 produced by the middleware below them.
    """
    application.add_middleware(
        BodySizeLimitMiddleware, max_bytes=settings.max_request_body_bytes
    )
    application.add_middleware(
        RateLimitMiddleware, limiter=LazyApiLimiter(application)
    )
    if settings.cors_origin_list:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origin_list,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH", "DELETE"],
            allow_headers=["Content-Type", "X-CSRF-Token"],
        )
    application.add_middleware(SecurityHeadersMiddleware, settings=settings)


class LazyApiLimiter:
    """Looks the limiter up on first use.

    Middleware is registered before the lifespan builds the container, so the
    limiter cannot be captured eagerly.
    """

    def __init__(self, application: FastAPI) -> None:
        self._application = application

    @property
    def _limiter(self) -> SlidingWindowRateLimiter:
        container: Container = self._application.state.container
        return container.api_limiter

    def allow(self, key: str) -> bool:
        return self._limiter.allow(key)

    def retry_after(self, key: str) -> int:
        return self._limiter.retry_after(key)


app = create_app()
