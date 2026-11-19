"""Logging setup with secret redaction.

A single :class:`SecretRedactingFilter` is attached to the root logger so that
an accidental ``logger.info(payload)`` can never print the Keitaro API key or a
session cookie, no matter which module emitted it.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from typing import Any

REDACTED = "***REDACTED***"

_HEADER_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)(api[-_]?key\"?\s*[:=]\s*\"?)([^\s\",}]+)"),
    # Consume the whole header value so an auth scheme ("Bearer <token>")
    # cannot leave the token behind.
    re.compile(r"(?i)(authorization\"?\s*[:=]\s*\"?)([^\",}\n]+)"),
    re.compile(r"(?i)(password\"?\s*[:=]\s*\"?)([^\s\",}]+)"),
    re.compile(r"(?i)(token\"?\s*[:=]\s*\"?)([^\s\",}]+)"),
)


class SecretRedactingFilter(logging.Filter):
    """Strip known secret values and secret-looking key/value pairs."""

    def __init__(self, secrets: Iterable[str] = ()) -> None:
        super().__init__()
        self._secrets = tuple(s for s in secrets if s and len(s) >= 8)

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self._scrub(record.getMessage())
        record.args = ()
        return True

    def _scrub(self, message: str) -> str:
        for secret in self._secrets:
            message = message.replace(secret, REDACTED)
        for pattern in _HEADER_PATTERNS:
            message = pattern.sub(lambda m: f"{m.group(1)}{REDACTED}", message)
        return message


def configure_logging(*, level: str = "INFO", secrets: Iterable[str] = ()) -> None:
    """Configure the root logger once, with redaction enabled."""
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-8s %(name)s | %(message)s")
    )
    handler.addFilter(SecretRedactingFilter(secrets))

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level.upper())

    # Uvicorn access logs duplicate our structured logging and may echo query
    # strings; keep them at WARNING.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def safe_extra(**fields: Any) -> dict[str, Any]:
    """Build a log ``extra`` dict with ``None`` values removed."""
    return {key: value for key, value in fields.items() if value is not None}
