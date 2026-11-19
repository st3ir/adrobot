"""Optional bootstrap operator account."""

from __future__ import annotations

import pytest
from app.core.config import Settings
from app.core.container import build_container
from app.core.security import verify_password
from app.db.base import Base
from app.db.models import User
from app.services.bootstrap import ensure_bootstrap_user
from pydantic import SecretStr
from sqlalchemy import select

from tests.fakes import FakeKeitaro


@pytest.fixture
async def make_container(settings: Settings):
    created = []

    async def factory(**overrides):
        container = build_container(
            settings.model_copy(update=overrides), keitaro=FakeKeitaro()
        )
        async with container.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        created.append(container)
        return container

    yield factory
    for container in created:
        await container.aclose()


class TestEnsureBootstrapUser:
    async def test_does_nothing_without_configuration(self, make_container) -> None:
        container = await make_container()
        await ensure_bootstrap_user(container)
        async with container.session_factory() as session:
            assert (await session.scalars(select(User))).all() == []

    async def test_creates_the_configured_account(self, make_container) -> None:
        container = await make_container(
            bootstrap_user_email="Boot@Example.com",
            bootstrap_user_password=SecretStr("bootstrap-password"),
        )
        await ensure_bootstrap_user(container)
        async with container.session_factory() as session:
            user = await session.scalar(select(User))
        assert user is not None
        assert user.email == "boot@example.com"
        assert verify_password("bootstrap-password", user.password_hash)

    async def test_is_idempotent_and_never_resets_a_password(
        self, make_container
    ) -> None:
        container = await make_container(
            bootstrap_user_email="boot@example.com",
            bootstrap_user_password=SecretStr("bootstrap-password"),
        )
        await ensure_bootstrap_user(container)
        async with container.session_factory() as session, session.begin():
            user = await session.scalar(select(User))
            assert user is not None
            user.password_hash = "changed-by-an-operator"

        await ensure_bootstrap_user(container)
        async with container.session_factory() as session:
            users = (await session.scalars(select(User))).all()
        assert len(users) == 1
        assert users[0].password_hash == "changed-by-an-operator"
