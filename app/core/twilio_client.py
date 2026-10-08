"""
Twilio REST API client helper.
Sends outbound WhatsApp / SMS messages synchronously or in a background executor.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


def send_twilio_message(to_number: str, body: str) -> bool:
    """
    Send an outbound message via Twilio REST API.
    Returns True on success, False if credentials are missing or call fails.
    Never raises uncaught exceptions to caller.
    """
    if not (settings.account_sid and settings.auth_token):
        logger.debug("Twilio credentials not configured; skipping outbound REST message.")
        return False

    if "mock" in settings.account_sid.lower() or "test" in settings.account_sid.lower():
        logger.debug("Mock Twilio credentials detected; skipping outbound network call.")
        return True

    try:
        from twilio.rest import Client
        client = Client(settings.account_sid, settings.auth_token)
        from_num = settings.sender_number

        # Format WhatsApp prefix correctly if to_number uses it
        if to_number.startswith("whatsapp:") and not from_num.startswith("whatsapp:"):
            from_num = f"whatsapp:{from_num}"

        msg = client.messages.create(
            body=body,
            from_=from_num,
            to=to_number,
        )
        logger.info("Sent Twilio message to %s (SID: %s)", to_number, getattr(msg, "sid", "unknown"))
        return True
    except Exception as exc:
        logger.error("Failed to send Twilio message to %s: %s", to_number, exc)
        return False
