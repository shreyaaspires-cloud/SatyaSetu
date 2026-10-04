"""
routers/webhook.py
───────────────────
POST /webhook/twilio — Twilio WhatsApp webhook entry point.

Rules enforced:
  - Returns TwiML acknowledgement ("🔍 Got it! Checking this for you... ⏳") in < 2 seconds
  - Full pipeline runs in BackgroundTasks — never blocks the webhook response
  - Twilio signature validated via dependency (see middleware/twilio_validator.py)
  - File-too-large reply sent as Twilio REST call (not in the initial TwiML)
  - Phone number hashed in run_preprocessing — raw number never leaves this function
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from fastapi.responses import Response

from lib.config import settings
from middleware.twilio_validator import validate_twilio_signature
from pipelines.verify_pipeline import run_preprocessing

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook", tags=["webhook"])

# ── Twilio TwiML reply helper ─────────────────────────────────────────────────

def _twiml_response(message: str) -> Response:
    """Build a minimal TwiML XML response that sends one WhatsApp message."""
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f"<Message>{message}</Message>"
        "</Response>"
    )
    return Response(content=xml, media_type="application/xml")


# ── Background pipeline task ──────────────────────────────────────────────────

async def _run_pipeline_background(
    body: str,
    media_url: str | None,
    media_content_type: str | None,
    from_number: str,
) -> None:
    """
    Run the full Member 1 preprocessing pipeline in the background.
    After extraction, passes result to Member 2 (Shreya's pipeline).

    This function must NEVER raise — any exception is caught and logged.
    """
    try:
        result = run_preprocessing(
            body=body,
            media_url=media_url,
            media_content_type=media_content_type,
            from_number=from_number,
        )

        logger.info(
            "Preprocessing done: input_type='%s', raw_text_len=%d",
            result["input_type"],
            len(result["raw_text"]),
        )

        # ── Handoff to Member 2 (Shreya) ──────────────────────────────────────
        # Uncomment when Shreya's module is ready:
        # from nlp.lang_detect import member2_pipeline
        # member2_output = await member2_pipeline(result["raw_text"])
        # ...then send final verdict via twilio_service

        # ── For now: send acknowledgement of extraction only (during development) ─
        # In production this block is replaced by member2_pipeline call above.
        if not result["raw_text"]:
            _send_twilio_message(
                to=from_number,
                body=(
                    "⚠️ I couldn't extract readable text from your message. "
                    "Please try sending as plain text."
                ),
            )

    except Exception as exc:
        logger.error(
            "Background pipeline task failed unexpectedly: %s", exc, exc_info=True
        )
        # Try to notify the user something went wrong
        try:
            _send_twilio_message(
                to=from_number,
                body="⚠️ Something went wrong processing your message. Please try again.",
            )
        except Exception:
            pass  # Best-effort — don't crash the error handler


def _send_twilio_message(to: str, body: str) -> None:
    """
    Send a WhatsApp message via Twilio REST API.
    Used for background task replies (after the initial TwiML acknowledgement).
    """
    from twilio.rest import Client

    client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
    try:
        client.messages.create(
            body=body,
            from_=settings.twilio_whatsapp_number,
            to=to,
        )
    except Exception as exc:
        logger.error("Failed to send Twilio message to %s: %s", to[:5] + "***", exc)


# ── Webhook endpoint ──────────────────────────────────────────────────────────

@router.post(
    "/twilio",
    response_class=Response,
    summary="Twilio WhatsApp webhook",
    description="Receives all WhatsApp messages forwarded by Twilio. Replies instantly with acknowledgement, processes in background.",
)
async def twilio_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    _: Annotated[None, Depends(validate_twilio_signature)],
    # ── Twilio form fields ────────────────────────────────────────────────────
    Body: Annotated[str, Form(alias="Body")] = "",
    From: Annotated[str, Form(alias="From")] = "",
    MediaUrl0: Annotated[str | None, Form(alias="MediaUrl0")] = None,
    MediaContentType0: Annotated[str | None, Form(alias="MediaContentType0")] = None,
    NumMedia: Annotated[str, Form(alias="NumMedia")] = "0",
) -> Response:
    """
    POST /webhook/twilio

    Steps:
        1. Validate Twilio signature (via Depends — raises 403 if invalid)
        2. Return TwiML acknowledgement immediately (< 2s target)
        3. Queue full pipeline in BackgroundTasks
    """
    logger.info(
        "Twilio webhook received: NumMedia=%s, MediaContentType0=%s",
        NumMedia,
        MediaContentType0,
    )

    # Queue background processing — MUST be added before returning the response
    background_tasks.add_task(
        _run_pipeline_background,
        body=Body,
        media_url=MediaUrl0,
        media_content_type=MediaContentType0,
        from_number=From,
    )

    # Return instant TwiML acknowledgement — Twilio requires response within 5s
    return _twiml_response("🔍 Got it! Checking this for you... ⏳")
