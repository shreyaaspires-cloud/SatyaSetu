"""
Unit tests for Wave 6: Verification — stance scoring and verdict aggregation.
All tests run without network access (evidence items are constructed in-process).
"""

from __future__ import annotations

import pytest

from app.contracts.models import EvidenceItem
from app.core.constants import Rating, Tier, Verdict
from app.features.verification.stance import aggregate_verdict, score_stance
from app.features.verification.service import verify_claim, batch_verify_claims


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_item(
    url: str = "https://example.com",
    title: str = "Test",
    snippet: str = "The sky is blue.",
    domain: str = "example.com",
    tier: Tier = Tier.TIER_5_GENERAL_WEB,
    rating: Rating = Rating.UNVERIFIED,
    score: float = 0.5,
    stance: str | None = None,
) -> EvidenceItem:
    return EvidenceItem(
        url=url,
        title=title,
        snippet=snippet,
        source_domain=domain,
        tier=tier,
        rating=rating,
        score=score,
        stance=stance,
    )


# ── score_stance ───────────────────────────────────────────────────────────────

class TestScoreStance:
    def test_empty_claim_returns_unchanged(self):
        items = [_make_item()]
        result = score_stance("", items)
        # Should return items unchanged
        assert result == items

    def test_empty_items_returns_empty(self):
        result = score_stance("The earth is round", [])
        assert result == []

    def test_sets_stance_field(self):
        """Stance field must be populated even on lexical fallback."""
        items = [_make_item(snippet="The earth is indeed a sphere.")]
        result = score_stance("The earth is round", items)
        assert result[0].stance in ("SUPPORTS", "REFUTES", "NEUTRAL")

    def test_score_bounded_0_1(self):
        """Score must be in [0, 1] after stance scoring."""
        items = [_make_item(snippet="Completely unrelated text about apples.")]
        result = score_stance("vaccines cause autism", items)
        assert 0.0 <= result[0].score <= 1.0


# ── aggregate_verdict ─────────────────────────────────────────────────────────

class TestAggregateVerdict:
    def test_empty_evidence_returns_unverifiable(self):
        verdict, conf, code = aggregate_verdict("any claim", [])
        assert verdict == Verdict.UNVERIFIABLE
        assert conf == 0.0
        assert code == "NO_EVIDENCE"

    def test_tier1_false_rating_gives_refuted(self):
        item = _make_item(
            tier=Tier.TIER_1_IFCN,
            rating=Rating.FALSE,
            score=0.9,
        )
        item.stance = "REFUTES"
        verdict, conf, code = aggregate_verdict("claim", [item])
        assert verdict == Verdict.REFUTED
        assert code == "AUTHORITATIVE_FACT_CHECK"
        assert 0.0 < conf <= 1.0

    def test_tier1_true_rating_gives_supported(self):
        item = _make_item(
            tier=Tier.TIER_1_IFCN,
            rating=Rating.TRUE,
            score=0.95,
        )
        item.stance = "SUPPORTS"
        verdict, conf, code = aggregate_verdict("claim", [item])
        assert verdict == Verdict.SUPPORTED
        assert code == "AUTHORITATIVE_FACT_CHECK"

    def test_tier2_partly_true_gives_partially_supported(self):
        item = _make_item(
            tier=Tier.TIER_2_GOV_PIB,
            rating=Rating.PARTLY_TRUE,
            score=0.8,
        )
        item.stance = "NEUTRAL"
        verdict, conf, code = aggregate_verdict("claim", [item])
        assert verdict == Verdict.PARTIALLY_SUPPORTED

    def test_majority_supports_gives_supported(self):
        """Three SUPPORTS items from web should tip toward SUPPORTED."""
        items = [
            _make_item(tier=Tier.TIER_5_GENERAL_WEB, score=0.7, stance="SUPPORTS"),
            _make_item(tier=Tier.TIER_5_GENERAL_WEB, score=0.8, stance="SUPPORTS"),
            _make_item(tier=Tier.TIER_5_GENERAL_WEB, score=0.6, stance="NEUTRAL"),
        ]
        verdict, conf, code = aggregate_verdict("claim", items)
        assert verdict in (Verdict.SUPPORTED, Verdict.UNVERIFIABLE)

    def test_verdict_confidence_bounded(self):
        items = [_make_item(score=0.5, stance="SUPPORTS")]
        _, conf, _ = aggregate_verdict("claim", items)
        assert 0.0 <= conf <= 1.0


