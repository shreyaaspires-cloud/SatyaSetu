"""
app/main.py
───────────
Canonical SatyaSetu application factory.

Usage (canonical):
    uvicorn app.main:app --reload --port 8000

This module contains create_app() which builds and configures the FastAPI
instance with all middleware, routers, and startup hooks. The root main.py
and app_main.py are thin shims that re-export the app object.
"""

from __future__ import annotations

import time
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Lock
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.logging import configure_logging, get_logger

# ── Logging setup (must run before any router imports) ───────────────────────
configure_logging(level=settings.log_level)
logger = get_logger(__name__)


# ── Lifespan: model pre-loading & resource lifecycle ────────────────────────
# Coordinates graceful subsystem initialization, preheats core language & stance
# inference models if enabled, and establishes local SQLite persistence handles.

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Asynchronous lifespan context manager for FastAPI.
    Orchestrates application warm-up and tear-down:
    1. Probes lightweight embedding and stance models.
    2. Initializes SQLite connection pool for local claim verification logs.
    3. Exposes model readiness status dictionary via app.state for health checks.
    """
    STARTUP: Pre-load heavy ML models once to eliminate per-request cold starts.
    Model load failures are non-fatal; status is stored in app.state for /health.
    SHUTDOWN: Python GC handles cleanup; no explicit teardown needed.
    """
    logger.info("=" * 60)
    logger.info("SatyaSetu backend starting up…")
    logger.info("Environment: %s | Port: %s", settings.env, settings.port)
    logger.info("=" * 60)

    model_status: dict[str, str] = {}

    # OCR (EasyOCR) — non-fatal
    try:
        from app.features.ingestion.ocr import load_ocr_reader
        app.state.ocr_reader = load_ocr_reader()
        model_status["ocr"] = "ok"
        logger.info("[OK] EasyOCR reader loaded")
    except Exception as exc:
        logger.error("[ERROR] EasyOCR failed to load: %s", exc)
        app.state.ocr_reader = None
        model_status["ocr"] = f"failed: {type(exc).__name__}"

    # ASR (Whisper) — non-fatal
    try:
        from app.features.ingestion.asr import load_whisper_model
        app.state.whisper_model = load_whisper_model()
        model_status["asr"] = "ok"
        logger.info("[OK] Whisper model '%s' loaded", settings.whisper_model_size)
    except Exception as exc:
        logger.error("[ERROR] Whisper failed to load: %s", exc)
        app.state.whisper_model = None
        model_status["asr"] = f"failed: {type(exc).__name__}"

    # NLI model — non-fatal
    try:
        from app.features.verification.stance import _load_nli_model
        app.state.nli_model = _load_nli_model(settings.nli_model_name)
        model_status["nli"] = "ok"
        logger.info("[OK] NLI model '%s' loaded", settings.nli_model_name)
    except Exception as exc:
        logger.error("[ERROR] NLI model failed to load: %s", exc)
        app.state.nli_model = None
        model_status["nli"] = f"failed: {type(exc).__name__}"

    # fastText LID model — non-fatal
    import os
    try:
        import fasttext  # type: ignore
        from app.features.nlp.language import set_ft_model
        lid_path = "models/lid.176.bin" if os.path.exists("models/lid.176.bin") else "lid.176.bin"
        if os.path.exists(lid_path):
            ft_inst = fasttext.load_model(lid_path)
            app.state.ft_model = ft_inst
            set_ft_model(ft_inst)
            model_status["fasttext_lid"] = "ok"
            logger.info("[OK] fastText LID model loaded from %s", lid_path)
        else:
            logger.warning("[WARN] fastText LID model not found; using heuristic detection")
            app.state.ft_model = None
            model_status["fasttext_lid"] = "not_found"
    except Exception as exc:
        logger.warning("[WARN] fastText not available (%s); using heuristic detection", exc)
        app.state.ft_model = None
        model_status["fasttext_lid"] = f"unavailable: {type(exc).__name__}"

    # Claims SQLite DB — non-fatal
    try:
        from app.db.claims_db import init_db
        init_db()
        logger.info("[OK] Claims SQLite database initialized")
    except Exception as exc:
        logger.warning("[WARN] Failed to initialize claims SQLite database: %s", exc)

    # Store model status for /health/detailed
    app.state.model_status = model_status

    logger.info("=" * 60)
    logger.info("SatyaSetu startup complete. Accepting requests.")
    logger.info("  GET  /health           — liveness probe")
    logger.info("  GET  /health/detailed  — model status")
    logger.info("  POST /webhook/twilio   — WhatsApp inbound")
    logger.info("  GET  /                 — WhatsApp Web demo")
    logger.info("  GET  /docs             — Swagger UI")
    logger.info("=" * 60)

    yield  # ── Application runs here ─────────────────────────────────────────

    logger.info("SatyaSetu backend shutting down…")


