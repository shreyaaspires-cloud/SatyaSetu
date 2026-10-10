"""
app_main.py
───────────
FastAPI application entry point for SatyaSetu (refactored — Wave 8).

Responsibilities:
  - Define FastAPI app with lifespan() for model pre-loading
  - Mount CORS, global error handler
  - Register /health and /webhook/twilio routers
  - Run via: uvicorn app_main:app --host 0.0.0.0 --port 8000 --reload

Architecture: docs/ARCHITECTURE.md
"""

from __future__ import annotations

import sys
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from threading import Lock
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.logging import configure_logging, get_logger

# ── Logging setup (must be first) ─────────────────────────────────────────────
configure_logging(level=settings.log_level)
logger = get_logger(__name__)


# ── Lifespan: model pre-loading ───────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    STARTUP: Pre-load heavy ML models once to eliminate per-request cold starts.
    SHUTDOWN: Python GC handles cleanup; no explicit teardown needed.
    """
    logger.info("=" * 60)
    logger.info("SatyaSetu backend starting up…")
    logger.info("Environment: %s | Port: %s", settings.env, settings.port)
    logger.info("=" * 60)

    # OCR (EasyOCR) — non-fatal on load failure
    try:
        from app.features.ingestion.ocr import load_ocr_reader
        app.state.ocr_reader = load_ocr_reader()
        logger.info("[OK] EasyOCR reader loaded")
    except Exception as exc:
        logger.error("[ERROR] EasyOCR failed to load: %s", exc)
        app.state.ocr_reader = None

    # ASR (Whisper) — non-fatal on load failure
    try:
        from app.features.ingestion.asr import load_whisper_model
        app.state.whisper_model = load_whisper_model()
        logger.info("[OK] Whisper model '%s' loaded", settings.whisper_model_size)
    except Exception as exc:
        logger.error("[ERROR] Whisper failed to load: %s", exc)
        app.state.whisper_model = None

    logger.info("=" * 60)
    logger.info("SatyaSetu startup complete. Accepting requests.")
    logger.info("  GET  /health           — liveness probe")
    logger.info("  POST /webhook/twilio   — WhatsApp inbound")
    logger.info("  GET  /docs             — Swagger UI")
    logger.info("=" * 60)

    yield  # ── Application runs here ──────────────────────────────────────────

    logger.info("SatyaSetu backend shutting down…")


# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="SatyaSetu — WhatsApp Fact Checker",
    description=(
        "Multilingual AI-powered fact-checking via WhatsApp. "
        "Hack on Track — FCRIT Vashi 2026."
    ),
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)


# ── Middleware ─────────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# ── IP-based Rate Limiter (OWASP API4:2023) ──────────────────────────────────
_ip_rate_store: dict[str, list[float]] = defaultdict(list)
_ip_rate_lock = Lock()
IP_RATE_LIMIT_PER_MINUTE = 60


@app.middleware("http")
async def ip_rate_limiting_middleware(request: Request, call_next):
    """
    Per-IP sliding-window rate limiter on all public endpoints.
    Returns HTTP 429 Too Many Requests with Retry-After header.
    """
    client_ip = request.client.host if request.client else "unknown"
    path = request.url.path

    # Bypass internal docs and health checks from aggressive IP throttling
    if not (path.startswith("/docs") or path.startswith("/redoc") or path == "/openapi.json"):
        now = time.monotonic()
        with _ip_rate_lock:
            timestamps = _ip_rate_store[client_ip]
            _ip_rate_store[client_ip] = [ts for ts in timestamps if now - ts < 60.0]
            if len(_ip_rate_store[client_ip]) >= IP_RATE_LIMIT_PER_MINUTE:
                return JSONResponse(
                    status_code=429,
                    content={
                        "success": False,
                        "error": "Too many requests from this IP address. Please wait before retrying.",
                        "code": "RATE_LIMIT_EXCEEDED",
                    },
                    headers={"Retry-After": "60"},
                )
            _ip_rate_store[client_ip].append(now)

    return await call_next(request)


# ── Global error handler ───────────────────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all: returns safe JSON without stack trace."""
    logger.error(
        "Unhandled exception %s %s: %s",
        request.method,
        request.url.path,
        type(exc).__name__,
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": "Internal server error",
            "code": "INTERNAL_ERROR",
        },
    )


# ── Static files ──────────────────────────────────────────────────────────────
from pathlib import Path
from fastapi.staticfiles import StaticFiles

static_path = Path(__file__).resolve().parent / "static"
if static_path.exists():
    app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

# ── Router registration ───────────────────────────────────────────────────────

from app.routers.check import router as check_router      # noqa: E402
from app.routers.health import router as health_router    # noqa: E402
from app.routers.webhook import router as webhook_router  # noqa: E402

app.include_router(health_router)
app.include_router(webhook_router)
app.include_router(check_router)


# ── Dev server entrypoint ─────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app_main:app",
        host="0.0.0.0",
        port=settings.port,
        reload=settings.env == "development",
        log_level="info",
    )
