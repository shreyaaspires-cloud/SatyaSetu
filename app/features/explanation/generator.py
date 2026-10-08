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
    Verdict.MISLEADING: "⚠️",
    Verdict.UNVERIFIABLE: "❓",
}

VERDICT_LABEL: dict = {
    Verdict.SUPPORTED: "SUPPORTED",
    Verdict.REFUTED: "REFUTED",
    Verdict.MISLEADING: "MISLEADING / PARTLY TRUE",
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
    emoji = VERDICT_EMOJI.get(result.verdict, "❓")
    label = VERDICT_LABEL.get(result.verdict, str(result.verdict))
    conf_pct = int(result.confidence * 100)
    ev_text = _top_evidence_text(result)

    lines = [
        f"Verdict: {emoji} {label} (confidence: {conf_pct}%)",
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


def _evidence_word_pool(result: ClaimResult) -> set[str]:
    """
    Build a set of lowercase content words from all evidence snippets and titles.
    Used to validate that each sentence in a Gemini explanation has grounding.
    """
    import re as _re
    pool: set[str] = set()
    for item in result.evidence:
        for text in (item.snippet, item.title, item.source_domain):
            tokens = _re.findall(r"\b[a-z]{3,}\b", text.lower())
            pool.update(tokens)
    # Also add words from the claim itself
    pool.update(_re.findall(r"\b[a-z]{3,}\b", result.claim.lower()))
    return pool


def _is_grounded(sentence: str, word_pool: set[str]) -> bool:
    """
    Return True if at least one content word in the sentence appears in the
    evidence/claim word pool. Sentences with zero overlap are hallucinated.
    """
    import re as _re
    _STOP = {"the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
              "it", "its", "of", "in", "on", "at", "to", "for", "and", "or", "but",
              "not", "no", "this", "that", "has", "have", "had", "with", "by"}
    tokens = {w for w in _re.findall(r"\b[a-z]{3,}\b", sentence.lower())
              if w not in _STOP}
    return bool(tokens & word_pool)


def _validate_explanation(text: str, result: ClaimResult) -> bool:
    """
    Validate every sentence in the Gemini explanation against evidence.
    Returns True only if all sentences are grounded in evidence or the claim.
    When evidence is empty, any non-empty text is considered ungrounded.
    """
    if not result.evidence:
        # No evidence retrieved → any generated text is ungrounded
        return False

    import re as _re
    word_pool = _evidence_word_pool(result)
    sentences = [s.strip() for s in _re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]

    for sentence in sentences:
        if not _is_grounded(sentence, word_pool):
            logger.warning(
                "Explanation sentence has no evidence grounding — rejecting Gemini output. "
                "Sentence: '%.80s'", sentence
            )
            return False
    return True


def generate_explanation(result: ClaimResult) -> str:
    """
    Generate a human-readable explanation for a single ClaimResult.

    Steps (T5 hardened):
      1. Call Gemini for a fluent 2-3 sentence explanation.
      2. Validate every sentence against evidence word-overlap.
         If any sentence is ungrounded → discard and fall back to template.
      3. Fall back to deterministic template if Gemini is unavailable.

    Args:
        result: A fully-populated ClaimResult (verdict, confidence, evidence).

    Returns:
        Plain-text explanation string (no markdown).
    """
    gemini_text = _gemini_explanation(result)
    if gemini_text:
        if _validate_explanation(gemini_text, result):
            logger.debug("Using Gemini-generated explanation (grounding validated).")
            return gemini_text
        logger.warning(
            "Gemini explanation failed grounding check — using template fallback."
        )

    logger.debug("Using template explanation (Gemini unavailable or failed grounding).")
    return _template_explanation(result)

