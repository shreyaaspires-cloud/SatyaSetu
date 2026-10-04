"""
Unit tests for app.contracts and app.core modules.
Verifies contract validation (good and bad instances), redaction, logging filter,
StageTimer, constants, and settings loading.
"""

import logging
import re
import time
import pytest
from pydantic import ValidationError

from app.contracts.models import (
    CheckResponse,
    ClaimResult,
    EvidenceItem,
    IngestedMessage,
    NLPResult,
    WebhookPayload,
)
from app.core.config import settings
from app.core.constants import InputType, Rating, Tier, Verdict
from app.core.logging import RedactionFilter, configure_logging, request_id_var
from app.core.redaction import hash_identifier, redact
from app.core.timing import StageTimer


# ── Contracts Unit Tests (Good & Bad Instances) ──────────────────────────────


def test_ingested_message_contract():
    # Good instance
    good = IngestedMessage(
        raw_text="Test claim text",
        input_type=InputType.TEXT,
        from_number="a" * 64,
        original_body="Test claim text",
    )
    assert good.raw_text == "Test claim text"
    assert good.input_type == InputType.TEXT

    # Bad instance (missing required raw_text or invalid input_type)
    with pytest.raises(ValidationError):
        IngestedMessage(
            raw_text="Test",
            input_type="invalid_input_type",  # type: ignore
            from_number="a" * 64,
        )


def test_nlp_result_contract():
    # Good instance
    good = NLPResult(
        detected_language="hi",
        language_confidence=0.98,
        translated_text="Sample translated text",
        claims=["Claim 1"],
        check_worthiness_score=0.85,
        has_forward_pressure=True,
        keywords=["sample", "claim"],
    )
    assert good.detected_language == "hi"
    assert good.has_forward_pressure is True

    # Bad instance (missing required fields like detected_language or language_confidence)
    with pytest.raises(ValidationError):
        NLPResult(
            detected_language="hi",
            # missing language_confidence and translated_text
        )  # type: ignore


def test_evidence_item_contract():
    # Good instance
    good = EvidenceItem(
        url="https://factcheck.org/story",
        title="Fact check title",
        snippet="Snippet of text",
        source_domain="factcheck.org",
        tier=Tier.TIER_1_IFCN,
        rating=Rating.FALSE,
        score=0.91,
    )
    assert good.tier == Tier.TIER_1_IFCN
    assert good.rating == Rating.FALSE

    # Bad instance (invalid tier)
    with pytest.raises(ValidationError):
        EvidenceItem(
            url="https://example.com",
            title="Title",
            snippet="Snippet",
            source_domain="example.com",
            tier="tier_unknown",  # type: ignore
        )


def test_claim_result_contract():
    # Good instance
    good = ClaimResult(
        claim="Drinking lemon water cures cancer",
        verdict=Verdict.REFUTED,
        confidence=0.95,
        reason_code="TIER1_FALSE",
    )
    assert good.verdict == Verdict.REFUTED

    # Bad instance (missing reason_code or invalid verdict)
    with pytest.raises(ValidationError):
        ClaimResult(
            claim="Claim text",
            verdict="INVALID_VERDICT",  # type: ignore
            confidence=0.5,
            reason_code="UNKNOWN",
        )


def test_check_response_contract():
    # Good instance
    good = CheckResponse(
        claim_results=[],
        overall_verdict=Verdict.UNVERIFIABLE,
        explanation="No reliable evidence found.",
        formatted_reply="*SatyaSetu Verdict:* UNVERIFIABLE",
        language="en",
    )
    assert good.overall_verdict == Verdict.UNVERIFIABLE

    # Bad instance
    with pytest.raises(ValidationError):
        CheckResponse(
            overall_verdict=Verdict.SUPPORTED,
            # missing explanation, formatted_reply, language
        )  # type: ignore


def test_webhook_payload_contract():
    # Good instance
    good = WebhookPayload(
        From="whatsapp:+919876543210",
        To="whatsapp:+14155238886",
        Body="Check this forward",
        NumMedia=0,
    )
    assert good.NumMedia == 0

    # Extra fields are ignored cleanly per config
    payload_with_extra = WebhookPayload.model_validate(
        {"From": "whatsapp:+1", "ExtraField": "extra_val"}
    )
    assert payload_with_extra.From == "whatsapp:+1"


# ── Core Layer Unit Tests ────────────────────────────────────────────────────


def test_settings_load():
    assert settings.app_name == "Satyasetu"
    assert settings.search_provider == "brave"
    assert isinstance(settings.retrieval_budget_ms, int)


def test_redact_phone_and_email():
    text = "call 9876543210"
    redacted = redact(text)
    # Must return no digits
    assert not re.search(r"\d", redacted)
    assert "[REDACTED_PHONE]" in redacted or "[REDACTED_NUMBER]" in redacted

    text_email = "send info to test.user@example.com immediately"
    redacted_email = redact(text_email)
    assert "test.user@example.com" not in redacted_email
    assert "[REDACTED_EMAIL]" in redacted_email

    text_whatsapp = "contact whatsapp:+919876543210 for details"
    redacted_wa = redact(text_whatsapp)
    assert "9876543210" not in redacted_wa


def test_hash_identifier():
    phone = "whatsapp:+919876543210"
    h = hash_identifier(phone)
    assert len(h) == 64
    assert phone not in h
    assert hash_identifier("") == ""


def test_stage_timer():
    with StageTimer("test_stage") as timer:
        time.sleep(0.01)  # 10ms
    assert timer.name == "test_stage"
    assert timer.elapsed_ms > 0
    # Sleep 10ms should be roughly 10ms (allowing window timer jitter)
    assert 5 <= timer.elapsed_ms <= 100


def test_logging_redaction_filter():
    redaction_filter = RedactionFilter()
    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="User sent message from 9876543210 with code 123456789012",
        args=(),
        exc_info=None,
    )

    request_id_var.set("req-test-123")
    passed = redaction_filter.filter(record)

    assert passed is True
    assert record.request_id == "req-test-123"
    # Digits from phone/number must be redacted
    assert "9876543210" not in record.msg
    assert "123456789012" not in record.msg


def test_constants_enums():
    assert InputType.TEXT == "text"
    assert InputType.SCREENSHOT == "screenshot"
    assert Tier.TIER_1_IFCN == "tier_1_ifcn"
    assert Rating.TRUE == "TRUE"
    assert Verdict.SUPPORTED == "SUPPORTED"
