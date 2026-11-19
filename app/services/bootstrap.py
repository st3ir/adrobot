"""Startup helpers: optional bootstrap operator account."""

from __future__ import annotations

from sqlalchemy import select

from app.core.container import Container
from app.core.logging import get_logger
from app.core.security import hash_password
from app.db.models import User

logger = get_logger(__name__)


async def ensure_bootstrap_user(container: Container) -> None:
    """Create the account from ``BOOTSTRAP_USER_*`` when it does not exist.

    Nothing happens when the variables are unset, and an existing account is
    never modified — the password is not reset on restart.
    """
    settings = container.settings
    email = (settings.bootstrap_user_email or "").strip().lower()
    password = settings.bootstrap_user_password
    if not email or password is None:
        return

    async with container.session_factory() as session, session.begin():
        existing = await session.scalar(select(User.id).where(User.email == email))
        if existing is not None:
            return
        session.add(
            User(email=email, password_hash=hash_password(password.get_secret_value()))
        )
    logger.info("Created bootstrap user %s", email)
