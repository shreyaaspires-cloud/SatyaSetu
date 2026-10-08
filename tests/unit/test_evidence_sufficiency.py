"""
Unit acceptance tests for T3: Evidence Sufficiency in the Aggregator (AT6–AT9).

All tests mock score_stance to inject pre-scored evidence directly into
aggregate_verdict, bypassing NLI/Gemini so results are deterministic.
"""

from unittest.mock import patch as _patch

from app.contracts.models import EvidenceItem
from app.core.constants import Rating, Tier, Verdict
from app.features.verification.stance import aggregate_verdict


# ---------------------------------------------------------------------------
# Helpers to build pre-scored EvidenceItem objects
# ---------------------------------------------------------------------------

def _make_item(
    url: str,
    source_domain: str,
    tier: Tier,
    rating: Rating,
    stance: str,
    score: float,
    reason: str | None = None,
) -> EvidenceItem:
    return EvidenceItem(
        url=url,
        title=f"Article from {source_domain}",
        snippet="Some fact-check snippet.",
        source_domain=source_domain,
        tier=tier,
        rating=rating,
        score=score,
        stance=stance,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# AT6 — Unrelated Tier 1 FALSE does not override Tier 1 TRUE
# ---------------------------------------------------------------------------

def test_at6_unrelated_false_does_not_override_true():
    """
    AT6: A Tier-1 item that failed the relevance gate (demoted to Tier 5 /
    stance NEUTRAL / reason RELATED_NOT_SAME) must NOT trigger REFUTED
    when a genuine Tier-1 TRUE item is present.
    """
    # Item from unrelated fact check — already demoted by T1 relevance gate
    unrelated_false = _make_item(
        url="https://altnews.in/vaccine-chips",
        source_domain="altnews.in",
        tier=Tier.TIER_5_GENERAL_WEB,   # demoted
        rating=Rating.FALSE,
        stance="NEUTRAL",
        score=0.1,
        reason="RELATED_NOT_SAME",
    )
    # Genuine Tier-1 TRUE item for the actual moon claim
    related_true = _make_item(
        url="https://boomlive.in/moon-landing-real",
        source_domain="boomlive.in",
        tier=Tier.TIER_1_IFCN,
        rating=Rating.TRUE,
        stance="SUPPORTS",
        score=0.85,
    )

    verdict, conf, reason = aggregate_verdict(
        claim="The moon landing actually happened",
        evidence_items=[unrelated_false, related_true],
    )

    assert verdict != Verdict.REFUTED, (
        f"Got {verdict} — unrelated demoted FALSE must not drive REFUTED"
    )


# ---------------------------------------------------------------------------
# AT7 — Single Wikipedia snippet → UNVERIFIABLE
# ---------------------------------------------------------------------------

def test_at7_single_wikipedia_support_is_unverifiable():
    """
    AT7: A single Tier-4 (Wikipedia) item that SUPPORTS must yield UNVERIFIABLE,
    not SUPPORTED. Wikipedia alone is never decisive.
    """
    wiki_support = _make_item(
        url="https://en.wikipedia.org/wiki/Moon_landing",
        source_domain="en.wikipedia.org",
        tier=Tier.TIER_4_WIKIPEDIA,
        rating=Rating.UNVERIFIED,
        stance="SUPPORTS",
        score=0.75,
    )

    verdict, conf, reason = aggregate_verdict(
        claim="The moon landing happened in 1969",
        evidence_items=[wiki_support],
    )

    assert verdict == Verdict.UNVERIFIABLE, (
        f"Got {verdict} — single Wikipedia SUPPORTS must yield UNVERIFIABLE"
    )


# ---------------------------------------------------------------------------
# AT8 — Two Tier-3 sources from different domains → SUPPORTED
# ---------------------------------------------------------------------------

def test_at8_two_tier3_different_domains_yields_supported():
    """
    AT8: Two independent Tier-3 mainstream sources that both SUPPORT the claim,
    from different domains, must yield SUPPORTED.
    """
    item_a = _make_item(
        url="https://thehindu.com/moon-landing-confirmed",
        source_domain="thehindu.com",
        tier=Tier.TIER_3_MAINSTREAM,
        rating=Rating.UNVERIFIED,
        stance="SUPPORTS",
        score=0.80,
    )
    item_b = _make_item(
        url="https://ndtv.com/moon-landing-real",
        source_domain="ndtv.com",
        tier=Tier.TIER_3_MAINSTREAM,
        rating=Rating.UNVERIFIED,
        stance="SUPPORTS",
        score=0.78,
    )

    verdict, conf, reason = aggregate_verdict(
        claim="The moon landing happened in 1969",
        evidence_items=[item_a, item_b],
    )

    assert verdict == Verdict.SUPPORTED, (
        f"Got {verdict} — two independent Tier-3 supports must yield SUPPORTED"
    )


# ---------------------------------------------------------------------------
# AT9 — Tier-3 support + Tier-3 refute → UNVERIFIABLE (CONFLICTING_EVIDENCE)
# ---------------------------------------------------------------------------

def test_at9_conflicting_tier3_yields_unverifiable():
    """
    AT9: One Tier-3 item SUPPORTS, one Tier-3 item REFUTES.
    Must yield UNVERIFIABLE with reason CONFLICTING_EVIDENCE.
    """
    item_support = _make_item(
        url="https://thehindu.com/support-claim",
        source_domain="thehindu.com",
        tier=Tier.TIER_3_MAINSTREAM,
        rating=Rating.UNVERIFIED,
        stance="SUPPORTS",
        score=0.70,
    )
    item_refute = _make_item(
        url="https://ndtv.com/refute-claim",
        source_domain="ndtv.com",
        tier=Tier.TIER_3_MAINSTREAM,
        rating=Rating.UNVERIFIED,
        stance="REFUTES",
        score=0.72,
    )

    verdict, conf, reason = aggregate_verdict(
        claim="Some contested claim",
        evidence_items=[item_support, item_refute],
    )

    assert verdict == Verdict.UNVERIFIABLE, (
        f"Got {verdict} — conflicting Tier-3 evidence must yield UNVERIFIABLE"
    )
    assert reason == "CONFLICTING_EVIDENCE", (
        f"Got reason={reason} — expected CONFLICTING_EVIDENCE"
    )
