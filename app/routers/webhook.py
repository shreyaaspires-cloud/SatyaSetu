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

import asyncio
import hashlib
import logging
import threading
import time
import uuid
from collections import defaultdict
from threading import Lock
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import PlainTextResponse

from app.contracts.models import IngestedMessage, WebhookPayload
from app.core.config import settings
from app.core.logging import get_logger
from app.core.twiml import twiml_message as _twiml_message_fn
from app.core.twilio_client import send_twilio_message
from app.features.ingestion.service import ingest
from app.pipeline import run_pipeline

logger = get_logger(__name__)

router = APIRouter(prefix="/webhook", tags=["webhook"])

# ── In-memory rate limiter (per hashed sender, per minute) ─────────────────────

_rate_store: Dict[str, list] = defaultdict(list)
_rate_lock = Lock()

# ── In-memory deduplication store (per MessageSid, 10 min TTL) ────────────────
_processed_sids: Dict[str, float] = {}
_sids_lock = Lock()


def clear_processed_sids() -> None:
    """Clear deduplication cache."""
    with _sids_lock:
        _processed_sids.clear()


def _is_duplicate_message(sid: str) -> bool:
    """Return True if message with this MessageSid has already been processed within 10 minutes."""
    if not sid:
        return False
    now = time.monotonic()
    window = 600.0  # 10 minutes
    with _sids_lock:
        # Purge expired entries
        for s, ts in list(_processed_sids.items()):
            if now - ts > window:
                del _processed_sids[s]
        if sid in _processed_sids:
            return True
        _processed_sids[sid] = now
        return False


def _hash_sender(phone: str) -> str:
    """SHA-256 hash of the raw phone number — never log raw digits."""
    return hashlib.sha256(phone.encode()).hexdigest()[:12]


def _is_rate_limited(sender_hash: str) -> bool:
    """Return True if this sender has exceeded rate_limit_per_minute."""
    now = time.monotonic()
    window = 600.0
    with _rate_lock:
        timestamps = _rate_store[sender_hash]
        # Purge entries older than 1 minute
        _rate_store[sender_hash] = [ts for ts in timestamps if now - ts < 60.0]
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
    Receive inbound WhatsApp message from Twilio.
    Instantly sends an acknowledgement and offloads verification pipeline to a background task.

    Returns HTTP 200 with immediate TwiML acknowledgement.
    Returns HTTP 429 if rate limit exceeded.
    Returns HTTP 200 if duplicate MessageSid is received (drops duplicate pipeline run).
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
        "[%s] Inbound WhatsApp message sender=%s… body_len=%d media=%d sid=%s",
        request_id,
        sender_hash,
        len(payload.Body),
        payload.NumMedia,
        payload.MessageSid,
    )

    # ── Deduplication ──────────────────────────────────────────────────────────
    if payload.MessageSid and _is_duplicate_message(payload.MessageSid):
        logger.warning("[%s] Duplicate MessageSid=%s received. Dropping duplicate pipeline run.", request_id, payload.MessageSid)
        return PlainTextResponse(
            content=_twiml_message("Your message is already being processed."),
            status_code=200,
            media_type="application/xml",
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

    # ── Step 1: Immediate acknowledgement ─────────────────────────────────────
    ack_message = "Checking this, one moment..."
    threading.Thread(
        target=send_twilio_message,
        args=(payload.From, ack_message),
        daemon=True,
    ).start()

    # ── Step 2: Offload pipeline to non-blocking background task ──────────────
    def _execute_pipeline_and_reply(ingested_msg: IngestedMessage, to_number: str, req_id: str) -> None:
        try:
            response = run_pipeline(ingested_msg)
            reply = response.formatted_reply or "Sorry, I could not generate a reply."
            logger.info(
                "[%s] Background pipeline complete verdict=%s total_ms=%.0f",
                req_id,
                response.overall_verdict,
                response.timings_ms.get("total_ms", 0),
            )
            send_twilio_message(to_number, reply)
        except Exception as exc:
            logger.error("[%s] Background pipeline error: %s", req_id, exc, exc_info=True)
            send_twilio_message(
                to_number,
                "⚠️ Something went wrong while fact-checking. Please try again.",
            )

    threading.Thread(
        target=_execute_pipeline_and_reply,
        args=(ingested, payload.From, request_id),
        daemon=True,
    ).start()

    # Webhook handler returns immediately with TwiML acknowledgement (< 2 seconds)
    return PlainTextResponse(
        content=_twiml_message(ack_message),
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
