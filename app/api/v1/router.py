"""API v1 router."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import auth, campaigns, catalog

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(catalog.router)
api_router.include_router(campaigns.router)
