"""
TwiML response helpers.

Extracted as a standalone module so unit tests can import these
without triggering the FastAPI dependency chain.
"""

from __future__ import annotations


def twiml_message(body: str) -> str:
    """
    Wrap a text body in minimal TwiML Response/Message XML.
    Escapes XML special characters: & < >
    """
    escaped = (
        body.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f"<Response><Message>{escaped}</Message></Response>"
    )
