"""
Check-worthiness scorer for prioritizing factual claims over greetings,
questions, and subjective opinions.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# Common non-factual indicators (greetings, polite chit-chat)
GREETING_PATTERNS = [
    r"\bgood\s+(?:morning|afternoon|evening|night)\b",
    r"\bhave\s+a\s+(?:nice|great|wonderful|blessed)\s+day\b",
    r"\bhappy\s+(?:birthday|anniversary|diwali|holi|eid|new\s+year)\b",
    r"\bsuprabhat\b",
    r"\bshubh\s+(?:prabhat|ratri|din)\b",
    r"\bhello\b",
    r"\bhi\s+there\b",
]

# Subjective opinion indicators
OPINION_PATTERNS = [
    r"\bi\s+(?:personally\s+)?(?:feel|think|believe|guess)\b",
    r"\bin\s+my\s+(?:opinion|view)\b",
    r"\bit\s+seems\s+to\s+me\b",
]

# Factual markers (entities, numbers, government, health, scheme terms)
FACTUAL_MARKERS = [
    r"\b\d+[\d,.]*\s*(?:rupees|rs|crore|lakh|percent|%|died|injured|people|cases|metres|km|litres|liters)\b",
    r"\b(?:government|pib|modi|minister|court|police|who|fda|isro|nasa|rbi)\b",
    r"\b(?:cure|treatment|vaccine|corona|covid|cancer|remedy|death|killed|banned|approved|announced)\b",
    r"\b(?:scheme|yojana|subsidy|stipend|bonus|pension|recharge|lottery|winner)\b",
    r"\b(?:yojana|sarkar|pradhan\s*mantri|kisan|dawa|ilaj)\b",
]

GREETING_REGEX = re.compile("|".join(GREETING_PATTERNS), re.IGNORECASE)
OPINION_REGEX = re.compile("|".join(OPINION_PATTERNS), re.IGNORECASE)
FACTUAL_REGEX = re.compile("|".join(FACTUAL_MARKERS), re.IGNORECASE)


def score_check_worthiness(text: str) -> float:
    """
    Compute a check-worthiness score between 0.0 and 1.0 for the text.
    Factual claims, health rumors, government scheme assertions, and scam promises
    receive high scores (>= 0.70).
    Greetings, chit-chat, questions, and subjective opinions receive low scores (< 0.40).
    """
    cleaned = text.strip()
    if not cleaned:
        return 0.0

    # Short texts are rarely full factual claims
    if len(cleaned) < 10:
        return 0.15

    # Check for pure greetings
    if GREETING_REGEX.search(cleaned) and not FACTUAL_REGEX.search(cleaned):
        return 0.10

    # Check for pure questions
    if cleaned.endswith("?") and not FACTUAL_REGEX.search(cleaned):
        return 0.20

    # Check for subjective opinion statements
    if OPINION_REGEX.search(cleaned) and not FACTUAL_REGEX.search(cleaned):
        return 0.25

    # Base score for declarative text
    score = 0.50

    # Boost score for factual markers
    matches = FACTUAL_REGEX.findall(cleaned)
    if matches:
        score += min(len(matches) * 0.15, 0.40)

    # Check for digits/numbers (often indicate statistical or fiscal claims)
    if re.search(r"\b\d+\b", cleaned):
        score += 0.10

    return min(round(score, 2), 1.0)


def is_check_worthy(text: str, threshold: float = 0.50) -> bool:
    """
    Determine if the text should be routed to retrieval and verification.
    """
    return score_check_worthiness(text) >= threshold
