"""
Health check router.

GET /health — lightweight liveness probe suitable for Render / Railway / Cloud Run.
Returns service metadata and environment info without exposing secrets.
"""

from __future__ import annotations

import time
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.config import settings

router = APIRouter(tags=["health"])

_START_TIME = time.time()


class HealthResponse(BaseModel):
    status: str
    app_name: str
    env: str
    version: str
    uptime_seconds: float = Field(default=0.0)


class DetailedHealthResponse(HealthResponse):
    environment: dict[str, str] = Field(default_factory=dict)
    features_enabled: dict[str, bool] = Field(default_factory=dict)


@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
async def health_check() -> HealthResponse:
    """Return 200 OK with basic app metadata and uptime."""
    return HealthResponse(
        status="ok",
        app_name=settings.app_name,
        env=settings.env,
        version="2.0.0",
        uptime_seconds=round(time.time() - _START_TIME, 2),
    )


@router.get("/health/detailed", response_model=DetailedHealthResponse, summary="Diagnostics probe")
async def health_check_detailed() -> DetailedHealthResponse:
    """Return 200 OK with diagnostics without exposing secrets."""
    return DetailedHealthResponse(
        status="ok",
        app_name=settings.app_name,
        env=settings.env,
        version="2.0.0",
        uptime_seconds=round(time.time() - _START_TIME, 2),
        environment={
            "python_env": settings.env,
            "log_level": settings.log_level,
        },
        features_enabled={
            "gemini": bool(settings.gemini_api_key),
            "factcheck_api": bool(settings.google_fact_check_api_key),
            "web_search": bool(settings.search_api_key),
            "twilio_signature_required": settings.require_twilio_signature,
        },
    )

