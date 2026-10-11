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
    Uses fixture from tests/fixtures/claim_bank_fixtures.yaml.
    """
    import yaml
    from pathlib import Path
    from unittest.mock import patch

    fixture_path = Path(__file__).resolve().parent.parent / "fixtures" / "claim_bank_fixtures.yaml"
    with open(fixture_path, "r", encoding="utf-8") as f:
        fixtures = yaml.safe_load(f)

    # Fixture contains cb-004 which expired in 2024
    with patch("app.features.verification.claim_bank.load_claim_bank", return_value=fixtures):
        match = lookup_claim_bank("Old test claim that expired yesterday")
        assert match is None, "Expired entry must not be returned as a valid hit"


def test_validate_claim_bank_entry_rejection():
    """
    Verify validate_claim_bank_entry rejects expired or unsourced entries.
    """
    from app.features.verification.claim_bank import validate_claim_bank_entry

    # Valid entry
    valid_entry = {
        "id": "cb-valid",
        "canonical_claim": "A valid claim",
        "review_by": "2030-01-01",
        "sources": [{"url": "https://example.com", "publisher": "FactCheck"}],
    }
    assert validate_claim_bank_entry(valid_entry) is True

    # Expired entry
    expired_entry = {
        "id": "cb-expired",
        "canonical_claim": "An expired claim",
        "review_by": "2020-01-01",
        "sources": [{"url": "https://example.com", "publisher": "FactCheck"}],
    }
    assert validate_claim_bank_entry(expired_entry) is False

    # Missing sources
    unsourced_entry = {
        "id": "cb-unsourced",
        "canonical_claim": "An unsourced claim",
        "review_by": "2030-01-01",
        "sources": [],
    }
    assert validate_claim_bank_entry(unsourced_entry) is False

    # Source without url or publisher
    invalid_source_entry = {
        "id": "cb-invalid-source",
        "canonical_claim": "Claim with bad source",
        "review_by": "2030-01-01",
        "sources": [{"url": "", "publisher": ""}],
    }
    assert validate_claim_bank_entry(invalid_source_entry) is False


def test_living_person_claim_is_not_decisive():
    from app.features.verification.claim_bank import lookup_claim_bank
    from unittest.mock import patch
    mock_entry = [{
        "id": "cb-test-living",
        "canonical_claim": "Living actor is no more in this world",
        "variants": ["Living actor passed away today"],
        "verdict": "REFUTED",
        "explanation_en": "Alive and well.",
        "claim_type": "living_person_status",
        "sources": [{"publisher": "BOOM", "url": "https://example.com"}],
        "category": "celebrity_hoax",
        "last_reviewed": "2026-01-01",
        "review_by": "2027-01-01",
    }]
    with patch("app.features.verification.claim_bank.load_claim_bank", return_value=mock_entry):
        result = lookup_claim_bank("Living actor passed away today")
        assert result is not None
        assert not result.is_decisive

