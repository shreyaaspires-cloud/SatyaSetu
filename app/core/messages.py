"""
app/core/messages.py
────────────────────
Centralized bot message strings (ADR-010).

All user-visible text sent by the SatyaSetu bot via Twilio is defined here
so that copy changes never require touching webhook logic, and the demo UI
can fetch them via GET /api/demo/config.

Rules:
- No real personal names or real group names.
- No invented verdicts or fake confidence values.
- All strings are plain WhatsApp-safe text (no HTML, no markdown headers).
"""

from __future__ import annotations

# ── Acknowledgement ───────────────────────────────────────────────────────────

ACK_MESSAGE = (
    "🔍 Checking this for you, one moment…\n"
    "_SatyaSetu Fact-Check Bot_"
)

# ── Rate limit notice ─────────────────────────────────────────────────────────

RATE_LIMIT_MESSAGE = (
    "⚠️ You've sent several messages in a short time.\n"
    "Please wait a moment before sending another claim."
)

# ── Error / fallback (truthful neutral — never invents a verdict) ─────────────

ERROR_MESSAGE = (
    "⚠️ Couldn't check this right now. Please try again in a moment.\n"
    "_SatyaSetu Fact-Check Bot_"
)

# ── Empty / uncheck-worthy claim ─────────────────────────────────────────────

NOT_CHECKWORTHY_MESSAGE = (
    "ℹ️ This message doesn't appear to contain a verifiable claim.\n"
    "Try forwarding a specific news headline, health claim, or viral message."
)

# ── Unsupported media type ────────────────────────────────────────────────────

UNSUPPORTED_MEDIA_MESSAGE = (
    "⚠️ This media type isn't supported yet.\n"
    "Please send text, images, voice notes, or PDF documents."
)

# ── Demo config payload (returned by GET /api/demo/config) ───────────────────

DEMO_CONFIG = {
    "bot_name": "SatyaSetu",
    "bot_phone": "+91 XX XXXX XXXX (simulated)",
    "messages": {
        "ack": ACK_MESSAGE,
        "rate_limit": RATE_LIMIT_MESSAGE,
        "error": ERROR_MESSAGE,
        "not_checkworthy": NOT_CHECKWORTHY_MESSAGE,
        "unsupported_media": UNSUPPORTED_MEDIA_MESSAGE,
    },
    "supported_languages": ["en", "hi", "hi-Latn", "mr", "bn", "ta", "te"],
    "verdict_labels": {
        "SUPPORTED": "Supported",
        "REFUTED": "Refuted",
        "MISLEADING": "Misleading",
        "UNVERIFIABLE": "Unverifiable",
    },
    "evidence_strength_labels": {
        "Strong": "Multiple authoritative sources agree",
        "Moderate": "Some credible sources found",
        "Limited": "Weak or indirect sources only",
        "Insufficient": "No relevant sources found",
    },
    "disclaimer": (
        "Simulated interface for demonstration. "
        "Not affiliated with WhatsApp or Meta."
    ),
}
