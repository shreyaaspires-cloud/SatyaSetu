"""
Rating normalization for converting heterogeneous fact-checker verdict strings
into canonical Rating enums.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Dict, List, Optional

import yaml

from app.core.constants import Rating

logger = logging.getLogger(__name__)

_rating_mappings_cache: Optional[Dict[Rating, List[str]]] = None


def get_verification_config_path() -> str:
    """Return path to config/verification.yaml."""
    base_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..")
    )
    return os.path.join(base_dir, "config", "verification.yaml")


def load_rating_mappings() -> Dict[Rating, List[str]]:
    """
    Load rating mappings from config/verification.yaml.
    Falls back to built-in rules if file is missing.
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

    parsed: Dict[Rating, List[str]] = {}
    for key, phrases in raw_dict.items():
        try:
            if key is True:
                str_key = "TRUE"
            elif key is False:
                str_key = "FALSE"
            else:
                str_key = str(key).upper().strip()
            enum_key = Rating(str_key)
            parsed[enum_key] = [p.lower().strip() for p in phrases]
        except ValueError:
            pass

    _rating_mappings_cache = parsed
    return _rating_mappings_cache


def normalize_rating(raw_rating: Optional[str]) -> Rating:
    """
    Normalize any raw fact-checker rating text (e.g. 'Pants on Fire!', 'Mostly False',
    'भ्रामक दावा') into a canonical Rating enum.
    Returns Rating.UNVERIFIED if unclassifiable or empty.
    """
    if not raw_rating or not raw_rating.strip():
        return Rating.UNVERIFIED

    cleaned = raw_rating.lower().strip()
    cleaned = re.sub(r"[^\w\s\u0900-\u097F]", "", cleaned).strip()

    mappings = load_rating_mappings()

    # Flatten and sort candidate phrases by length descending
    # This ensures "mostly false" matches PARTLY_TRUE before "false" matches FALSE
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
