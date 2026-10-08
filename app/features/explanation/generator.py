"""
Explanation generator (Wave 7).

Produces a human-readable English explanation of the overall verdict by:
  1. Summarising Tier-1/2 fact-checker evidence (if any).
  2. Describing the most relevant supporting/refuting snippets.
  3. Optionally using Gemini to write a fluent 2-3 sentence summary.

Falls back to a deterministic template if Gemini is unavailable.
"""

from __future__ import annotations

import logging
import textwrap
from typing import List

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


def _top_evidence_text(result: ClaimResult, max_items: int = 3) -> str:
    """Extract the most relevant evidence snippets as a numbered bullet list."""
    items = sorted(result.evidence, key=lambda e: -e.score)[:max_items]
    lines: List[str] = []
    for idx, item in enumerate(items, 1):
        stance_tag = f"[{item.stance}] " if item.stance else ""
        lines.append(f"  {idx}. {stance_tag}{item.snippet[:260].strip()} — {item.source_domain}")
    return "\n".join(lines) if lines else "  (no evidence retrieved)"


def _template_explanation(result: ClaimResult) -> str:
    """Deterministic template-based explanation (Gemini fallback)."""
    from app.features.explanation.formatter import compute_evidence_strength

    emoji = VERDICT_EMOJI.get(result.verdict, "❓")
    label = VERDICT_LABEL.get(result.verdict, str(result.verdict))
    strength_label, strength_detail = compute_evidence_strength(result.evidence)
    ev_text = _top_evidence_text(result)

    lines = [
        f"Verdict: {emoji} {label}",
        f"Evidence strength: {strength_label} · {strength_detail}",
        f'Claim: "{result.claim[:200]}"',
        "",
        "Evidence summary:",
        ev_text,
    ]

    if result.reason_code == "AUTHORITATIVE_FACT_CHECK":
        lines.append("")
        lines.append("This verdict is based on an authoritative fact-checking source.")
    elif result.reason_code == "NO_EVIDENCE":
        lines.append("")
        lines.append("No relevant evidence was found for this claim. Please verify manually.")
    elif result.reason_code in ("LOW_EVIDENCE_SIGNAL", "INCONCLUSIVE"):
        lines.append("")
        lines.append("Evidence was inconclusive. Treat this claim with caution.")

    return "\n".join(lines)


def _gemini_explanation(result: ClaimResult) -> str | None:
    """
    Use Gemini Flash to write a fluent, objective 2-3 sentence explanation.
    Returns None if Gemini key is missing or call fails.
    """
    if not settings.gemini_api_key:
        return None

    label = VERDICT_LABEL.get(result.verdict, str(result.verdict))
    ev_text = _top_evidence_text(result, max_items=3)

    prompt = textwrap.dedent(f"""
        You are an expert fact-checking assistant for an Indian WhatsApp misinformation detection service.
        Write a concise, objective 2-3 sentence explanation of the following fact-check verdict.
        Do NOT use markdown formatting (no bold, asterisks, bullet points, or headers).
        Keep it under 150 words and suitable for WhatsApp.

        Claim: "{result.claim[:300]}"
        Assessed Verdict: {label}
        Retrieved Evidence:
        {ev_text}

        Guidelines:
        - If the verdict is REFUTED, explicitly state that the claim is false, a myth, or unscientific, explaining what experts or evidence actually say.
        - If the verdict is SUPPORTED, summarize the key evidence confirming the fact.
        - If MISLEADING, clarify what aspect is inaccurate, exaggerated, or pseudoscientific.
        - Output ONLY the plain text explanation.
    """).strip()

    try:
        from google import genai

        client = genai.Client(api_key=settings.gemini_api_key)
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
        )
        if response and response.text:
            cleaned = response.text.strip().replace("*", "").replace("#", "")
            return cleaned
    except Exception as exc:
        logger.warning("Gemini explanation generation failed: %s", exc)

    return None


def generate_explanation(result: ClaimResult) -> str:
    """
    Generate a human-readable explanation for a single ClaimResult.

    Tries Gemini first; falls back to a deterministic template.

    Args:
        result: A fully-populated ClaimResult (verdict, confidence, evidence).

    Returns:
        Plain-text explanation string (no markdown).
    """
    gemini_text = _gemini_explanation(result)
    if gemini_text:
        logger.debug("Using Gemini-generated explanation.")
        return gemini_text

    logger.debug("Using template explanation (Gemini unavailable or failed).")
    return _template_explanation(result)
