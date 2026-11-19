"""Session authentication endpoints."""

from __future__ import annotations

from contextlib import suppress

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import select

from app.api.deps import AuditDep, ClientIp, ContainerDep, CurrentUser, SessionDep
from app.core.exceptions import InvalidCredentialsError, RateLimitedError
from app.core.logging import get_logger
from app.core.security import (
    SessionPayload,
    dummy_verify,
    generate_csrf_token,
    hash_password,
    needs_rehash,
    verify_password,
)
from app.db.models import AuditAction, AuditOutcome, User
from app.schemas.auth import LoginRequest, SessionInfo
from app.schemas.common import OkResponse

logger = get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=SessionInfo)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    container: ContainerDep,
    session: SessionDep,
    audit: AuditDep,
    client_ip: ClientIp,
) -> SessionInfo:
    """Authenticate and start a signed session."""
    settings = container.settings
    email = payload.email.strip().lower()
    limiter_key = f"{client_ip}:{email}"

    if not container.login_limiter.allow(limiter_key):
        raise RateLimitedError(retry_after=container.login_limiter.retry_after(limiter_key))

    user = await session.scalar(select(User).where(User.email == email))
    password = payload.password.get_secret_value()

    if user is None or not user.is_active:
        # Equalise timing so the response does not reveal whether the account exists.
        dummy_verify_safely()
        await audit.record_now(
            AuditAction.LOGIN_FAILED,
            outcome=AuditOutcome.FAILURE,
            actor_label=email,
            client_ip=client_ip,
            message="unknown or inactive account",
        )
        raise InvalidCredentialsError

    if not verify_password(password, user.password_hash):
        await audit.record_now(
            AuditAction.LOGIN_FAILED,
            outcome=AuditOutcome.FAILURE,
            user_id=user.id,
            actor_label=email,
            client_ip=client_ip,
            message="bad password",
        )
        raise InvalidCredentialsError

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)

    container.login_limiter.reset(limiter_key)
    csrf_token = generate_csrf_token()
    token = container.session_codec.encode(
        SessionPayload(user_id=user.id, csrf_token=csrf_token)
    )
    _set_session_cookie(response, container, token)
    request.state.csrf_token = csrf_token

    await audit.record(
        AuditAction.LOGIN_SUCCEEDED,
        user_id=user.id,
        actor_label=email,
        client_ip=client_ip,
    )
    return SessionInfo(
        email=user.email,
        csrf_token=csrf_token,
        campaign_name_prefix=settings.campaign_name_prefix,
    )


@router.post("/logout", response_model=OkResponse, status_code=status.HTTP_200_OK)
async def logout(
    response: Response,
    container: ContainerDep,
    user: CurrentUser,
    audit: AuditDep,
    client_ip: ClientIp,
) -> OkResponse:
    """Clear the session cookie."""
    response.delete_cookie(
        container.settings.session_cookie_name,
        path="/",
        httponly=True,
        secure=container.settings.cookie_secure,
        samesite="strict",
    )
    await audit.record(
        AuditAction.LOGOUT, user_id=user.id, actor_label=user.email, client_ip=client_ip
    )
    return OkResponse()


@router.get("/session", response_model=SessionInfo)
async def current_session(
    request: Request, container: ContainerDep, user: CurrentUser
) -> SessionInfo:
    """Return the active session, used by the UI on page load."""
    return SessionInfo(
        email=user.email,
        csrf_token=str(request.state.csrf_token),
        campaign_name_prefix=container.settings.campaign_name_prefix,
    )


def _set_session_cookie(response: Response, container: ContainerDep, token: str) -> None:
    settings = container.settings
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/",
    )


def dummy_verify_safely() -> None:
    """Burn CPU to mask timing; the helper must never fail the request."""
    with suppress(Exception):
        dummy_verify()
