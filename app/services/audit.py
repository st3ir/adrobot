"""Append-only audit trail for every mutating action."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import AuditAction, AuditLogEntry, AuditOutcome

logger = get_logger(__name__)

#: Keys that must never reach the audit log, even by accident.
_FORBIDDEN_CONTEXT_KEYS = frozenset(
    {"password", "api_key", "token", "secret", "authorization", "cookie"}
)


class AuditService:
    """Writes audit entries. Never raises into the caller's happy path."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        action: AuditAction,
        *,
        outcome: AuditOutcome = AuditOutcome.SUCCESS,
        user_id: int | None = None,
        actor_label: str | None = None,
        target_type: str | None = None,
        target_id: str | int | None = None,
        context: dict[str, Any] | None = None,
        message: str | None = None,
        client_ip: str | None = None,
    ) -> None:
        entry = AuditLogEntry(
            action=action,
            outcome=outcome,
            user_id=user_id,
            actor_label=actor_label,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            context=sanitize_context(context),
            message=message[:1000] if message else None,
            client_ip=client_ip,
        )
        self._session.add(entry)
        await self._session.flush()

    async def record_now(self, action: AuditAction, **fields: Any) -> None:
        """Record and commit immediately.

        Used for entries that must survive the exception that follows, such
        as a failed login: the request transaction is rolled back, so the
        entry would otherwise disappear with it.
        """
        await self.record(action, **fields)
        await self._session.commit()


def sanitize_context(context: dict[str, Any] | None) -> dict[str, Any] | None:
    """Drop secret-looking keys and clamp value sizes before persisting."""
    if not context:
        return None
    clean: dict[str, Any] = {}
    for key, value in context.items():
        if any(marker in key.lower() for marker in _FORBIDDEN_CONTEXT_KEYS):
            continue
        if isinstance(value, str):
            clean[key] = value[:500]
        elif isinstance(value, (int, float, bool)) or value is None:
            clean[key] = value
        elif isinstance(value, (list, tuple)):
            clean[key] = [str(item)[:120] for item in list(value)[:50]]
        else:
            clean[key] = str(value)[:500]
    return clean or None
