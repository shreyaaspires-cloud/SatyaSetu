"""
Explanation generator (Wave 7 / Simplified Short Reason).

Produces a human-readable plain explanation of the verdict:
  - 1-2 short sentences (max 35 words).
  - School student reading level, no jargon, no markdown.
  - Deterministic template fallback ensuring zero-failure offline mode.
"""

from __future__ import annotations

import logging
import re
import textwrap
from typing import List, Optional

from app.contracts.models import ClaimResult
from app.core.constants import Verdict
from app.core.config import settings
from app.core.constants import Tier

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

# Patterns that indicate ad/boilerplate content — never use these as explanations.
_AD_PATTERNS: List[re.Pattern] = [
    re.compile(p, re.IGNORECASE) for p in [
        r"save\s+rs\.?\s*\d+",          # "Save Rs 588"
        r"subscribe\s+now",              # "Subscribe Now"
        r"ad[- ]?free\s+(membership|plan|subscription)",
        r"\d+[- ]year\s+(membership|plan|subscription)",
        r"cookie\s+policy",
        r"sign\s+in\s+to\s+(continue|read)",
        r"log\s+in\s+to\s+(continue|read)",
        r"(this\s+content\s+is\s+)?(for\s+)?subscriber(s)?\s+only",
        r"join\s+(now|today|free)",
        r"limited[- ]time\s+offer",
        r"discount\s+code",
        r"pro\s+(membership|plan)",
        r"popular\s+courses\s+academy",
        r"coaching\s+books?",
        r"(get|buy)\s+(now|today)\s+at\s+rs",
        r"click\s+here\s+to\s+(subscribe|register|buy|learn\s+more)",
    ]
]


# Tier numeric priority — lower = higher trust
_TIER_PRIORITY = {
    Tier.TIER_1_IFCN: 1,
    Tier.TIER_2_GOV_PIB: 2,
    Tier.TIER_3_MAINSTREAM: 3,
    Tier.TIER_4_WIKIPEDIA: 4,
    Tier.TIER_5_GENERAL_WEB: 5,
}


def _is_ad_snippet(text: str) -> bool:
    """Return True if the snippet looks like an ad or boilerplate page element."""
    if not text:
        return False
    return any(pat.search(text) for pat in _AD_PATTERNS)


def _clean_snippet(text: str) -> str:
    """Strip common HTML artifacts and excessive whitespace from a raw snippet."""
    if not text:
        return ""
    # Remove HTML tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _top_evidence_text(result: ClaimResult, max_items: int = 3) -> str:
    """Extract decisive evidence snippets, prioritising high-trust tiers and filtering ad content."""
    def _sort_key(e):
        tier_pri = _TIER_PRIORITY.get(getattr(e, 'tier', None), 99)
        stance_priority = 0 if e.stance in ("SUPPORTS", "REFUTES") else 1
        return (tier_pri, stance_priority, -e.score)

    # Filter out ad snippets before selecting evidence
    clean_evidence = [
        e for e in result.evidence
        if not _is_ad_snippet(_clean_snippet(e.snippet))
    ]
    # Fall back to all evidence if filtering removed everything
    if not clean_evidence:
        clean_evidence = result.evidence

    items = sorted(clean_evidence, key=_sort_key)[:max_items]
    lines: List[str] = []
    for idx, item in enumerate(items, 1):
        snippet = _clean_snippet(item.snippet)
        lines.append(f"{item.source_domain}: {snippet[:160].strip()}")
    return " | ".join(lines) if lines else "(no evidence)"


def _template_explanation(result: ClaimResult) -> str:
    """Deterministic short template-based explanation (1-2 lines)."""
    # 1. Exact gold match or authoritative debunking snippet
    if result.reason_code == "CLAIM_BANK_MATCH" and result.evidence:
        snippet = _clean_snippet(result.evidence[0].snippet)
        if snippet and not _is_ad_snippet(snippet):
            return snippet[:160]

    # Health advisory special check
    claim_lower = result.claim.lower()
    if result.verdict == Verdict.UNVERIFIABLE and any(kw in claim_lower for kw in HEALTH_KEYWORDS):
        return "No medical evidence supports this claim. Consult a doctor or WHO.int."

    # Top authoritative evidence snippet — tier-first, ad-filtered
    if result.evidence:
        def _rank(e):
            return (_TIER_PRIORITY.get(getattr(e, 'tier', None), 99), -e.score)

        for ev in sorted(result.evidence, key=_rank):
            s = _clean_snippet(ev.snippet)
            if s and not _is_ad_snippet(s):
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
    """Generate concise explanation for a ClaimResult with resilient timeout."""
    # When there is no evidence and verdict is UNVERIFIABLE, do not hallucinate an explanation
    if not result.evidence and result.verdict == Verdict.UNVERIFIABLE:
        return _template_explanation(result)

    if settings.gemini_api_key:
        try:
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(_gemini_explanation, result)
                gemini_text = future.result(timeout=4.0)
                if gemini_text and len(gemini_text) > 10:
                    return gemini_text
        except concurrent.futures.TimeoutError:
            logger.warning("Gemini explanation timed out after 4.0s; using deterministic template fallback.")
        except Exception as exc:
            logger.warning("Explanation generation encountered error: %s", exc)

    return _template_explanation(result)
