"""
Explanation generator (Wave 7).

Produces a human-readable English explanation of the overall verdict by:
  1. Summarising Tier-1/2 fact-checker evidence (if any).
  2. Describing the most relevant supporting/refuting snippets.
  3. Optionally using Gemini to write a fluent 2-3 sentence summary.

# Generation Strategy:
#   1. Tier-1/2 official evidence priority (IFCN, PIB, WHO).
#   2. High-sensitivity detection for medical/health misinformation keywords.
#   3. Deterministic template fallback ensuring zero-failure offline mode.
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


HEALTH_KEYWORDS = {
    "cure", "treat", "theek", "bimari", "disease", "cancer", "medicine",
    "drink", "peene", "health", "chemical", "gas", "fluorine", "bleach",
    "vaccine", "virus", "covid", "pani", "water", "herb", "ayurved"
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

    claim_lower = result.claim.lower()
    if result.verdict == Verdict.UNVERIFIABLE and any(kw in claim_lower for kw in HEALTH_KEYWORDS):
        lines.append("")
        lines.append(
            "Health advisory: No scientific or medical evidence supports claims that any household chemical, gas, or unverified substance cures disease. Please consult a certified doctor or check WHO.int and ICMR.gov.in for accurate health information."
        )

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
        A user forwarded this claim: "{redacted_claim}"
        The system's verdict is: {label}

        Retrieved evidence (may be sparse or empty):
        {ev_text}

        Write a clear, factual explanation of 120-200 words for this claim.
        
        IMPORTANT RULES:
        - Use the retrieved evidence if it is relevant and high-quality.
        - If retrieved evidence is sparse, weak, or only background context, USE YOUR OWN KNOWLEDGE
          of science, medicine, Indian government policy, current events, and social media hoaxes.
        - For health/chemical claims: explain what science says about the substance.
        - For government policy claims: state what the actual policy is.
        - For celebrity/public figure claims: state what is factually known.
        - For viral hoaxes (UPI tax, WhatsApp shutdown, 5G cancer, free scheme, etc.): debunk directly.
        - Always end with: which source a user should check (WHO, PIB, RBI, NPCI, etc.) for this topic.
        - Do NOT say "based on the retrieved evidence" — just state the facts directly.
        - Plain text only. No bullet points, no markdown, no asterisks.

        Write the explanation now:
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
    Relaxed grounding filter.
    Only filter aggressively when we have rich, high-quality evidence.
    When evidence is sparse, trust Gemini's parametric knowledge.
    """
    if not text or not text.strip():
        return ""

    # Determine evidence quality
    high_quality_items = [
        i for i in result.evidence
        if (i.score or 0.0) >= 0.65 and getattr(i.tier, "value", str(i.tier)) in ("tier_1_ifcn", "tier_2_gov_pib", "tier_3_mainstream")
    ]

    if not result.evidence:
        claim_lower = result.claim.lower()
        if any(kw in claim_lower for kw in HEALTH_KEYWORDS):
            return text.strip()
        # For non-health ungrounded claims with zero evidence (AT15):
        # Discard hallucinated explanation and fall back to template
        return ""

    # If evidence is sparse or low quality → trust Gemini fully, no filtering
    if len(high_quality_items) < 2:
        return text.strip()


    # Rich evidence available → apply relaxed per-sentence filter
    import re as _re
    word_pool = _evidence_word_pool(result)
    sentences = [s.strip() for s in _re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]

    grounded = []
    for sentence in sentences:
        # Short sentences (≤ 12 words) are connective, never hallucinations — keep them
        if len(sentence.split()) <= 12:
            grounded.append(sentence)
            continue
        if _is_grounded(sentence, word_pool):
            grounded.append(sentence)
        else:
            logger.debug("Filtering ungrounded sentence: '%.80s'", sentence)

    # Safety: if filtering removed too much, return original
    if len(grounded) < 2:
        return text.strip()

    return " ".join(grounded)


def _gemini_quick_context(claim: str, verdict_label: str) -> str | None:
    """
    Lightweight 2-sentence factual context from Gemini.
    Used as template fallback when full explanation fails.
    """
    if not settings.gemini_api_key:
        return None
    try:
        from google import genai
        from app.core.redaction import redact_for_external
        client = genai.Client(api_key=settings.gemini_api_key)
        prompt = (
            f'A WhatsApp claim says: "{redact_for_external(claim[:200])}"\n'
            f'Verdict: {verdict_label}\n'
            f'Write exactly 2 sentences: (1) what the claim says and why it is {verdict_label}, '
            f'(2) what the actual fact is. Plain text, no formatting.'
        )
        response = client.models.generate_content(model=settings.gemini_model, contents=prompt)
        if response and response.text:
            return response.text.strip().replace("**", "").replace("*", "")
    except Exception as exc:
        logger.debug("Quick context Gemini call failed: %s", exc)
    return None


def generate_explanation(result: ClaimResult) -> str:
    """
    Generate human-readable explanation for a single ClaimResult.
    Tries full Gemini explanation -> quick Gemini context -> deterministic template.
    """
    try:
        # Step 1: Full Gemini explanation
        gemini_text = _gemini_explanation(result)
        if gemini_text:
            filtered = _filter_explanation_sentences(gemini_text, result)
            if filtered and len(filtered) > 80:
                return filtered

        # Step 2: Quick 2-sentence Gemini context (cheaper fallback)
        label = VERDICT_LABEL.get(result.verdict, str(result.verdict))
        quick = _gemini_quick_context(result.claim, label)
        if quick and len(quick) > 40:
            logger.debug("Using quick Gemini context fallback.")
            return quick
    except Exception as exc:
        logger.warning("Explanation generation encountered error: %s", exc)

    # Step 3: Deterministic template (last resort)
    logger.debug("Using template explanation.")
    return _template_explanation(result)


