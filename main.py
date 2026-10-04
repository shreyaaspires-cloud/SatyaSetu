"""
main.py
────────
FastAPI application entry point for "Is This Forward True?" — FactGuard.

Responsibilities:
  - Define the FastAPI app with lifespan() context manager
  - Load ALL heavy ML models at startup (EasyOCR + Whisper) — once, never per-request
  - Mount CORS, rate-limit stub, and global error handler
  - Register routers: /webhook, /health
  - Run via: uvicorn main:app --host 0.0.0.0 --port 8000 --reload

Architecture: BACKEND_ARCHITECTURE.md §9 (Model Loading Strategy)
TRD reference:  TRD.md §2 (Technology Stack), §3 (Security)
"""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from lib.config import settings

# ── Logging setup ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


# ── Lifespan: model loading ───────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    FastAPI lifespan context manager.

    STARTUP:
        Load EasyOCR reader and Whisper model ONCE.
        Store on app.state so all request handlers share the same instance.
        This prevents cold-start latency on the first real request.

    SHUTDOWN:
        No explicit cleanup needed (models freed by GC on process exit).

    Per TRD §2 and BACKEND_ARCHITECTURE.md §9:
        "Model loading happens at startup in a lifespan() context manager,
         not on first request — cold starts are too slow."
    """
    # ── STARTUP ───────────────────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("FactGuard backend starting up...")
    logger.info("Environment: %s | Port: %s", settings.env, settings.port)
    logger.info("=" * 60)

    # Load EasyOCR reader (en + hi)
    try:
        from services.input.ocr_service import load_ocr_reader
        app.state.ocr_reader = load_ocr_reader()
        logger.info("✅ EasyOCR reader loaded")
    except Exception as exc:
        # OCR failure is non-fatal — screenshots won't work but text/URL will
        logger.error("❌ EasyOCR failed to load: %s", exc, exc_info=True)
        app.state.ocr_reader = None

    # Load Whisper ASR model
    try:
        from services.input.asr_service import load_whisper_model
        app.state.whisper_model = load_whisper_model()
        logger.info("✅ Whisper model '%s' loaded", settings.whisper_model_size)
    except Exception as exc:
        # Whisper failure is non-fatal — voice notes won't work but text/URL will
        logger.error("❌ Whisper failed to load: %s", exc, exc_info=True)
        app.state.whisper_model = None

    logger.info("=" * 60)
    logger.info("FactGuard startup complete. Accepting requests.")
    logger.info("  GET  /health            — health check")
    logger.info("  POST /webhook/twilio    — WhatsApp webhook")
    logger.info("=" * 60)

    yield  # ── Application runs here ──────────────────────────────────────────

    # ── SHUTDOWN ──────────────────────────────────────────────────────────────
    logger.info("FactGuard backend shutting down...")


# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="Is This Forward True? — FactGuard",
    description=(
        "WhatsApp AI fact-checking bot for Ignite 8.0 Hackathon. "
        "Team Appsolutely — Member 1 (Tejas Kute): Ingestion & Preprocessing."
    ),
    version="1.0.0",
    docs_url="/docs",      # Swagger UI (disable in prod: docs_url=None)
    redoc_url="/redoc",
    lifespan=lifespan,
)


# ── Middleware stack ───────────────────────────────────────────────────────────

# 1. CORS — restrict to admin dashboard origin only
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["*"],
)

# NOTE: Rate limiting (per-number Redis) and Twilio signature validation are
# implemented as FastAPI *dependencies* (not ASGI middleware) to keep things
# simple for the hackathon. They are applied at the route level:
#   - /webhook/twilio → Depends(validate_twilio_signature)
# Full middleware stack can be wired once Redis is configured.


# ── Global error handler ──────────────────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Catch-all exception handler — returns JSON error without stack trace.
    Per TRD §3.3: "Log exposure — Never log raw phone numbers, message bodies, or API keys"
    """
    logger.error(
        "Unhandled exception on %s %s: %s",
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
            "message": "Something went wrong. Please try again.",
        },
    )


# ── Router registration ───────────────────────────────────────────────────────

from routers.health import router as health_router      # noqa: E402
from routers.webhook import router as webhook_router    # noqa: E402

app.include_router(health_router)
app.include_router(webhook_router)


# ── Dev server entrypoint ─────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=settings.port,
        reload=settings.env == "development",
        log_level="info",
    )