# ── verify_claim ──────────────────────────────────────────────────────────────

class TestVerifyClaim:
    def test_empty_claim_returns_unverifiable(self):
        result = verify_claim("")
        assert result.verdict == Verdict.UNVERIFIABLE
        assert result.reason_code == "EMPTY_CLAIM"
        assert result.claim == ""
        assert result.guard_passed is True

    def test_whitespace_claim_returns_unverifiable(self):
        result = verify_claim("   ")
        assert result.verdict == Verdict.UNVERIFIABLE

    def test_claim_result_has_required_fields(self):
        """verify_claim must always return a ClaimResult — even on network failure."""
        result = verify_claim("The moon is made of cheese.", budget_ms=100)
        assert hasattr(result, "verdict")
        assert hasattr(result, "confidence")
        assert hasattr(result, "reason_code")
        assert isinstance(result.evidence, list)
        assert 0.0 <= result.confidence <= 1.0

    def test_confidence_bounded(self):
        result = verify_claim("test claim for confidence bounds", budget_ms=100)
        assert 0.0 <= result.confidence <= 1.0


# ── batch_verify_claims ────────────────────────────────────────────────────────

class TestBatchVerifyClaims:
    def test_empty_list_returns_empty(self):
        results = batch_verify_claims([])
        assert results == []

    def test_same_count_as_input(self):
        claims = ["claim one", "claim two", "claim three"]
        results = batch_verify_claims(claims, budget_ms=300)
        assert len(results) == 3

    def test_each_result_is_claim_result(self):
        from app.contracts.models import ClaimResult
        results = batch_verify_claims(["hello", "world"], budget_ms=200)
        for r in results:
            assert isinstance(r, ClaimResult)


# ── Acceptance Tests: T4 (AT10, AT11, AT12) ──────────────────────────────────

class TestT4Acceptance:
    def test_at10_partly_true_rating_yields_partially_supported(self):
        """AT10: A fact check rating of 'partly true' yields PARTIALLY_SUPPORTED."""
        from app.features.retrieval.ratings import normalize_rating
        rating = normalize_rating("partly true")
        item = _make_item(
            tier=Tier.TIER_1_IFCN,
            rating=rating,
            score=0.85,
        )
        verdict, conf, code = aggregate_verdict("Claim under test", [item])
        assert verdict == Verdict.PARTIALLY_SUPPORTED

    def test_at11_old_video_rating_yields_outdated(self):
        """AT11: A rating of 'old video, not from this year' yields OUTDATED."""
        from app.features.retrieval.ratings import normalize_rating
        rating = normalize_rating("old video, not from this year")
        item = _make_item(
            tier=Tier.TIER_1_IFCN,
            rating=rating,
            score=0.85,
        )
        verdict, conf, code = aggregate_verdict("Viral video claim", [item])
        assert verdict == Verdict.OUTDATED

    def test_at12_tier2_snippet_withdrawn_yields_outdated(self):
        """AT12: A Tier 2 snippet saying a notice was withdrawn yields OUTDATED."""
        item = _make_item(
            tier=Tier.TIER_2_GOV_PIB,
            title="Press Information Bureau Notice",
            snippet="The public notice regarding the mandatory exam requirement has been withdrawn by the department.",
            score=0.8,
        )
        verdict, conf, code = aggregate_verdict("Mandatory exam requirement notice", [item])
        assert verdict == Verdict.OUTDATED

