"""Authentication DTOs."""

from __future__ import annotations

from typing import Annotated

from pydantic import EmailStr, Field, SecretStr

from app.schemas.common import ApiModel


class LoginRequest(ApiModel):
    email: EmailStr
    password: Annotated[SecretStr, Field(min_length=8, max_length=256)]


class SessionInfo(ApiModel):
    email: str
    csrf_token: str
    campaign_name_prefix: str
