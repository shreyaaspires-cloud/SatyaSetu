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


def _top_evidence_text(result: ClaimResult, max_items: int = 5) -> str:
    """
    Extract most relevant evidence. Prioritises SUPPORTS/REFUTES over NEUTRAL
    so Gemini sees decisive evidence first regardless of score ordering.
    """
    def _sort_key(e):
        stance_priority = 0 if e.stance in ("SUPPORTS", "REFUTES") else 1
        return (stance_priority, -e.score)

    items = sorted(result.evidence, key=_sort_key)[:max_items]
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

    # If we have an exact gold match from the pre-verified claim bank or authoritative debunking
    if result.reason_code == "CLAIM_BANK_MATCH" and result.evidence:
        real_fact = result.evidence[0].snippet.strip()
        lines = [
            f"Verdict: {emoji} {label}",
            f"Real News Fact Check: {real_fact}",
            f"Evidence strength: {strength_label} · {strength_detail}",
            f'Claim: "{result.claim[:200]}"',
            "",
            "Evidence summary:",
            ev_text,
        ]
        return "\n".join(lines)

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
    """Use Gemini Flash to write a detailed, objective fact-check explanation."""
    if not settings.gemini_api_key:
        return None

    label = VERDICT_LABEL.get(result.verdict, str(result.verdict))
    ev_text = _top_evidence_text(result, max_items=5)

    from app.core.redaction import redact_for_external
    redacted_claim = redact_for_external(result.claim[:300])

    prompt = textwrap.dedent(f"""
        You are an expert fact-checking journalist for an Indian WhatsApp misinformation detection service.
        Write a detailed, objective explanation (150-250 words) of the following fact-check verdict.
        Do NOT use markdown formatting (no bold, asterisks, bullet points, headers, or backticks).
        Keep it readable as plain WhatsApp text.

        Claim: "{redacted_claim}"
        Assessed Verdict: {label}
        Retrieved Evidence:
        {ev_text}

        Your explanation MUST:
        1. State clearly whether the claim is TRUE, FALSE, MISLEADING, OUTDATED, or UNVERIFIABLE.
        2. Explain WHY — cite specific facts, numbers, or named sources from the evidence above.
        3. Provide context — what IS actually true about this topic.
        4. Name the authoritative sources checked (PIB, WHO, AltNews, BOOM, Factly, etc.) if present.
        5. If TRUE: explain what makes it accurate and well-corroborated.
        6. If FALSE: explain exactly what is wrong and what the real fact is.
        7. Use simple language suitable for Indian WhatsApp users.

        Output ONLY the plain text explanation, no bullet points, no asterisks, no backticks.
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
            )
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


def _filter_explanation_sentences(text: str, result: ClaimResult) -> str:
    """
    Filter out ungrounded sentences rather than rejecting the whole explanation.
    Returns the grounded portion, or empty string to trigger template fallback.
    """
    if not result.evidence:
        return ""

    import re as _re
    word_pool = _evidence_word_pool(result)
    sentences = [s.strip() for s in _re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]

    grounded_sentences = []
    for sentence in sentences:
        if _is_grounded(sentence, word_pool):
            grounded_sentences.append(sentence)
        else:
            logger.debug("Filtering out ungrounded sentence: '%.80s'", sentence)

    return " ".join(grounded_sentences)


def generate_explanation(result: ClaimResult) -> str:
    """
    Generate a human-readable explanation for a single ClaimResult.

    Steps:
      1. Call Gemini for a detailed 150-250 word explanation.
      2. Filter individual ungrounded sentences (not all-or-nothing rejection).
      3. Fall back to deterministic template if Gemini fails or all filtered.
    """
    gemini_text = _gemini_explanation(result)
    if gemini_text:
        filtered = _filter_explanation_sentences(gemini_text, result)
        if filtered:
            logger.debug("Using Gemini explanation (%d chars, grounding passed).", len(filtered))
            return filtered
        logger.warning("All Gemini sentences failed grounding — falling back to template.")

    logger.debug("Using template explanation.")
    return _template_explanation(result)

