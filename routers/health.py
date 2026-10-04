"""
routers/health.py
──────────────────
GET /health — health check endpoint for UptimeRobot and Render.
Returns current timestamp, version, and model load status.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])

APP_VERSION = "1.0.0"


@router.get(
    "/health",
    summary="Health check",
    description="Returns 200 OK with service status. Used by UptimeRobot to keep Render alive.",
)
async def health_check(request: Request) -> JSONResponse:
    """
    GET /health

    Returns:
        {
            "status": "ok",
            "version": "1.0.0",
            "timestamp": "2024-01-01T00:00:00+00:00",
            "models": {
                "ocr": true | false,
                "whisper": true | false
            }
        }
    """
    # Check if models are loaded (stored in app.state by lifespan)
    ocr_loaded = getattr(request.app.state, "ocr_reader", None) is not None
    whisper_loaded = getattr(request.app.state, "whisper_model", None) is not None

    return JSONResponse(
        status_code=200,
        content={
            "status": "ok",
            "version": APP_VERSION,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "models": {
                "ocr": ocr_loaded,
                "whisper": whisper_loaded,
            },
        },
    )
