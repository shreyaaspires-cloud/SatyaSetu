"""
app/features/retrieval/ratings.py
───────────────────────────────────
Rating normalization for converting heterogeneous fact-checker verdict strings
into canonical Rating enums.

Problem
────────
Different fact-checking organisations use different verdict labels:
  • PolitiFact: "Pants on Fire", "Mostly False", "Half True", "True"
  • AltNews:    "Fake", "Misleading", "Partially True"
  • Snopes:     "False", "Mixture", "Unproven"
  • Hindi:       "गलत", "भ्रामक", "सत्य"

This module collapses the long tail of rating strings into a small canonical
set (TRUE, FALSE, MISLEADING, PARTLY_TRUE, OUTDATED, UNVERIFIED) defined in
app.core.constants.Rating.

Matching algorithm
───────────────────
1. Lowercase + Unicode-safe strip of non-word / non-Devanagari characters.
2. Build a flat list of (phrase, Rating) pairs from the loaded mapping dict.
3. Sort longest-first: ensures "mostly false" (13 chars → PARTLY_TRUE) beats
   "false" (5 chars → FALSE) in cases of substring containment.
4. First match wins (word-boundary regex then substring fallback).
5. No match → Rating.UNVERIFIED.

Configuration
──────────────
Rating keyword lists are externalised to two YAML files:
  config/verification.yaml    — primary rating_mappings dict
  config/verdict_keywords.yaml — supplemental partly_supported / outdated lists
Both files are loaded once and cached for the process lifetime.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Dict, List, Optional

import yaml

from app.core.constants import Rating

logger = logging.getLogger(__name__)

# Process-lifetime cache; populated on first call to load_rating_mappings().
_rating_mappings_cache: Optional[Dict[Rating, List[str]]] = None


def get_verification_config_path() -> str:
    """Return path to config/verification.yaml."""
    base_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..")
    )
    return os.path.join(base_dir, "config", "verification.yaml")


def get_verdict_keywords_config_path() -> str:
    """Return path to config/verdict_keywords.yaml."""
    base_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..")
    )
    return os.path.join(base_dir, "config", "verdict_keywords.yaml")


def load_verdict_keywords() -> dict[str, list[str]]:
    """
    Load configurable keyword lists from config/verdict_keywords.yaml.

    These supplemental lists extend the main rating_mappings with nuanced
    verdicts that fact-checkers frequently use but don't fit cleanly into
    the primary TRUE/FALSE/MISLEADING buckets (e.g., 'old video', 'recycled').
    Falls back to embedded defaults if the YAML file is absent.
    """
    kw_path = get_verdict_keywords_config_path()
    if os.path.exists(kw_path):
        try:
            with open(kw_path, "r", encoding="utf-8") as f:
                content = yaml.safe_load(f) or {}
                return {
                    "partly_supported_keywords": content.get("partly_supported_keywords", []),
                    "outdated_keywords": content.get("outdated_keywords", []),
                }
        except Exception as exc:
            logger.warning("Failed to load %s: %s", kw_path, exc)
    return {
        "partly_supported_keywords": [
            "partly true", "half true", "mixture", "mostly true", "mostly false",
            "partly false", "mixed", "partially true", "partially false"
        ],
        "outdated_keywords": [
            "old", "outdated", "old video", "old photo", "old image", "recycled",
            "no longer", "expired", "not current", "not recent", "from [year]",
            "circulating again", "previously", "misleading context"
        ],
    }


def load_rating_mappings() -> Dict[Rating, List[str]]:
    """
    Load rating mappings from config/verification.yaml and config/verdict_keywords.yaml.
    Falls back to built-in rules if file is missing.

    YAML True/False keys: PyYAML parses unquoted 'true'/'false' as Python booleans.
    The `if key is True / key is False` guard converts them back to string keys
    before the Rating(str_key) enum lookup.
    """
    global _rating_mappings_cache
    if _rating_mappings_cache is not None:
        return _rating_mappings_cache

    config_path = get_verification_config_path()
    raw_dict = {}
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                content = yaml.safe_load(f) or {}
                raw_dict = content.get("rating_mappings", {})
        except Exception as exc:
            logger.warning("Failed to load %s: %s. Using default ratings.", config_path, exc)

    if not raw_dict:
        # Embedded fallback — keeps service functional when config is absent.
        # Hindi terms (गलत, झूठ, भ्रामक…) support Devanagari-script inputs.
        raw_dict = {
            "FALSE": [
                "false", "fake", "incorrect", "fabricated", "hoax", "untrue",
                "debunked", "pants on fire", "scam", "doctored", "manipulated",
                "misattributed", "गलत", "झूठ", "फेक", "अफवाह",
            ],
            "MISLEADING": [
                "misleading", "out of context", "missing context", "altered",
                "भ्रामक", "संदर्भहीन",
            ],
            "PARTLY_TRUE": [
                "partly true", "partially true", "half true", "mixed",
                "mostly false", "mostly true", "अंशतः सत्य", "आधा सच",
            ],
            "TRUE": [
                "true", "correct", "accurate", "verified", "confirmed",
                "सत्य", "सही", "पुष्ट",
            ],
        }

    # Merge in keywords from verdict_keywords.yaml (additive; no override).
    vk = load_verdict_keywords()
    raw_dict.setdefault("OUTDATED", []).extend(vk.get("outdated_keywords", []))
    raw_dict.setdefault("PARTLY_TRUE", []).extend(vk.get("partly_supported_keywords", []))

    parsed: Dict[Rating, List[str]] = {}
    for key, phrases in raw_dict.items():
        try:
            # Guard against PyYAML boolean coercion of 'true'/'false' keys.
            if key is True:
                str_key = "TRUE"
            elif key is False:
                str_key = "FALSE"
            else:
                str_key = str(key).upper().strip()
            enum_key = Rating(str_key)
            parsed[enum_key] = [p.lower().strip() for p in phrases]
        except ValueError:
            pass  # Unknown rating key in YAML — skip silently.

    _rating_mappings_cache = parsed
    return _rating_mappings_cache


def normalize_rating(raw_rating: Optional[str]) -> Rating:
    """
    Normalize any raw fact-checker rating text (e.g. 'Pants on Fire!', 'Mostly False',
    'भ्रामक दावा') into a canonical Rating enum.
    Returns Rating.UNVERIFIED if unclassifiable or empty.

    Matching pipeline
    ──────────────────
    1. Lowercase + strip non-word chars (preserve Devanagari U+0900-U+097F range).
    2. Flatten (phrase, Rating) pairs and sort by phrase length descending so
       longer, more specific phrases are matched before shorter substrings.
    3. Word-boundary regex search; fallback to substring containment check.
    4. First match wins — returns immediately without scanning remaining candidates.
    """
    if not raw_rating or not raw_rating.strip():
        return Rating.UNVERIFIED

    cleaned = raw_rating.lower().strip()
    # Keep word characters, spaces, and Devanagari block; strip punctuation noise.
    cleaned = re.sub(r"[^\w\s\u0900-\u097F]", "", cleaned).strip()

    mappings = load_rating_mappings()

    # Flatten and sort candidate phrases by length descending.
    # This ensures "mostly false" matches PARTLY_TRUE before "false" matches FALSE.
    all_candidates: List[tuple[str, Rating]] = []
    for rating_enum, phrases in mappings.items():
        for phrase in phrases:
            all_candidates.append((phrase, rating_enum))

    all_candidates.sort(key=lambda x: len(x[0]), reverse=True)

    for phrase, rating_enum in all_candidates:
        pattern = r"\b" + re.escape(phrase) + r"\b"
        if re.search(pattern, cleaned) or phrase in cleaned:
            return rating_enum

    return Rating.UNVERIFIED
