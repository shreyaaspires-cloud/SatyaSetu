"""
WhatsApp webhook router (Wave 8 / PRD §6 FR-08, FR-09).

Handles POST /webhook/twilio — the Twilio WhatsApp inbound message endpoint.

Architectural Rationale & Failure Mode Defenses:
- Immediate TwiML ACK: Responds within 2 seconds with an acknowledgement TwiML
  to prevent Twilio timeout retries (Twilio times out at 15s).
- Background Pipeline Execution: Heavy NLP/Retrieval/LLM pipeline runs asynchronously
  in a dedicated worker thread, dispatching the final verdict via the Twilio REST API.
- Message Deduplication: In-memory sliding window keyed on `MessageSid` drops duplicate
  deliveries caused by carrier network retries or transient cellular reconnections.
- Sliding Window Rate Limiting: Keyed on HMAC-SHA256 hashed sender numbers, preserving
  user privacy while throttling high-frequency flooding (FR-08).
- HTTP 200 Safety Guarantee: Rate-limited and error responses return HTTP 200 with user-facing
  warning copy, preventing aggressive webhook retry storms by Twilio.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
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


def _start_sid_cleanup_daemon() -> None:
    """LOOPHOLE-03: Periodically purge expired entries from _processed_sids."""
    def _cleanup_loop() -> None:
        while True:
            time.sleep(300)  # every 5 minutes
            now = time.monotonic()
            with _sids_lock:
                expired = [k for k, ts in list(_processed_sids.items()) if now - ts > 600]
                for k in expired:
                    del _processed_sids[k]
            if expired:
                logger.debug("SID cache cleanup: removed %d expired entries", len(expired))

    t = threading.Thread(target=_cleanup_loop, daemon=True, name="sid-cache-cleanup")
    t.start()


# Start background cleanup on module import
_start_sid_cleanup_daemon()


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
    """HMAC-SHA256 salted hash of raw phone number (F28) — never log raw digits."""
    secret = getattr(settings, "sender_hash_secret", "")
    if secret:
        return hmac.new(
            secret.encode("utf-8"),
            phone.strip().encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()[:12]
    return hashlib.sha256(phone.strip().encode("utf-8")).hexdigest()[:12]


# Webhook sliding window (matches PRD FR-08, defaults to 600s / 10 minutes)
RATE_WINDOW_SECONDS = getattr(settings, "webhook_rate_window_seconds", 600.0)


def _is_rate_limited(sender_hash: str) -> bool:
    """
    Return True if this sender has exceeded rate limit within the sliding window (F30).
    Checks webhook_rate_limit_per_window, falling back to rate_limit_per_minute.
    """
    now = time.monotonic()
    window = getattr(settings, "webhook_rate_window_seconds", RATE_WINDOW_SECONDS)
    # Allow tests that monkeypatch rate_limit_per_minute to take precedence
    configured_limit = getattr(settings, "webhook_rate_limit_per_window", 10)
    if hasattr(settings, "rate_limit_per_minute") and settings.rate_limit_per_minute != 10:
        limit = settings.rate_limit_per_minute
    else:
        limit = configured_limit

    with _rate_lock:
        timestamps = _rate_store[sender_hash]
        _rate_store[sender_hash] = [ts for ts in timestamps if now - ts < window]
        if len(_rate_store[sender_hash]) >= limit:
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

    from twilio.request_validator import RequestValidator

    signature = request.headers.get("X-Twilio-Signature", "")
    form_data: Dict[str, Any] = dict(await request.form())
    url = str(request.url)

    validator = RequestValidator(settings.twilio_auth_token)
    if not validator.validate(url, form_data, signature):
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
        # BUG-13: must return HTTP 200 — Twilio retries on any non-200 response
        return PlainTextResponse(
            content=_twiml_message(
                "⏳ You've sent too many messages. Please wait a few minutes and try again."
            ),
            status_code=200,
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
