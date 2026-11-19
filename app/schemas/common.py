"""Shared response models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    """Base DTO: rejects unknown input fields."""

    model_config = ConfigDict(extra="forbid")


class ErrorResponse(BaseModel):
    """Uniform error envelope. Contains no internal details."""

    code: str = Field(description="Machine-readable error code")
    message: str = Field(description="Human-readable, safe to display")


class OkResponse(BaseModel):
    ok: bool = True
