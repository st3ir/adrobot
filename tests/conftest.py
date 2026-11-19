"""Shared test fixtures."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from app.core.config import Settings
from app.core.container import Container, build_container
from app.core.security import hash_password
from app.db.base import Base
from app.db.models import User
from app.main import create_app
from app.services.draft import CampaignDraftService
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from tests.fakes import FakeKeitaro

TEST_PASSWORD = "correct-horse-battery-staple"
TEST_EMAIL = "operator@example.com"


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        environment="local",
        debug=False,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        keitaro_base_url="https://keitaro.test",
        keitaro_api_key=SecretStr("test-api-key"),
        keitaro_cache_ttl_seconds=0,
        campaign_name_prefix="test_ivanov_",
        geo_redirect_url="https://google.com",
        session_secret=SecretStr("a" * 48),
        cookie_secure=False,
        login_rate_limit_attempts=5,
        api_rate_limit_requests=1000,
    )


@pytest.fixture
def keitaro() -> FakeKeitaro:
    return FakeKeitaro()


@pytest.fixture
async def container(settings: Settings, keitaro: FakeKeitaro) -> AsyncIterator[Container]:
    built = build_container(settings, keitaro=keitaro)
    async with built.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield built
    finally:
        await built.aclose()


@pytest.fixture
async def db_session(container: Container) -> AsyncIterator[AsyncSession]:
    async with container.session_factory() as session:
        yield session


@pytest.fixture
async def user(container: Container) -> User:
    async with container.session_factory() as session, session.begin():
        account = User(email=TEST_EMAIL, password_hash=hash_password(TEST_PASSWORD))
        session.add(account)
    async with container.session_factory() as session:
        return await session.get(User, 1)  # type: ignore[return-value]


@pytest.fixture
async def draft_service(container: Container, db_session: AsyncSession):
    """The editor service, wired to the test container's fake Keitaro."""
    return CampaignDraftService(
        session=db_session,
        campaigns=container.gateway,
        streams=container.gateway,
        catalog=container.catalog,
        stats=container.stats,
    )


@pytest.fixture
def app(settings: Settings, container: Container):
    """FastAPI app wired to the test container.

    ``ASGITransport`` does not run the lifespan, so the container that the
    fixtures own is attached directly.
    """
    application = create_app(settings, container_factory=lambda _: container)
    application.state.container = container
    return application


@pytest.fixture
async def client(app) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


@pytest.fixture
async def auth_client(client: httpx.AsyncClient, user: User) -> httpx.AsyncClient:
    """A client with an authenticated session and the CSRF header set."""
    response = await client.post(
        "/api/v1/auth/login", json={"email": TEST_EMAIL, "password": TEST_PASSWORD}
    )
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return client
