"""
app/features/nlp/worthiness.py
───────────────────────────────
Check-worthiness scorer for prioritizing factual claims over greetings,
questions, and subjective opinions.

Purpose
────────
Not all WhatsApp messages sent to SatyaSetu are fact-checkable claims.
This module acts as a routing gate: texts with low worthiness scores are
rejected early (saving downstream API calls) with a user-friendly message
explaining why the bot cannot verify the input.

Scoring model (heuristic rule-based)
──────────────────────────────────────
The scorer is intentionally lightweight — no ML inference — to give sub-1 ms
latency on the routing decision.

Score bands:
  0.00 – 0.09  Empty text
  0.10 – 0.19  Pure greetings (no factual markers)
  0.15         Very short text (< 10 chars)
  0.20         Pure questions without factual assertions
  0.25         Subjective opinions without factual assertions
  0.50+        Declarative text (baseline) boosted by factual markers
  ≥ 0.70       High-confidence factual claim

Factual boost: each regex match in FACTUAL_MARKERS adds +0.15, capped at +0.40.
Numeric boost: any \d+ token adds +0.10 (statistics, dates, monetary values).

Threshold (default 0.50): texts scoring ≥ 0.50 proceed to the full pipeline.
Callers can adjust threshold — e.g., use 0.30 for demo/lenient mode.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# ── Pattern libraries ─────────────────────────────────────────────────────────
# Common non-factual indicators (greetings, polite chit-chat).
# Each pattern targets one greeting archetype; OR-joined at compile time.
GREETING_PATTERNS = [
    r"\bgood\s+(?:morning|afternoon|evening|night)\b",
    r"\bhave\s+a\s+(?:nice|great|wonderful|blessed)\s+day\b",
    r"\bhappy\s+(?:birthday|anniversary|diwali|holi|eid|new\s+year)\b",
    r"\bsuprabhat\b",
    r"\bshubh\s+(?:prabhat|ratri|din)\b",
    r"\b(?:hello|hi|hey|namaste|namaskar|pranam)\b",
    r"\bhow\s+are\s+you\b",
]

# Subjective opinion indicators.
# A text containing one of these without factual markers is scored as opinion.
OPINION_PATTERNS = [
    r"\bi\s+(?:personally\s+)?(?:feel|think|believe|guess)\b",
    r"\bin\s+my\s+(?:opinion|view)\b",
    r"\bit\s+seems\s+to\s+me\b",
    r"\b(?:this|that|it|he|she)\s+is\s+(?:the\s+)?(?:best|worst|greatest|finest|most\s+amazing)\b",
    r"\b(?:is|are)\s+(?:the\s+)?(?:best|worst|greatest|finest)\b",
    r"\b(?:i\s+like|i\s+love|i\s+hate|i\s+prefer)\b",
]

# Factual markers (entities, numbers, government, health, scheme terms).
# Presence of even one marker elevates base score and overrides greeting/opinion gates.
FACTUAL_MARKERS = [
    r"\b\d+[\d,.]*\s*(?:rupees|rs|crore|lakh|percent|%|died|injured|people|cases|metres|km|litres|liters)\b",
    r"\b(?:government|pib|modi|minister|court|police|who|fda|isro|nasa|rbi)\b",
    r"\b(?:cure|treatment|vaccine|corona|covid|cancer|remedy|death|killed|banned|approved|announced)\b",
    r"\b(?:scheme|yojana|subsidy|stipend|bonus|pension|recharge|lottery|winner)\b",
    r"\b(?:yojana|sarkar|pradhan\s*mantri|kisan|dawa|ilaj)\b",
]

# Pre-compiled regex objects: reused across all calls, no re-compilation overhead.
GREETING_REGEX = re.compile("|".join(GREETING_PATTERNS), re.IGNORECASE)
OPINION_REGEX = re.compile("|".join(OPINION_PATTERNS), re.IGNORECASE)
FACTUAL_REGEX = re.compile("|".join(FACTUAL_MARKERS), re.IGNORECASE)


def is_greeting(text: str) -> bool:
    """Return True if text is a greeting without factual claims."""
    cleaned = text.strip()
    if not cleaned:
        return False
    # Factual markers override greeting classification: "Happy birthday — Modi
    # announced 2 crore jobs" should still be treated as a factual claim.
    return bool(GREETING_REGEX.search(cleaned) and not FACTUAL_REGEX.search(cleaned))


def is_opinion(text: str) -> bool:
    """Return True if text expresses an opinion without factual claims."""
    cleaned = text.strip()
    if not cleaned:
        return False
    return bool(OPINION_REGEX.search(cleaned) and not FACTUAL_REGEX.search(cleaned))


def is_pure_question(text: str) -> bool:
    """Return True if text is a pure question without factual assertion."""
    cleaned = text.strip()
    if not cleaned:
        return False
    is_q = cleaned.endswith("?") or bool(
        re.match(r"^(?:who|what|where|when|why|how|can\s+you|are\s+you)\b", cleaned, re.IGNORECASE)
    )
    # "Did the government ban X?" ends with "?" but contains a factual marker → not pure.
    return bool(is_q and not FACTUAL_REGEX.search(cleaned))


def is_non_claim(text: str) -> bool:
    """Return True if the text represents a non-claim (greeting, opinion, or pure question)."""
    cleaned = text.strip()
    if not cleaned:
        return True
    return is_greeting(cleaned) or is_opinion(cleaned) or is_pure_question(cleaned)


def score_check_worthiness(text: str) -> float:
    """
    Compute a check-worthiness score between 0.0 and 1.0 for the text.
    Factual claims, health rumors, government scheme assertions, and scam promises
    receive high scores (>= 0.70).
    Greetings, chit-chat, questions, and subjective opinions receive low scores (< 0.40).

    Algorithm
    ──────────
    1. Empty / very short → return early (0.00 / 0.15).
    2. Pure greeting with no factual markers → 0.10.
    3. Pure question ending with '?' and no factual markers → 0.20.
    4. Opinion pattern and no factual markers → 0.25.
    5. Declarative text baseline → 0.50.
    6. Factual marker boost: +0.15 per match, max +0.40.
    7. Digit boost: +0.10 if any standalone integer is present.
    8. Clamp to 1.0.
    """
    cleaned = text.strip()
    if not cleaned:
        return 0.0

    # Short texts are rarely full factual claims.
    if len(cleaned) < 10:
        return 0.15

    # Check for pure greetings.
    if GREETING_REGEX.search(cleaned) and not FACTUAL_REGEX.search(cleaned):
        return 0.10

    # Check for pure questions.
    if cleaned.endswith("?") and not FACTUAL_REGEX.search(cleaned):
        return 0.20

    # Check for subjective opinion statements.
    if OPINION_REGEX.search(cleaned) and not FACTUAL_REGEX.search(cleaned):
        return 0.25

    # Base score for declarative text.
    score = 0.50

    # Boost score for factual markers.
    matches = FACTUAL_REGEX.findall(cleaned)
    if matches:
        score += min(len(matches) * 0.15, 0.40)

    # Check for digits/numbers (often indicate statistical or fiscal claims).
    if re.search(r"\b\d+\b", cleaned):
        score += 0.10

    return min(round(score, 2), 1.0)


def is_check_worthy(text: str, threshold: float = 0.50) -> bool:
    """
    Determine if the text should be routed to retrieval and verification.

    The default threshold of 0.50 is conservative: it allows ambiguous declarative
    sentences through rather than silently dropping them.  Raise to 0.65+ for
    production deployments with high message volume to reduce API costs.
    """
    return score_check_worthiness(text) >= threshold
