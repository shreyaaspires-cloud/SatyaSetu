"""
WhatsApp webhook router (Wave 8).

Handles POST /webhook/twilio — the Twilio WhatsApp inbound message endpoint.

Security:
  - Optional Twilio signature validation (settings.require_twilio_signature)
  - Per-sender rate limiting (in-memory, configurable)
  - PII redacted from all log lines (from_number hashed before logging)
  - Request IDs attached to all log statements for traceability
"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from collections import defaultdict
from threading import Lock
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import PlainTextResponse

from app.contracts.models import WebhookPayload
from app.core.config import settings
from app.core.logging import get_logger
from app.core.twiml import twiml_message as _twiml_message_fn
from app.features.ingestion.service import ingest
from app.pipeline import run_pipeline

logger = get_logger(__name__)

router = APIRouter(prefix="/webhook", tags=["webhook"])

# ── In-memory rate limiter (per hashed sender, per minute) ─────────────────────

_rate_store: Dict[str, list] = defaultdict(list)
_rate_lock = Lock()


def _hash_sender(phone: str) -> str:
    """SHA-256 hash of the raw phone number — never log raw digits."""
    return hashlib.sha256(phone.encode()).hexdigest()[:12]


def _is_rate_limited(sender_hash: str) -> bool:
    """Return True if this sender has exceeded rate_limit_per_minute."""
    now = time.monotonic()
    window = 60.0
    with _rate_lock:
        timestamps = _rate_store[sender_hash]
        # Purge entries older than 1 minute
        _rate_store[sender_hash] = [ts for ts in timestamps if now - ts < window]
        if len(_rate_store[sender_hash]) >= settings.rate_limit_per_minute:
            return True
        _rate_store[sender_hash].append(now)
        return False


# ── Twilio signature dependency ────────────────────────────────────────────────

async def _validate_twilio_signature(request: Request) -> None:
    """
    FastAPI dependency — validates Twilio X-Twilio-Signature header.
    Only enforced when settings.require_twilio_signature is True.
    """
    if not settings.require_twilio_signature:
        return

    from app.core.security import twilio_media_auth

    signature = request.headers.get("X-Twilio-Signature", "")
    form_data: Dict[str, Any] = dict(await request.form())
    url = str(request.url)

    if not twilio_media_auth(signature=signature, url=url, params=form_data):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid Twilio signature",
        )


# ── Webhook handler ────────────────────────────────────────────────────────────

@router.post(
    "/twilio",
    response_class=PlainTextResponse,
    dependencies=[Depends(_validate_twilio_signature)],
    summary="Twilio WhatsApp inbound webhook",
)
async def twilio_webhook(
    request: Request,
) -> PlainTextResponse:
    """
    Receive inbound WhatsApp message from Twilio, run SatyaSetu pipeline,
    and return a TwiML response that sends the reply back to the user.

    Returns HTTP 200 with TwiML <Response><Message>...</Message></Response>.
    Returns HTTP 429 if rate limit exceeded.
    Returns HTTP 500 with a safe error TwiML on unhandled exceptions.
    """
    request_id = str(uuid.uuid4())[:8]

    # Parse form data (Twilio sends application/x-www-form-urlencoded)
    try:
        form_data = dict(await request.form())
        payload = WebhookPayload(**form_data)
    except Exception as exc:
        logger.warning("[%s] Malformed webhook payload: %s", request_id, type(exc).__name__)
        return _twiml_error("Could not parse your message. Please try again.")

    sender_hash = _hash_sender(payload.From)
    logger.info(
        "[%s] Inbound WhatsApp message sender=%s… body_len=%d media=%d",
        request_id,
        sender_hash,
        len(payload.Body),
        payload.NumMedia,
    )

    # ── Rate limiting ──────────────────────────────────────────────────────────
    if _is_rate_limited(sender_hash):
        logger.warning("[%s] Rate limit exceeded for sender=%s…", request_id, sender_hash)
        return PlainTextResponse(
            content=_twiml_message(
                "⏳ You've sent too many messages. Please wait a minute and try again."
            ),
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            media_type="application/xml",
        )

    # ── Ingestion ──────────────────────────────────────────────────────────────
    try:
        ingested = ingest(
            body=payload.Body,
            from_number=payload.From,
            media_url=payload.MediaUrl0,
            media_content_type=payload.MediaContentType0,
            ocr_reader=getattr(request.app.state, "ocr_reader", None),
            whisper_model=getattr(request.app.state, "whisper_model", None),
        )
    except Exception as exc:
        logger.error("[%s] Ingestion error: %s", request_id, exc, exc_info=True)
        return _twiml_error("Could not process your message. Please try again.")

    # ── Pipeline ───────────────────────────────────────────────────────────────
    try:
        response = run_pipeline(ingested)
        reply_text = response.formatted_reply or "Sorry, I could not generate a reply."
    except Exception as exc:
        logger.error("[%s] Pipeline error: %s", request_id, exc, exc_info=True)
        return _twiml_error("Something went wrong while fact-checking. Please try again.")

    logger.info(
        "[%s] Pipeline complete verdict=%s total_ms=%.0f",
        request_id,
        response.overall_verdict,
        response.timings_ms.get("total_ms", 0),
    )

    return PlainTextResponse(
        content=_twiml_message(reply_text),
        status_code=200,
        media_type="application/xml",
    )


# ── TwiML helpers ──────────────────────────────────────────────────────────────

def _twiml_message(body: str) -> str:
    """Delegate to app.core.twiml for testability."""
    return _twiml_message_fn(body)


def _twiml_error(message: str) -> PlainTextResponse:
    """Return a safe TwiML error response."""
    return PlainTextResponse(
        content=_twiml_message(f"⚠️ {message}"),
        status_code=200,  # Twilio requires 200 even on errors to avoid retry storms
        media_type="application/xml",
    )
