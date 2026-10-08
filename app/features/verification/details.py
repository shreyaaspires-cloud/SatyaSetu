"""
Key detail agreement checker for stance scoring (T2).

Extracts typed details (directions, numbers with units, currency amounts,
percentages, years) from claim and evidence text, then detects conflicts:

  - DETAIL_MISMATCH: same detail type present on both sides with different values
    (e.g. "east" vs "north"; "Rs 500" vs "Rs 5000"; "2021" vs "2025")
    → Evidence becomes context only; cannot SUPPORT or REFUTE.

  - None: no typed conflict found → normal stance scoring proceeds.

Negation handling is separate: when only one side carries a negation word,
the item is treated as opposite-polarity evidence (REFUTES), not a mismatch.
"""

from __future__ import annotations

import re
from typing import Optional

# ---------------------------------------------------------------------------
# Direction vocabulary (English + common Hindi transliterations)
# ---------------------------------------------------------------------------
_DIRECTION_WORDS = frozenset({
    "north", "south", "east", "west",
    "northeast", "northwest", "southeast", "southwest",
    "uttar", "dakshin", "purv", "paschim",
})

# ---------------------------------------------------------------------------
# Negation vocabulary
# ---------------------------------------------------------------------------
_NEGATION_PATTERNS: list[str] = [
    r"\bnot\b", r"\bno\b", r"\bnever\b",
    r"\bcannot\b", r"\bcan't\b", r"\bcan not\b",
    r"\bdoes not\b", r"\bdoesn't\b",
    r"\bdo not\b", r"\bdon't\b",
    r"\bdid not\b", r"\bdidn't\b",
    r"\bwill not\b", r"\bwon't\b",
    r"\bis not\b", r"\bisn't\b",
    r"\bare not\b", r"\baren't\b",
    r"\bwas not\b", r"\bwasn't\b",
    r"\bwere not\b", r"\bweren't\b",
    r"\bnahi\b", r"\bnahin\b", r"\bmat\b",      # Hindi negations
]
_NEGATION_RE = re.compile("|".join(_NEGATION_PATTERNS), re.IGNORECASE)


def has_negation(text: str) -> bool:
    """Return True if the text contains a negation word."""
    return bool(_NEGATION_RE.search(text))


# ---------------------------------------------------------------------------
# Detail extractors
# ---------------------------------------------------------------------------

def _extract_directions(text: str) -> frozenset[str]:
    """Return direction words found in text."""
    text_lower = text.lower()
    return frozenset(
        d for d in _DIRECTION_WORDS
        if re.search(r"\b" + re.escape(d) + r"\b", text_lower)
    )


def _extract_currency_amounts(text: str) -> frozenset[str]:
    """
    Extract currency amounts.
    Recognises: 'Rs 500', 'Rs. 5,000', 'INR 500', '500 rupees', '5000 rs'.
    Normalises comma-separated numbers and returns raw numeric strings.
    """
    text_lower = text.lower()
    amounts: set[str] = set()

    # Pattern: Rs/INR prefix then number
    for m in re.finditer(
        r"(?:rs\.?\s*|inr\s*)(\d[\d,]*(?:\.\d+)?)", text_lower
    ):
        amounts.add(m.group(1).replace(",", ""))

    # Pattern: number then rupees/rs suffix
    for m in re.finditer(
        r"(\d[\d,]*(?:\.\d+)?)\s*(?:rupees?|rs\.?)\b", text_lower
    ):
        amounts.add(m.group(1).replace(",", ""))

    return frozenset(amounts)


def _extract_percentages(text: str) -> frozenset[str]:
    """Extract percentage figures, e.g. '2 percent', '2.5%'."""
    text_lower = text.lower()
    return frozenset(
        m.group(1)
        for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(?:percent|%)", text_lower)
    )


def _extract_years(text: str) -> frozenset[str]:
    """Extract 4-digit calendar years (1900–2099)."""
    return frozenset(re.findall(r"\b((?:19|20)\d{2})\b", text))


def _extract_number_units(text: str) -> dict[str, frozenset[str]]:
    """
    Extract numbers paired with specific unit words.
    Returns {unit_word: frozenset(numeric_strings)}.
    """
    text_lower = text.lower()
    result: dict[str, frozenset[str]] = {}
    _UNITS = [
        "month", "months", "year", "years", "day", "days",
        "week", "weeks", "hour", "hours",
        "km", "kg", "crore", "lakh", "thousand",
        "million", "billion",
    ]
    for unit in _UNITS:
        values = frozenset(
            m.group(1)
            for m in re.finditer(
                r"(\d+(?:\.\d+)?)\s*" + re.escape(unit), text_lower
            )
        )
        if values:
            # normalise plural → singular key
            key = unit.rstrip("s") if unit.endswith("s") and unit != "crores" else unit
            if key in result:
                result[key] = result[key] | values
            else:
                result[key] = values
    return result


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def check_detail_conflict(claim: str, evidence: str) -> Optional[str]:
    """
    Compare typed key details from a claim and an evidence snippet.

    Rules (applied in order):
      1. Directions: if both texts mention direction words but share none
         → DETAIL_MISMATCH
      2. Currency: if both mention currency amounts but share none
         → DETAIL_MISMATCH
      3. Percentages: if both mention percentage values but share none
         → DETAIL_MISMATCH
      4. Years: if both mention years but share none
         → DETAIL_MISMATCH
      5. Number+unit: for each shared unit key, if values differ entirely
         → DETAIL_MISMATCH

    Returns:
        "DETAIL_MISMATCH" | None
    """
    # --- 1. Directions ---
    claim_dirs = _extract_directions(claim)
    ev_dirs = _extract_directions(evidence)
    if claim_dirs and ev_dirs and not (claim_dirs & ev_dirs):
        return "DETAIL_MISMATCH"

    # --- 2. Currency ---
    claim_amounts = _extract_currency_amounts(claim)
    ev_amounts = _extract_currency_amounts(evidence)
    if claim_amounts and ev_amounts and not (claim_amounts & ev_amounts):
        return "DETAIL_MISMATCH"

    # --- 3. Percentages ---
    claim_pcts = _extract_percentages(claim)
    ev_pcts = _extract_percentages(evidence)
    if claim_pcts and ev_pcts and not (claim_pcts & ev_pcts):
        return "DETAIL_MISMATCH"

    # --- 4. Years ---
    claim_years = _extract_years(claim)
    ev_years = _extract_years(evidence)
    if claim_years and ev_years and not (claim_years & ev_years):
        return "DETAIL_MISMATCH"

    # --- 5. Numbers with units ---
    claim_nu = _extract_number_units(claim)
    ev_nu = _extract_number_units(evidence)
    shared_units = set(claim_nu.keys()) & set(ev_nu.keys())
    for unit in shared_units:
        if not (claim_nu[unit] & ev_nu[unit]):
            return "DETAIL_MISMATCH"

    return None
