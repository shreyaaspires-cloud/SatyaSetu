"""
Unit tests for evidence retrieval: domain classification, Google Fact Check,
Wikipedia, and orchestrator parallel execution and deduplication.
"""

from unittest.mock import MagicMock, patch

from app.contracts.models import EvidenceItem
from app.core.config import settings
from app.core.constants import Rating, Tier
from app.features.retrieval.factcheck_google import search_google_fact_check
from app.features.retrieval.orchestrator import normalize_url_for_dedupe, retrieve_evidence
from app.features.retrieval.sources import classify_domain
from app.features.retrieval.wikipedia import search_wikipedia


def test_classify_domain():
    assert classify_domain("https://www.altnews.in/fact-check-lemon") == Tier.TIER_1_IFCN
    assert classify_domain("https://boomlive.in/fake-news") == Tier.TIER_1_IFCN
    assert classify_domain("https://pib.gov.in/PressRelease.aspx") == Tier.TIER_2_GOV_PIB
    assert classify_domain("https://who.int/news/item") == Tier.TIER_2_GOV_PIB
    assert classify_domain("https://thehindu.com/news/national") == Tier.TIER_3_MAINSTREAM
    assert classify_domain("https://en.wikipedia.org/wiki/COVID-19") == Tier.TIER_4_WIKIPEDIA
    assert classify_domain("https://random-unverified-blog.org/post") == Tier.TIER_5_GENERAL_WEB


def test_normalize_url_for_dedupe():
    url1 = "https://www.example.com/article/"
    url2 = "http://example.com/article"
    assert normalize_url_for_dedupe(url1) == normalize_url_for_dedupe(url2)


def test_google_fact_check_parsing():
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
                            "url": "https://www.altnews.in/claim-checked",
                            "title": "False claim about lemon water",
                            "textualRating": "False",
                            "reviewDate": "2024-01-15",
                        }
                    ],
                }
            ]
        }

        with patch("app.features.retrieval.factcheck_google._fetch_google_fact_check", return_value=mock_data):
            results = search_google_fact_check("lemon water cancer")
            assert len(results) == 1
            item = results[0]
            assert item.tier == Tier.TIER_1_IFCN
            assert item.rating == Rating.FALSE
            assert item.source_domain == "altnews.in"
            assert "Alt News" in item.snippet
    finally:
        settings.google_fact_check_api_key = orig_key


def test_wikipedia_retrieval_parsing():
    with patch("app.features.retrieval.wikipedia.safe_get") as mock_get:
        # Mock search response
        mock_search_resp = MagicMock()
        mock_search_resp.status_code = 200
        mock_search_resp.json.return_value = {
            "query": {"search": [{"title": "Lemon"}]}
        }

        # Mock summary response
        mock_summary_resp = MagicMock()
        mock_summary_resp.status_code = 200
        mock_summary_resp.json.return_value = {
            "extract": "The lemon is a species of small evergreen tree.",
            "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Lemon"}},
        }

        mock_get.side_effect = [mock_search_resp, mock_summary_resp]

        results = search_wikipedia("lemon")
        assert len(results) == 1
        item = results[0]
        assert item.tier == Tier.TIER_4_WIKIPEDIA
        assert item.rating == Rating.UNVERIFIED
        assert "Wikipedia: Lemon" in item.title


def test_orchestrator_parallel_dedupe_and_sorting():
    item_tier1 = EvidenceItem(
        url="https://altnews.in/fact-check",
        title="Alt News Check",
        snippet="Debunked as false.",
        source_domain="altnews.in",
        tier=Tier.TIER_1_IFCN,
        rating=Rating.FALSE,
        score=0.95,
    )

    item_duplicate_tier1 = EvidenceItem(
        url="https://www.altnews.in/fact-check/",
        title="Alt News Check Duplicate",
        snippet="Duplicate snippet.",
        source_domain="altnews.in",
        tier=Tier.TIER_1_IFCN,
        rating=Rating.FALSE,
        score=0.90,
    )

    item_tier4 = EvidenceItem(
        url="https://en.wikipedia.org/wiki/Claim",
        title="Wikipedia context",
        snippet="Encyclopedic information.",
        source_domain="en.wikipedia.org",
        tier=Tier.TIER_4_WIKIPEDIA,
        rating=Rating.UNVERIFIED,
        score=0.70,
    )

    with patch("app.features.retrieval.orchestrator.search_google_fact_check", return_value=[item_tier1, item_duplicate_tier1]):
        with patch("app.features.retrieval.orchestrator.search_wikipedia", return_value=[item_tier4]):
            with patch("app.features.retrieval.orchestrator.search_web", return_value=[]):
                evidence = retrieve_evidence("Sample claim", budget_ms=1000)

                # Deduplication check: only one altnews.in item should exist
                assert len(evidence) == 2
                # Sorting check: Tier 1 IFCN must be first, followed by Tier 4 Wikipedia
                assert evidence[0].tier == Tier.TIER_1_IFCN
                assert evidence[1].tier == Tier.TIER_4_WIKIPEDIA
