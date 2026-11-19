"""Composition root.

Everything is wired here once at startup, so the rest of the code receives
collaborators instead of reaching for globals. Routers get them through
FastAPI dependencies in :mod:`app.api.deps`.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.rate_limit import SlidingWindowRateLimiter
from app.core.security import SessionTokenCodec
from app.db.session import create_engine, create_session_factory
from app.keitaro.client import KeitaroClient
from app.keitaro.gateway import KeitaroGateway
from app.keitaro.protocols import KeitaroPort
from app.services.campaign_creator import CampaignCreatorService
from app.services.catalog import CatalogService
from app.services.stats import StatsService


@dataclass(slots=True)
class Container:
    """Holds every long-lived object of the application."""

    settings: Settings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    keitaro_client: KeitaroClient
    gateway: KeitaroPort
    catalog: CatalogService
    creator: CampaignCreatorService
    stats: StatsService
    session_codec: SessionTokenCodec
    login_limiter: SlidingWindowRateLimiter
    api_limiter: SlidingWindowRateLimiter

    async def aclose(self) -> None:
        await self.keitaro_client.aclose()
        await self.engine.dispose()


def build_container(settings: Settings, *, keitaro: KeitaroPort | None = None) -> Container:
    """Construct the object graph from settings.

    ``keitaro`` replaces the live gateway; the application never passes it,
    tests do. It is the one seam that keeps the whole stack testable
    without patching imports.
    """
    engine = create_engine(settings.database_url, echo=settings.debug)
    session_factory = create_session_factory(engine)

    keitaro_client = KeitaroClient(
        api_root=settings.keitaro_api_root,
        api_key=settings.keitaro_api_key.get_secret_value(),
        timeout_seconds=settings.keitaro_timeout_seconds,
        max_retries=settings.keitaro_max_retries,
    )
    gateway: KeitaroPort = keitaro or KeitaroGateway(keitaro_client)

    catalog = CatalogService(
        gateway,
        ttl_seconds=settings.keitaro_cache_ttl_seconds,
        preferred_domain=settings.keitaro_default_domain,
        preferred_group=settings.keitaro_default_group,
        preferred_source=settings.keitaro_default_source,
    )
    stats = StatsService(gateway)
    creator = CampaignCreatorService(
        campaigns=gateway,
        streams=gateway,
        catalog=catalog,
        name_prefix=settings.campaign_name_prefix,
        redirect_url=settings.geo_redirect_url,
    )
    return Container(
        settings=settings,
        engine=engine,
        session_factory=session_factory,
        keitaro_client=keitaro_client,
        gateway=gateway,
        catalog=catalog,
        creator=creator,
        stats=stats,
        session_codec=SessionTokenCodec(
            settings.effective_session_secret,
            max_age_seconds=settings.session_ttl_seconds,
        ),
        login_limiter=SlidingWindowRateLimiter(
            settings.login_rate_limit_attempts, settings.login_rate_limit_window_seconds
        ),
        api_limiter=SlidingWindowRateLimiter(
            settings.api_rate_limit_requests, settings.api_rate_limit_window_seconds
        ),
    )
