"""
Acceptance tests for T13: Official source search with topic routing (AT30, AT31).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from app.contracts.models import EvidenceItem
from app.core.constants import Rating, Tier, Verdict
from app.features.retrieval.official_search import (
    passes_detail_check,
    passes_relevance_gate,
    route_claim_topic,
    search_official_sources,
)
from app.features.verification.stance import aggregate_verdict


class TestT13Acceptance:
    def test_at30_banking_claim_triggers_domain_restricted_search(self):
        """AT30: A banking claim triggers searches restricted to rbi.org.in, npci.org.in, and cert-in.org.in."""
        banking_claim = "RBI has announced new UPI payment limits for all banks"
        topic, domains = route_claim_topic(banking_claim)

        assert topic == "banking"
        assert "rbi.org.in" in domains
        assert "npci.org.in" in domains
        assert "cert-in.org.in" in domains

        # When searching with Brave provider, query includes site: restrictions
        with patch("app.features.retrieval.search_web._search_brave", return_value=[]) as mock_brave:
            with patch("app.core.config.settings.search_api_key", "mock_key"):
                with patch("app.core.config.settings.search_provider", "brave"):
                    search_official_sources(banking_claim, domains=domains, provider="brave")
                    assert mock_brave.called
                    query = mock_brave.call_args[0][0]
                    assert "rbi.org.in" in query
                    assert "npci.org.in" in query
                    assert "cert-in.org.in" in query

    def test_at31_official_results_failing_detail_check_do_not_decide_verdict(self):
        """AT31: Official results that fail the T2 detail check do not decide a verdict."""
        claim = "Government is giving free laptops under PM Youth Scheme 2026"

        # Item from official domain (Tier 2) but has generic snippet with no matching details
        vague_official_item = EvidenceItem(
            url="https://pib.gov.in/homepage",
            title="Press Information Bureau Home",
            snippet="Welcome to PIB. Government of India press releases and announcements.",
            source_domain="pib.gov.in",
            tier=Tier.TIER_2_GOV_PIB,
            rating=Rating.TRUE,  # would otherwise mark SUPPORTED if not checked
            score=0.4,
        )

        # Fails detail check
        assert not passes_detail_check(claim, f"{vague_official_item.title} {vague_official_item.snippet}")

        # Verdict must NOT be decided by this vague official item
        verdict, conf, reason = aggregate_verdict(claim, [vague_official_item])
        assert verdict != Verdict.SUPPORTED
        assert reason != "AUTHORITATIVE_FACT_CHECK"
        assert verdict == Verdict.UNVERIFIABLE
