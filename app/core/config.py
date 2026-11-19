"""Application settings.

All configuration comes from environment variables (or a local ``.env`` file).
Secrets are wrapped in :class:`~pydantic.SecretStr` so they never leak into
logs, tracebacks or ``repr()`` output.
"""

from __future__ import annotations

import secrets
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "staging", "production"]

# Keitaro campaign names must start with a team-wide prefix (``test_<surname>_``).
CAMPAIGN_PREFIX_PATTERN = r"^[a-z0-9_]{1,40}$"


class Settings(BaseSettings):
    """Typed, immutable application configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
        case_sensitive=False,
    )

    # ---- General ---------------------------------------------------------
    app_name: str = "Adrobot"
    environment: Environment = "local"
    debug: bool = False

    # ---- Persistence -----------------------------------------------------
    database_url: str = "sqlite+aiosqlite:///./adrobot.db"

    # ---- Keitaro ---------------------------------------------------------
    keitaro_base_url: str = "https://tlgk.host"
    keitaro_api_key: SecretStr = SecretStr("")
    keitaro_timeout_seconds: Annotated[float, Field(gt=0, le=120)] = 20.0
    keitaro_max_retries: Annotated[int, Field(ge=0, le=5)] = 2
    keitaro_cache_ttl_seconds: Annotated[int, Field(ge=0, le=3600)] = 60

    # ---- Campaign defaults ----------------------------------------------
    campaign_name_prefix: str = "test_"
    geo_redirect_url: str = "https://google.com"
    # Preferred names for the campaign domain/group/source. When a name is not
    # configured (or not found in Keitaro) the first available entity is used.
    keitaro_default_domain: str | None = None
    keitaro_default_group: str | None = None
    keitaro_default_source: str | None = None

    # ---- Auth / sessions -------------------------------------------------
    session_secret: SecretStr = SecretStr("")
    session_cookie_name: str = "adrobot_session"
    session_ttl_seconds: Annotated[int, Field(ge=300, le=604_800)] = 28_800
    cookie_secure: bool = True
    csrf_cookie_name: str = "adrobot_csrf"

    # Optional bootstrap user, created on startup when both values are set.
    bootstrap_user_email: str | None = None
    bootstrap_user_password: SecretStr | None = None

    # ---- Hardening -------------------------------------------------------
    # Comma-separated list; empty means same-origin only (the default, since
    # the UI is served by this app).
    cors_origins: str = ""
    login_rate_limit_attempts: Annotated[int, Field(ge=1, le=100)] = 5
    login_rate_limit_window_seconds: Annotated[int, Field(ge=10, le=3600)] = 300
    api_rate_limit_requests: Annotated[int, Field(ge=1, le=10_000)] = 120
    api_rate_limit_window_seconds: Annotated[int, Field(ge=1, le=3600)] = 60
    max_request_body_bytes: Annotated[int, Field(ge=1024, le=10 * 1024 * 1024)] = 64 * 1024

    @field_validator("keitaro_base_url", "geo_redirect_url")
    @classmethod
    def _require_https_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        if not normalized.startswith(("https://", "http://")):
            msg = "URL must start with http:// or https://"
            raise ValueError(msg)
        return normalized

    @field_validator("campaign_name_prefix")
    @classmethod
    def _validate_prefix(cls, value: str) -> str:
        import re

        normalized = value.strip().lower()
        if not re.fullmatch(CAMPAIGN_PREFIX_PATTERN, normalized):
            msg = "campaign_name_prefix must match [a-z0-9_]{1,40}"
            raise ValueError(msg)
        return normalized

    @model_validator(mode="after")
    def _validate_production_safety(self) -> Settings:
        if self.environment == "production":
            if self.debug:
                msg = "debug must be disabled in production"
                raise ValueError(msg)
            if not self.keitaro_api_key.get_secret_value():
                msg = "KEITARO_API_KEY is required in production"
                raise ValueError(msg)
            if len(self.session_secret.get_secret_value()) < 32:
                msg = "SESSION_SECRET must be at least 32 characters in production"
                raise ValueError(msg)
            if not self.cookie_secure:
                msg = "cookie_secure must stay enabled in production"
                raise ValueError(msg)
        return self

    @property
    def keitaro_api_root(self) -> str:
        """Base URL of the Keitaro Admin API v1."""
        return f"{self.keitaro_base_url}/admin_api/v1"

    @property
    def cors_origin_list(self) -> list[str]:
        """Allowed CORS origins, parsed from the comma-separated setting."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def effective_session_secret(self) -> str:
        """Session secret, falling back to an ephemeral one outside production.

        An ephemeral secret invalidates sessions on restart, which is a safe
        default for local development but never silently used in production
        (see :meth:`_validate_production_safety`).
        """
        configured = self.session_secret.get_secret_value()
        return configured or secrets.token_urlsafe(48)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached application settings instance."""
    return Settings()
