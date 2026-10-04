"""
middleware/twilio_validator.py
───────────────────────────────
FastAPI dependency that validates Twilio webhook HMAC-SHA1 signatures.

Every POST to /webhook/* MUST pass this check.
Invalid signatures → 403 Forbidden.

Per TRD §3.1: "Every webhook request MUST be validated with Twilio HMAC signature"
"""

from __future__ import annotations

import logging

from fastapi import Depends, HTTPException, Request
from twilio.request_validator import RequestValidator

from lib.config import settings

logger = logging.getLogger(__name__)

# ── Dependency ─────────────────────────────────────────────────────────────────

async def validate_twilio_signature(request: Request) -> None:
    """
    FastAPI dependency — validates the Twilio X-Twilio-Signature header.

    Raises HTTPException(403) if:
        - The signature header is missing
        - The signature does not match the computed HMAC

    Usage in router:
        @router.post("/twilio")
        async def handler(
            _: Annotated[None, Depends(validate_twilio_signature)],
            ...
        ): ...
    """
    # Skip validation in development mode (set ENV=development in .env)
    if settings.env.lower() == "development":
        logger.debug("Twilio signature validation SKIPPED (ENV=development)")
        return

    validator = RequestValidator(settings.twilio_auth_token)

    # Read the raw form body — must be read before FastAPI parses it via Form()
    # body is already consumed by FastAPI, so we re-read it from the cached body
    try:
        form_data = await request.form()
        form_dict = dict(form_data)
    except Exception as exc:
        logger.error("Failed to read form data for Twilio validation: %s", exc)
        raise HTTPException(status_code=400, detail="Invalid form data")

    signature = request.headers.get("X-Twilio-Signature", "")
    if not signature:
        logger.warning("Missing X-Twilio-Signature header — rejecting request")
        raise HTTPException(status_code=403, detail="Missing Twilio signature")

    # Build the full URL as Twilio sees it (including scheme + host)
    url = str(request.url)

    is_valid = validator.validate(url, form_dict, signature)

    if not is_valid:
        logger.warning(
            "Invalid Twilio signature — rejecting request from IP %s",
            request.client.host if request.client else "unknown",
        )
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")

    logger.debug("Twilio signature validated successfully")
