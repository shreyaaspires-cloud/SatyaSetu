"""
Explanation generator (Wave 7 / Simplified Short Reason).

Produces a human-readable plain explanation of the verdict:
  - 1-2 short sentences (max 35 words).
  - School student reading level, no jargon, no markdown.
  - Deterministic template fallback ensuring zero-failure offline mode.
"""

from __future__ import annotations

import logging
import textwrap
from typing import List, Optional

from app.contracts.models import ClaimResult
from app.core.constants import Verdict
from app.core.config import settings

logger = logging.getLogger(__name__)

# Emoji labels for verdicts
VERDICT_EMOJI: dict = {
    Verdict.SUPPORTED: "✅",
    Verdict.REFUTED: "❌",
    Verdict.PARTIALLY_SUPPORTED: "⚠️",
    Verdict.OUTDATED: "⏳",
    Verdict.UNVERIFIABLE: "❓",
}

VERDICT_LABEL: dict = {
    Verdict.SUPPORTED: "SUPPORTED",
    Verdict.REFUTED: "REFUTED",
    Verdict.PARTIALLY_SUPPORTED: "PARTIALLY_SUPPORTED",
    Verdict.OUTDATED: "OUTDATED",
    Verdict.UNVERIFIABLE: "UNVERIFIABLE",
}

HEALTH_KEYWORDS = {
    "cure", "treat", "theek", "bimari", "disease", "cancer", "medicine",
    "drink", "peene", "health", "chemical", "gas", "fluorine", "bleach",
    "vaccine", "virus", "covid", "pani", "water", "herb", "ayurved"
}


def _top_evidence_text(result: ClaimResult, max_items: int = 3) -> str:
    """Extract decisive evidence snippets."""
    def _sort_key(e):
        stance_priority = 0 if e.stance in ("SUPPORTS", "REFUTES") else 1
        return (stance_priority, -e.score)

    items = sorted(result.evidence, key=_sort_key)[:max_items]
    lines: List[str] = []
    for idx, item in enumerate(items, 1):
        lines.append(f"{item.source_domain}: {item.snippet[:160].strip()}")
    return " | ".join(lines) if lines else "(no evidence)"


def _template_explanation(result: ClaimResult) -> str:
    """Deterministic short template-based explanation (1-2 lines)."""
    # 1. Exact gold match or authoritative debunking snippet
    if result.reason_code == "CLAIM_BANK_MATCH" and result.evidence:
        snippet = result.evidence[0].snippet.strip()
        return snippet[:160]

    # Health advisory special check
    claim_lower = result.claim.lower()
    if result.verdict == Verdict.UNVERIFIABLE and any(kw in claim_lower for kw in HEALTH_KEYWORDS):
        return "No medical evidence supports this claim. Consult a doctor or WHO.int."

    # Top authoritative evidence snippet if available
    if result.evidence:
        top_ev = max(result.evidence, key=lambda e: e.score)
        if top_ev.snippet:
            s = top_ev.snippet.strip()
            if len(s) > 160:
                s = s[:157] + "..."
            return s

    # Single-line template per verdict / reason
    if result.verdict == Verdict.REFUTED:
        return "Independent fact-checkers found no evidence supporting this claim."
    elif result.verdict == Verdict.SUPPORTED:
        return "Verified by credible reports and authoritative sources."
    elif result.verdict == Verdict.PARTIALLY_SUPPORTED:
        return "This mixes true information with inaccurate or exaggerated details."
    elif result.verdict == Verdict.OUTDATED:
        return "This describes an older event or policy that is no longer valid."
    elif result.reason_code == "NO_EVIDENCE":
        return "No relevant evidence found to confirm this claim."
    elif result.reason_code in ("LOW_EVIDENCE_SIGNAL", "INCONCLUSIVE"):
        return "Evidence is inconclusive. Please verify with primary sources."

    return "Not enough proof yet to confirm this claim."


def _gemini_explanation(result: ClaimResult) -> str | None:
    """Use Gemini Flash to write a concise 1-2 sentence explanation (max 35 words)."""
    if not settings.gemini_api_key:
        return None

    label = VERDICT_LABEL.get(result.verdict, str(result.verdict))
    ev_text = _top_evidence_text(result, max_items=3)

    from app.core.redaction import redact_for_external
    redacted_claim = redact_for_external(result.claim[:240])

    prompt = textwrap.dedent(f"""
        You are an objective fact-checker for an Indian WhatsApp misinformation service.
        Claim: "{redacted_claim}"
        Verdict: {label}
        Evidence: {ev_text}

        Write exactly 1 or 2 short sentences explaining why this verdict was reached (maximum 35 words total).
        Requirements:
        - Reading level of a school student.
        - Simple, direct words. No jargon, no technical terms, no filler.
        - No bullet points, no markdown, no quotes, no asterisks.
        - Plain text only.
    """).strip()

    try:
        from google import genai
        client = genai.Client(api_key=settings.gemini_api_key)
        response = client.models.generate_content(model=settings.gemini_model, contents=prompt)
        if response and response.text:
            cleaned = (
                response.text.strip()
                .replace("**", "")
                .replace("*", "")
                .replace("#", "")
                .replace("`", "")
                .replace('"', "")
            )
            words = cleaned.split()
            if len(words) > 45:
                cleaned = " ".join(words[:40]) + "."
            return cleaned
    except Exception as exc:
        logger.warning("Gemini explanation generation failed: %s", exc)

    return None


def generate_explanation(result: ClaimResult) -> str:
    """Generate concise explanation for a ClaimResult."""
    # When there is no evidence and verdict is UNVERIFIABLE, do not hallucinate an explanation
    if not result.evidence and result.verdict == Verdict.UNVERIFIABLE:
        return _template_explanation(result)

    try:
        gemini_text = _gemini_explanation(result)
        if gemini_text and len(gemini_text) > 10:
            return gemini_text
    except Exception as exc:
        logger.warning("Explanation generation encountered error: %s", exc)

    return _template_explanation(result)
