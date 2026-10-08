"""
Claim extraction, sentence splitting, and forward pressure detection.
"""

from __future__ import annotations

import logging
import re
from typing import List, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

# Patterns signaling viral forwarding pressure in WhatsApp forwards
FORWARD_PRESSURE_PATTERNS = [
    # English patterns
    r"\bforward\s+(?:this|to|with)\b",
    r"\bshare\s+(?:this|with|to|in)\b",
    r"\bshare\s+to\s+all\b",
    r"\bspread\s+the\s+word\b",
    r"\bsend\s+to\s+\d+\b",
    r"\bforward\s+to\s+everyone\b",
    r"\bviral\s+message\b",
    r"\bwhatsapp\s+group\b",

    # Hindi Devanagari patterns
    r"फॉरवर्ड\s*(?:करें|करो|कीजिए)",
    r"शेयर\s*(?:करें|करो|कीजिए)",
    r"सबको\s*(?:भेजें|भेजो)",
    r"ग्रुप\s*में\s*(?:भेजें|भेजो)",
    r"ज्यादा\s*से\s*ज्यादा\s*शेयर",
    r"संदेश\s*(?:फॉरवर्ड|शेयर)",

    # Hinglish patterns
    r"\bforward\s+karo\b",
    r"\bshare\s+karo\b",
    r"\bsabko\s+bhejo\b",
    r"\bgroup\s+me\s+bhejo\b",
    r"\bviral\s+karo\b",
]

FORWARD_PRESSURE_REGEX = re.compile(
    "|".join(FORWARD_PRESSURE_PATTERNS),
    re.IGNORECASE,
)

# Sentence boundary regex supporting Latin and Indic punctuation
SENTENCE_SPLIT_REGEX = re.compile(
    r"[.!?।॥\n\r]+",
)


PURE_FORWARD_REGEX = re.compile(
    r"^(?:please\s+)?(?:forward|share|send|spread|kripya)\s+.*(?:friends|contacts|groups|group|everyone|all|people|family|whatsapp|members).*",
    re.IGNORECASE,
)


def has_forward_pressure(text: str) -> bool:
    """
    Check if the input text contains viral WhatsApp forwarding pressure signals
    (e.g., commands to share to all groups or forward immediately).
    """
    if not text:
        return False
    return bool(FORWARD_PRESSURE_REGEX.search(text))


def split_sentences(text: str) -> List[str]:
    """
    Split text into clean non-empty sentences using Latin and Indic sentence boundaries.
    """
    if not text:
        return []

    parts = SENTENCE_SPLIT_REGEX.split(text)
    sentences = [p.strip() for p in parts if p and len(p.strip()) > 3]
    return sentences


def extract_claims(
    text: str,
    max_claims: Optional[int] = None,
) -> List[str]:
    """
    Extract factual claim candidates from input text.
    Filters out pure forward-instruction fragments and caps to max_claims.
    """
    if not text or not text.strip():
        return []

    cap = max_claims or settings.max_claims_per_message
    sentences = split_sentences(text)

    # If no sentences found (e.g. no punctuation), use whole text
    if not sentences:
        return [text.strip()[:500]]

    from app.features.nlp.worthiness import is_non_claim

    claims: List[str] = []
    for s in sentences:
        # Check if sentence is purely an instruction to forward with no other content
        if PURE_FORWARD_REGEX.match(s.strip()):
            continue

        cleaned_no_pressure = FORWARD_PRESSURE_REGEX.sub("", s).strip()
        if len(cleaned_no_pressure) < 5:
            # Skip pure forward instructions like "Please forward"
            continue

        # If there are multiple sentences, skip greetings and non-claims
        if len(sentences) > 1 and is_non_claim(s):
            continue

        claims.append(s)
        if len(claims) >= cap:
            break

    # If all extracted were non-claims, return empty list
    return [c for c in claims if not is_non_claim(c)]
