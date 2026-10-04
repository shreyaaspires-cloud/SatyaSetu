"""
Unit tests for rating string normalization.
Verifies coverage of 30+ multilingual rating strings across Tier 1 fact checkers.
"""

import pytest

from app.core.constants import Rating
from app.features.retrieval.ratings import normalize_rating

FALSE_RATINGS = [
    "False",
    "fake",
    "INCORRECT",
    "Fabricated claim",
    "Hoax",
    "Untrue",
    "Debunked",
    "Pants on Fire!",
    "Scam",
    "Doctored image",
    "Manipulated media",
    "Misattributed quote",
    "गलत",
    "झूठ",
    "फेक",
    "अफवाह",
]

MISLEADING_RATINGS = [
    "Misleading",
    "Out of Context",
    "Missing context",
    "Altered video",
    "भ्रामक",
    "संदर्भहीन",
]

PARTLY_TRUE_RATINGS = [
    "Partly true",
    "Partially true",
    "Half true",
    "Mixed verdict",
    "Mostly false",
    "Mostly true",
    "अंशतः सत्य",
    "आधा सच",
]

TRUE_RATINGS = [
    "True",
    "Correct",
    "Accurate",
    "Verified",
    "Confirmed",
    "सत्य",
    "सही",
    "पुष्ट",
]


@pytest.mark.parametrize("raw_rating", FALSE_RATINGS)
def test_normalize_false_ratings(raw_rating):
    assert normalize_rating(raw_rating) == Rating.FALSE


@pytest.mark.parametrize("raw_rating", MISLEADING_RATINGS)
def test_normalize_misleading_ratings(raw_rating):
    assert normalize_rating(raw_rating) == Rating.MISLEADING


@pytest.mark.parametrize("raw_rating", PARTLY_TRUE_RATINGS)
def test_normalize_partly_true_ratings(raw_rating):
    assert normalize_rating(raw_rating) == Rating.PARTLY_TRUE


@pytest.mark.parametrize("raw_rating", TRUE_RATINGS)
def test_normalize_true_ratings(raw_rating):
    assert normalize_rating(raw_rating) == Rating.TRUE


def test_normalize_unknown_or_empty_ratings():
    assert normalize_rating("") == Rating.UNVERIFIED
    assert normalize_rating(None) == Rating.UNVERIFIED
    assert normalize_rating("Random uncalibrated observation") == Rating.UNVERIFIED
