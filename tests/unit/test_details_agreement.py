"""
Unit acceptance tests for T2: Key Detail Agreement Check (AT3, AT4, AT5).
"""

from app.contracts.models import EvidenceItem
from app.core.constants import Rating, Tier
from app.features.verification.stance import score_stance


def test_at3_direction_mismatch_yields_detail_mismatch():
    """
    AT3: Claim "head east causes bad blood flow" against a snippet about "head north"
    -> DETAIL_MISMATCH, no SUPPORTED or REFUTED.
    """
    claim = "sleeping with head east causes bad blood flow"
    evidence_items = [
        EvidenceItem(
            url="https://healthline.com/sleeping-direction",
            title="Sleeping direction study",
            snippet="Research shows sleeping with head north may influence magnetic fields and blood circulation.",
            source_domain="healthline.com",
            tier=Tier.TIER_3_MAINSTREAM,
            rating=Rating.UNVERIFIED,
            score=0.8,
        )
    ]

    scored = score_stance(claim, evidence_items)
    item = scored[0]

    assert item.stance == "NEUTRAL"
    assert getattr(item, "reason", None) == "DETAIL_MISMATCH"


def test_at4_negation_yields_opposite_polarity_not_mismatch():
    """
    AT4: "UPI charges of 2 percent" against a source saying the claim is false and
    there are no such charges → opposite polarity, NOT a detail mismatch.

    "2 percent" appears on BOTH sides (same value), so check_detail_conflict must
    return None. The stance scorer should then return REFUTES due to the refute
    signal in the snippet.

    NLI and Gemini are mocked out so the lexical fallback is used deterministically.
    """
    from unittest.mock import patch as _patch

    claim = "NPCI imposes UPI charges of 2 percent on all payments"
    evidence_items = [
        EvidenceItem(
            url="https://npci.org.in/press-release",
            title="NPCI Clarification on UPI Fees",
            snippet=(
                "NPCI clarified that claims of 2 percent UPI charges are false. "
                "No such fees are imposed on normal UPI payments to merchants."
            ),
            source_domain="npci.org.in",
            tier=Tier.TIER_2_GOV_PIB,
            rating=Rating.UNVERIFIED,
            score=0.9,
        )
    ]

    # Force lexical fallback so the test is deterministic regardless of NLI cache state
    with _patch("app.features.verification.stance._load_nli_model", return_value=None), \
         _patch("app.features.verification.stance._gemini_stance_batch", return_value=False):
        scored = score_stance(claim, evidence_items)

    item = scored[0]

    # "2 percent" shared → NOT a detail mismatch
    assert getattr(item, "reason", None) != "DETAIL_MISMATCH"
    # Negation flip detected → REFUTES
    assert item.stance == "REFUTES"


def test_at5_currency_amount_conflict_yields_detail_mismatch():
    """
    AT5: "Rs 500" claim against a source saying "Rs 5000"
    -> DETAIL_MISMATCH, item cannot support or refute.
    """
    claim = "RBI will discontinue Rs 500 notes next week"
    evidence_items = [
        EvidenceItem(
            url="https://rbi.org.in/notifications",
            title="RBI Notification",
            snippet="Old commemorative Rs 5000 notes are discontinued from circulation.",
            source_domain="rbi.org.in",
            tier=Tier.TIER_2_GOV_PIB,
            rating=Rating.UNVERIFIED,
            score=0.85,
        )
    ]

    scored = score_stance(claim, evidence_items)
    item = scored[0]

    assert item.stance == "NEUTRAL"
    assert getattr(item, "reason", None) == "DETAIL_MISMATCH"
