"""
app/routers/health.py
──────────────────────
Health check router.

GET /health          — lightweight liveness probe.
GET /health/detailed — model status, feature flags (no secrets exposed).

Design notes
─────────────
/health is intended for load balancer / Kubernetes liveness probes and must be
extremely fast — it performs no I/O and returns in < 1 ms.

/health/detailed reads model_status from app.state (populated during lifespan
startup) and exposes boolean feature flags without leaking API key values.
This endpoint is safe to call from monitoring dashboards; it deliberately omits
all secret material (keys are only represented as boolean presence checks).

Security: neither endpoint requires authentication.  If the service is running
behind an authenticated API gateway, these endpoints should be allowlisted.
"""

from __future__ import annotations

import time
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.core.config import settings

router = APIRouter(tags=["health"])

# Captured at module import time so uptime_seconds is always accurate.
_START_TIME = time.time()


class HealthResponse(BaseModel):
    """Minimal liveness payload returned by GET /health."""
    status: str
    app_name: str
    env: str
    version: str
    uptime_seconds: float = Field(default=0.0)


class DetailedHealthResponse(HealthResponse):
    """Extended diagnostics payload returned by GET /health/detailed."""
    environment: dict[str, str] = Field(default_factory=dict)
    # Features are represented as booleans (key present = True) to avoid
    # leaking secret values in the response body.
    features_enabled: dict[str, bool] = Field(default_factory=dict)
    # model_status comes from app.state.model_status set during lifespan startup.
    model_status: dict[str, str] = Field(default_factory=dict)


@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
async def health_check() -> HealthResponse:
    """
    Return 200 OK with basic app metadata and uptime.

    Designed for low-latency polling: no I/O, no DB queries.
    Suitable for Kubernetes liveness probes and load balancer health checks.
    """
    return HealthResponse(
        status="ok",
        app_name=settings.app_name,
        env=settings.env,
        version="2.0.0",
        uptime_seconds=round(time.time() - _START_TIME, 2),
    )


@router.get("/health/detailed", response_model=DetailedHealthResponse, summary="Diagnostics probe")
async def health_check_detailed(request: Request) -> DetailedHealthResponse:
    """
    Return 200 OK with model readiness status, feature flags (no secrets exposed).

    model_status is populated by the lifespan hook; if the application is still
    warming up, an empty dict is returned rather than raising a 500.
    """
    # Safely access model_status from app.state; default to empty dict if absent.
    model_status: dict[str, str] = getattr(request.app.state, "model_status", {})
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
            # Indicates whether HMAC-SHA256 signature validation is enforced on
            # incoming Twilio webhooks.
            "twilio_signature_required": settings.require_twilio_signature,
        },
        model_status=model_status,
    )
