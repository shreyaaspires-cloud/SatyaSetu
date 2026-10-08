"""
Unit acceptance tests for T14: Verified Claim Bank (AT32, AT33, AT34).
"""

from datetime import date, timedelta
import pytest
from app.core.constants import Verdict
from app.features.verification.claim_bank import lookup_claim_bank, load_claim_bank


def test_at32_bank_claim_returns_verdict_with_source_cited():
    """
    AT32: A bank claim returns its verdict with its source cited.
    """
    query = "Drinking bleach cures viral infections within 24 hours"
    match = lookup_claim_bank(query)
    assert match is not None, "Expected hit in claim bank for drinking bleach claim"
    assert match.verdict == Verdict.REFUTED or match.verdict == Verdict.MISLEADING
    assert match.source_url is not None and "http" in match.source_url
    assert match.publisher is not None and len(match.publisher) > 0
    assert "fact check" in match.citation.lower() or match.publisher.lower() in match.citation.lower()


def test_at33_key_detail_changed_does_not_return_bank_verdict():
    """
    AT33: Same claim with one key detail changed does not return the bank verdict.
    If the bank has 'head north', querying 'head east' must NOT return the bank verdict.
    """
    # Canonical in bank relates to sleeping with head north
    query_conflict = "Sleeping with head east causes severe blood flow issues"
    match = lookup_claim_bank(query_conflict)
    # Must not match as a decisive verdict hit because of east vs north conflict
    assert match is None or match.is_decisive is False


def test_at34_expired_entry_is_not_used():
    """
    AT34: An expired (review_by passed) entry is not used.
    """
    # Query corresponding to an expired test entry
    query_expired = "Old test claim that expired yesterday"
    match = lookup_claim_bank(query_expired)
    assert match is None, "Expired entry must not be returned as a valid hit"
