"""
WhatsApp reply formatter (Wave 7).

Converts the overall CheckResponse data into a tightly-formatted WhatsApp
message string, then translates it back to the user's source language.

WhatsApp character limit: 4096 chars per message (hard cap respected here).
Max safe reply length we target: 1500 chars (comfortable on mobile screens).
"""

from __future__ import annotations

import logging
from typing import List

from app.contracts.models import CheckResponse, ClaimResult
from app.core.constants import Verdict

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

VERDICT_EMOJI: dict = {
    Verdict.SUPPORTED: "✅",
    Verdict.REFUTED: "❌",
    Verdict.MISLEADING: "⚠️",
    Verdict.UNVERIFIABLE: "❓",
}

VERDICT_LABEL: dict = {
    Verdict.SUPPORTED: "SUPPORTED",
    Verdict.REFUTED: "REFUTED",
    Verdict.MISLEADING: "MISLEADING",
    Verdict.UNVERIFIABLE: "UNVERIFIABLE",
}

MAX_REPLY_LEN = 1400          # Soft cap — trim if exceeded
WHATSAPP_HARD_CAP = 4096      # Hard WhatsApp limit


def _format_single_claim(result: ClaimResult, idx: int, total: int) -> str:
    """Format one ClaimResult as a readable block."""
    emoji = VERDICT_EMOJI.get(result.verdict, "❓")
    label = VERDICT_LABEL.get(result.verdict, str(result.verdict))
    conf_pct = int(result.confidence * 100)

    header = f"*Claim {idx}/{total}:* {result.claim[:120].strip()}"
    verdict_line = f"{emoji} *{label}* ({conf_pct}% confidence)"

    # Pick the single best evidence item as the source cite
    sources: List[str] = []
    if result.evidence:
        top = sorted(result.evidence, key=lambda e: -e.score)
        for ev in top[:2]:
            if ev.url and ev.source_domain:
                sources.append(f"• {ev.source_domain}: {ev.url[:80]}")

    source_block = "\n".join(sources) if sources else "• No source available"

    parts = [header, verdict_line, source_block]
    return "\n".join(parts)


def format_whatsapp_reply(response: CheckResponse) -> str:
    """
    Build a complete WhatsApp reply string from a CheckResponse.

    Layout:
        🔍 *SatyaSetu Fact Check*
        ─────────────────────────
        <per-claim blocks>
        ─────────────────────────
        *Overall:* ✅ SUPPORTED
        <explanation excerpt>
        ─────────────────────────
        _SatyaSetu — AI-powered fact checking_

    Args:
        response: Completed CheckResponse from the pipeline.

    Returns:
        Formatted string ready to send via Twilio WhatsApp API.
    """
    divider = "─" * 25

    header_parts = [
        "🔍 *SatyaSetu Fact Check*",
        divider,
    ]

    claim_blocks: List[str] = []
    total = len(response.claim_results)
    for idx, result in enumerate(response.claim_results, 1):
        claim_blocks.append(_format_single_claim(result, idx, total))

    overall_emoji = VERDICT_EMOJI.get(response.overall_verdict, "❓")
    overall_label = VERDICT_LABEL.get(response.overall_verdict, str(response.overall_verdict))

    # Explanation: trim to ~400 chars for WhatsApp comfort
    explanation_excerpt = response.explanation[:400].strip()
    if len(response.explanation) > 400:
        explanation_excerpt += "…"

    footer_parts = [
        divider,
        f"*Overall:* {overall_emoji} {overall_label}",
        explanation_excerpt,
        divider,
        "_SatyaSetu — AI-powered multilingual fact checking_",
    ]

    sections = (
        header_parts
        + [("\n\n" + divider + "\n").join(claim_blocks)]
        + footer_parts
    )

    reply = "\n".join(sections)

    # Safety trim
    if len(reply) > MAX_REPLY_LEN:
        reply = reply[:MAX_REPLY_LEN - 3] + "…"

    if len(reply) > WHATSAPP_HARD_CAP:
        reply = reply[:WHATSAPP_HARD_CAP - 3] + "…"

    return reply


def translate_reply_back(
    english_reply: str,
    target_lang: str,
) -> str:
    """
    Translate a formatted English reply back to the user's source language.

    Only structural text (non-URL, non-emoji, non-domain lines) is translated.
    WhatsApp bold markers (*word*) are preserved.

    Falls back to the English reply if translation is unavailable.

    Args:
        english_reply: The English-formatted reply string.
        target_lang:   BCP-47 language code (e.g. 'hi', 'mr', 'ta').

    Returns:
        Translated reply string, or the original English if translation fails.
    """
    if not target_lang or target_lang.startswith("en"):
        return english_reply

    if not english_reply.strip():
        return english_reply

    try:
        from app.features.nlp.translation import translate_to_english

        # We reuse the same translation pipeline — note M2M100 can translate
        # English → Indic when src_lang is set correctly.
        # For the reverse direction we use Gemini (it handles en→hi well).
        from app.core.config import settings as cfg

        if not cfg.gemini_api_key:
            logger.info("No Gemini key — returning English reply.")
            return english_reply

        from google import genai

        client = genai.Client(api_key=cfg.gemini_api_key)
        prompt = (
            f"Translate the following WhatsApp fact-check reply into language code '{target_lang}'. "
            "Preserve all *bold* markers, emojis, and URLs exactly as-is. "
            "Output ONLY the translated text:\n\n"
            f"{english_reply}"
        )
        response = client.models.generate_content(
            model=cfg.gemini_model,
            contents=prompt,
        )
        if response and response.text:
            translated = response.text.strip()
            # Respect WhatsApp hard cap after translation
            if len(translated) > WHATSAPP_HARD_CAP:
                translated = translated[:WHATSAPP_HARD_CAP - 3] + "…"
            return translated

    except Exception as exc:
        logger.warning("Reply back-translation to '%s' failed: %s", target_lang, exc)

    return english_reply
