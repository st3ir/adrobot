"""FastAPI dependencies: container access, DB sessions, auth and CSRF."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.middleware import client_address
from app.core.config import Settings
from app.core.container import Container
from app.core.exceptions import AuthenticationError, CsrfError
from app.core.security import tokens_match
from app.db.models import User
from app.services.audit import AuditService
from app.services.campaign_creator import CampaignCreatorService
from app.services.catalog import CatalogService
from app.services.draft import CampaignDraftService

CSRF_HEADER = "X-CSRF-Token"
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def get_container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


ContainerDep = Annotated[Container, Depends(get_container)]


def get_settings(container: ContainerDep) -> Settings:
    return container.settings


SettingsDep = Annotated[Settings, Depends(get_settings)]


async def get_session(container: ContainerDep) -> AsyncIterator[AsyncSession]:
    """Per-request transactional database session."""
    async with container.session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_audit_service(session: SessionDep) -> AuditService:
    return AuditService(session)


AuditDep = Annotated[AuditService, Depends(get_audit_service)]


async def get_current_user(
    request: Request, container: ContainerDep, session: SessionDep
) -> User:
    """Resolve the signed session cookie into an active user."""
    token = request.cookies.get(container.settings.session_cookie_name)
    if not token:
        raise AuthenticationError
    payload = container.session_codec.decode(token)
    if payload is None:
        raise AuthenticationError("Your session has expired. Please sign in again.")

    user = await session.scalar(select(User).where(User.id == payload.user_id))
    if user is None or not user.is_active:
        raise AuthenticationError

    # Stash the CSRF token so :func:`verify_csrf` does not decode twice.
    request.state.csrf_token = payload.csrf_token
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def verify_csrf(request: Request, user: CurrentUser) -> User:
    """Double-submit CSRF check for every state-changing request."""
    if request.method not in _UNSAFE_METHODS:
        return user
    expected: str | None = getattr(request.state, "csrf_token", None)
    provided = request.headers.get(CSRF_HEADER)
    if not expected or not provided or not tokens_match(expected, provided):
        raise CsrfError
    return user


AuthorizedUser = Annotated[User, Depends(verify_csrf)]


def get_catalog_service(container: ContainerDep) -> CatalogService:
    return container.catalog


def get_creator_service(container: ContainerDep) -> CampaignCreatorService:
    return container.creator


def get_draft_service(container: ContainerDep, session: SessionDep) -> CampaignDraftService:
    """The editor works on a local draft, so it needs the request session."""
    return CampaignDraftService(
        session=session,
        campaigns=container.gateway,
        streams=container.gateway,
        catalog=container.catalog,
        stats=container.stats,
    )


CatalogDep = Annotated[CatalogService, Depends(get_catalog_service)]
CreatorDep = Annotated[CampaignCreatorService, Depends(get_creator_service)]
DraftDep = Annotated[CampaignDraftService, Depends(get_draft_service)]


def get_client_ip(request: Request) -> str:
    return client_address(request.scope)


ClientIp = Annotated[str, Depends(get_client_ip)]
