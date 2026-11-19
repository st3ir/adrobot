"""Password hashing, session tokens and CSRF primitives.

Deliberately dependency-light: Argon2id for passwords, itsdangerous for
tamper-proof session cookies, ``secrets.compare_digest`` for CSRF.
"""

from __future__ import annotations

import hmac
import secrets
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

# OWASP-recommended Argon2id parameters (second recommended option).
_hasher = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=4, hash_len=32)

_SESSION_SALT = "adrobot.session.v1"


def hash_password(password: str) -> str:
    """Return an Argon2id hash for ``password``."""
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify ``password`` against ``password_hash`` in constant time."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError, ValueError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """True when the stored hash uses outdated Argon2 parameters."""
    try:
        return _hasher.check_needs_rehash(password_hash)
    except (InvalidHashError, ValueError):
        return True


def dummy_verify() -> None:
    """Burn a comparable amount of CPU to mask user-enumeration timing."""
    _hasher.verify(
        "$argon2id$v=19$m=65536,t=3,p=4$c29tZXNhbHRzb21lc2FsdA$"
        "0E4FqN7u3L3Gp5bqkCjzqKkqLwPPvNq9Bqk0SIbjqyE",
        "not-the-password",
    )


@dataclass(frozen=True, slots=True)
class SessionPayload:
    """Data stored inside the signed session cookie."""

    user_id: int
    csrf_token: str


class SessionTokenCodec:
    """Encode/decode signed, expiring session cookies."""

    def __init__(self, secret_key: str, *, max_age_seconds: int) -> None:
        self._serializer = URLSafeTimedSerializer(secret_key, salt=_SESSION_SALT)
        self._max_age = max_age_seconds

    def encode(self, payload: SessionPayload) -> str:
        return self._serializer.dumps({"uid": payload.user_id, "csrf": payload.csrf_token})

    def decode(self, token: str) -> SessionPayload | None:
        """Return the payload, or ``None`` when the token is invalid/expired."""
        try:
            raw = self._serializer.loads(token, max_age=self._max_age)
        except (BadSignature, SignatureExpired):
            return None
        if not isinstance(raw, dict):
            return None
        user_id, csrf = raw.get("uid"), raw.get("csrf")
        if not isinstance(user_id, int) or not isinstance(csrf, str):
            return None
        return SessionPayload(user_id=user_id, csrf_token=csrf)


def generate_csrf_token() -> str:
    """Return a fresh, high-entropy CSRF token."""
    return secrets.token_urlsafe(32)


def tokens_match(left: str, right: str) -> bool:
    """Constant-time comparison for CSRF tokens."""
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))
