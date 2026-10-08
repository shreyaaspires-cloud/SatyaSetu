"""
Unit acceptance tests for T12: Source Configuration (AT29).

Validates that every required official domain and general category
classifies to its expected tier per config/sources.yaml.
"""

import pytest
from app.core.constants import Tier
from app.features.retrieval.sources import classify_domain


def test_at29_source_tiers_classification():
    """
    AT29: Every listed domain classifies to the correct tier in a unit test.
    Specifically checks the 12 required official Tier 2 domains,
    as well as representative Tier 1, Tier 3, Tier 4, and Tier 5 domains.
    """
    # Tier 2 Official Domains (per T12 specification)
    tier_2_domains = [
        "pib.gov.in",
        "mygov.in",
        "mohfw.gov.in",
        "icmr.gov.in",
        "who.int",
        "rbi.org.in",
        "npci.org.in",
        "cert-in.org.in",
        "sebi.gov.in",
        "uidai.gov.in",
        "india.gov.in",
        "incometax.gov.in",
        "incometaxindia.gov.in",
    ]

    for domain in tier_2_domains:
        url = f"https://{domain}/updates/article"
        assert classify_domain(url) == Tier.TIER_2_GOV_PIB, (
            f"Expected {domain} to be Tier 2, got {classify_domain(url)}"
        )

    # Tier 1 IFCN Fact Checkers
    tier_1_domains = [
        "altnews.in",
        "boomlive.in",
        "factly.in",
        "thequint.com",
        "vishvasnews.com",
        "newschecker.in",
        "snopes.com",
    ]
    for domain in tier_1_domains:
        url = f"https://{domain}/fact-check/story"
        assert classify_domain(url) == Tier.TIER_1_IFCN, (
            f"Expected {domain} to be Tier 1, got {classify_domain(url)}"
        )

    # Tier 3 Mainstream News
    tier_3_domains = [
        "thehindu.com",
        "indianexpress.com",
        "bbc.com",
        "ndtv.com",
    ]
    for domain in tier_3_domains:
        url = f"https://{domain}/news/national"
        assert classify_domain(url) == Tier.TIER_3_MAINSTREAM, (
            f"Expected {domain} to be Tier 3, got {classify_domain(url)}"
        )

    # Tier 4 Wikipedia
    assert classify_domain("https://en.wikipedia.org/wiki/India") == Tier.TIER_4_WIKIPEDIA
    assert classify_domain("https://wikipedia.org/wiki/Portal") == Tier.TIER_4_WIKIPEDIA

    # Tier 5 General Web / Unlisted
    assert classify_domain("https://some-random-blog.xyz/post") == Tier.TIER_5_GENERAL_WEB
