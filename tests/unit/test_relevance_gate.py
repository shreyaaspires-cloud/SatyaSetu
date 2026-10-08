"""
Unit acceptance tests for T1: Relevance Gate for Fact Check Matches (AT1, AT2).
"""

from unittest.mock import patch
from app.core.config import settings
from app.core.constants import Rating, Tier
from app.features.retrieval.factcheck_google import search_google_fact_check


def test_at1_unrelated_fact_check_demoted():
    """
    AT1: An unrelated fact check about vaccines does not pass relevance gate
    for a claim about the moon.
    Must be demoted: Tier 5, score <= 0.3, stance NEUTRAL with reason RELATED_NOT_SAME.
    """
    orig_key = settings.google_fact_check_api_key
    try:
        settings.google_fact_check_api_key = "mock_key"
        mock_data = {
            "claims": [
                {
                    "text": "COVID-19 vaccines contain microchips and alter DNA",
                    "claimReview": [
                        {
                            "publisher": {"name": "Alt News"},
                            "url": "https://www.altnews.in/vaccine-microchips-false",
                            "title": "Debunked: Vaccines do not contain chips",
                            "textualRating": "False",
                            "reviewDate": "2024-01-15",
                        }
                    ],
                }
            ]
        }

        with patch("app.features.retrieval.factcheck_google._fetch_google_fact_check", return_value=mock_data):
            results = search_google_fact_check("The moon landing was staged and faked in a movie studio")
            assert len(results) == 1
            item = results[0]

            # Check new fields
            assert hasattr(item, "matched_claim")
            assert item.matched_claim == "COVID-19 vaccines contain microchips and alter DNA"
            assert hasattr(item, "match_score")
            assert item.match_score < 0.6

            # Check demotion below threshold
            assert item.tier == Tier.TIER_5_GENERAL_WEB
            assert item.score <= 0.3
            assert item.stance == "NEUTRAL"
            assert getattr(item, "reason", None) == "RELATED_NOT_SAME"
    finally:
        settings.google_fact_check_api_key = orig_key


def test_at2_near_duplicate_fact_check_passes_gate():
    """
    AT2: A near-duplicate fact check (same topic, same details) passes the relevance gate.
    Tier is preserved from classify_domain and score reflects relevance.
    """
    orig_key = settings.google_fact_check_api_key
    try:
        settings.google_fact_check_api_key = "mock_key"
        mock_data = {
            "claims": [
                {
                    "text": "Drinking lemon water cures cancer",
                    "claimReview": [
                        {
                            "publisher": {"name": "Alt News"},
                            "url": "https://www.altnews.in/lemon-water-cancer-check",
                            "title": "False claim about lemon water curing cancer",
                            "textualRating": "False",
                            "reviewDate": "2024-01-15",
                        }
                    ],
                }
            ]
        }

        with patch("app.features.retrieval.factcheck_google._fetch_google_fact_check", return_value=mock_data):
            results = search_google_fact_check("Drinking warm lemon water cures cancer completely")
            assert len(results) == 1
            item = results[0]

            # Check new fields and score
            assert hasattr(item, "matched_claim")
            assert item.matched_claim == "Drinking lemon water cures cancer"
            assert hasattr(item, "match_score")
            assert item.match_score >= 0.6

            # Gate passed: Tier 1 preserved, stance not forced to NEUTRAL
            assert item.tier == Tier.TIER_1_IFCN
            assert item.rating == Rating.FALSE
            assert getattr(item, "reason", None) != "RELATED_NOT_SAME"
    finally:
        settings.google_fact_check_api_key = orig_key