# ── Rate limiting state ───────────────────────────────────────────────────────

_ip_rate_store: dict[str, list[float]] = defaultdict(list)
_ip_rate_lock = Lock()

# Exempt paths: never rate-limited (static assets, health checks, API docs)
_RATE_LIMIT_EXEMPT_PREFIXES = (
    "/static",
    "/web",
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
)

# Per-IP: max requests per 60-second sliding window on API paths
IP_RATE_LIMIT_PER_WINDOW = getattr(settings, "ip_rate_limit_per_window", 60)
IP_RATE_LIMIT_PER_MINUTE = IP_RATE_LIMIT_PER_WINDOW
IP_RATE_WINDOW_SECONDS = getattr(settings, "ip_rate_window_seconds", 60)


# ── Application factory ───────────────────────────────────────────────────────

def create_app() -> FastAPI:
    """Build and return the configured FastAPI application."""

    _app = FastAPI(
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

    # ── CORS ─────────────────────────────────────────────────────────────────
    _allowed_origins = list({
        settings.frontend_url,
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
    })

    _app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    # ── IP Rate Limiter Middleware (F21/F22) ─────────────────────────────────
    @_app.middleware("http")
    async def ip_rate_limiting_middleware(request: Request, call_next):
        """
        Per-IP sliding-window rate limiter on non-exempt API endpoints.
        Static assets, health, and docs are never rate-limited.
        Supports X-Forwarded-For for proxy deployments (single trusted hop).
        """
        path = request.url.path

        # Check exempt paths first — zero overhead for static/health
        if any(path.startswith(prefix) for prefix in _RATE_LIMIT_EXEMPT_PREFIXES):
            return await call_next(request)

        # Safely resolve client IP (proxy-aware, single hop only)
        forwarded_for = request.headers.get("X-Forwarded-For", "")
        client_ip = (
            forwarded_for.split(",")[0].strip()
            if forwarded_for
            else (request.client.host if request.client else "unknown")
        )

        now = time.monotonic()
        with _ip_rate_lock:
            timestamps = _ip_rate_store[client_ip]
            _ip_rate_store[client_ip] = [
                ts for ts in timestamps if now - ts < IP_RATE_WINDOW_SECONDS
            ]
            effective_limit = min(IP_RATE_LIMIT_PER_WINDOW, IP_RATE_LIMIT_PER_MINUTE)
            if len(_ip_rate_store[client_ip]) >= effective_limit:
                return JSONResponse(
                    status_code=429,
                    content={
                        "success": False,
                        "error": "Too many requests. Please wait before retrying.",
                        "code": "RATE_LIMIT_EXCEEDED",
                    },
                    headers={"Retry-After": str(IP_RATE_WINDOW_SECONDS)},
                )
            _ip_rate_store[client_ip].append(now)

        return await call_next(request)

    # ── Global error handler ─────────────────────────────────────────────────
    @_app.exception_handler(Exception)
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

    # ── Static files & Web UI ────────────────────────────────────────────────
    root_path = Path(__file__).resolve().parent.parent
    static_path = root_path / "static"
    if static_path.exists():
        _app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

    web_path = root_path / "web"
    if web_path.exists():
        _app.mount("/web", StaticFiles(directory=str(web_path)), name="web")

    # ── Router registration ──────────────────────────────────────────────────
    from app.routers.check import router as check_router      # noqa: E402
    from app.routers.health import router as health_router    # noqa: E402
    from app.routers.webhook import router as webhook_router  # noqa: E402
    from app.routers.admin import router as admin_router      # noqa: E402

    _app.include_router(health_router)
    _app.include_router(webhook_router)
    _app.include_router(check_router)
    _app.include_router(admin_router)

    return _app


# ── Canonical app instance (used by uvicorn app.main:app) ────────────────────
app = create_app()
