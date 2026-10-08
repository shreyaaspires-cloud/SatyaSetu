"""
Unit tests for Wave 7: Explanation generator and WhatsApp formatter.
All tests are offline — no Gemini API calls are made (key intentionally absent).
"""

from __future__ import annotations

import pytest

from app.contracts.models import CheckResponse, ClaimResult, EvidenceItem
from app.core.constants import Rating, Tier, Verdict
from app.features.explanation.generator import (
    VERDICT_EMOJI,
    VERDICT_LABEL,
    _template_explanation,
    generate_explanation,
)
from app.features.explanation.formatter import (
    MAX_REPLY_LEN,
    WHATSAPP_HARD_CAP,
    format_whatsapp_reply,
    translate_reply_back,
)


# ── Fixtures ───────────────────────────────────────────────────────────────────

def _make_evidence(
    url: str = "https://factcheck.org/article",
    title: str = "Fact Check: Claim is False",
    snippet: str = "Our investigation found no evidence for this claim.",
    domain: str = "factcheck.org",
    tier: Tier = Tier.TIER_1_IFCN,
    rating: Rating = Rating.FALSE,
    score: float = 0.9,
    stance: str = "REFUTES",
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


def _make_claim_result(
    claim: str = "Vaccines cause autism",
    verdict: Verdict = Verdict.REFUTED,
    confidence: float = 0.95,
    reason_code: str = "AUTHORITATIVE_FACT_CHECK",
    evidence: list | None = None,
) -> ClaimResult:
    return ClaimResult(
        claim=claim,
        verdict=verdict,
        confidence=confidence,
        reason_code=reason_code,
        evidence=evidence or [_make_evidence()],
        guard_passed=True,
    )


def _make_response(
    claim_results: list | None = None,
    overall_verdict: Verdict = Verdict.REFUTED,
    explanation: str = "This claim is refuted by authoritative sources.",
    language: str = "en",
) -> CheckResponse:
    results = claim_results or [_make_claim_result()]
    return CheckResponse(
        claim_results=results,
        overall_verdict=overall_verdict,
        explanation=explanation,
        formatted_reply="",
        language=language,
        timings_ms={},
        cached=False,
    )


# ── Explanation Generator ──────────────────────────────────────────────────────

class TestTemplateExplanation:
    def test_contains_verdict_label(self):
        result = _make_claim_result(verdict=Verdict.REFUTED)
        explanation = _template_explanation(result)
        assert "REFUTED" in explanation

    def test_contains_evidence_strength_label(self):
        result = _make_claim_result(confidence=0.85)
        explanation = _template_explanation(result)
        assert "Evidence strength:" in explanation
        assert "%" not in explanation

    def test_contains_claim_text(self):
        result = _make_claim_result(claim="The earth is flat")
        explanation = _template_explanation(result)
        assert "The earth is flat" in explanation

    def test_no_evidence_reason_note(self):
        result = _make_claim_result(reason_code="NO_EVIDENCE", evidence=[])
        explanation = _template_explanation(result)
        assert "No relevant evidence" in explanation

    def test_inconclusive_note_present(self):
        result = _make_claim_result(reason_code="INCONCLUSIVE", evidence=[])
        explanation = _template_explanation(result)
        assert "inconclusive" in explanation.lower()

    def test_all_verdicts_produce_string(self):
        for verdict in Verdict:
            result = _make_claim_result(verdict=verdict)
            explanation = _template_explanation(result)
            assert isinstance(explanation, str)
            assert len(explanation) > 10


class TestGenerateExplanation:
    def test_returns_string(self):
        result = _make_claim_result()
        explanation = generate_explanation(result)
        assert isinstance(explanation, str)
        assert len(explanation) > 0

    def test_no_api_key_uses_template(self, monkeypatch):
        """Without Gemini key, should fall back to template (not raise)."""
        monkeypatch.setattr("app.core.config.settings.gemini_api_key", "")
        result = _make_claim_result()
        explanation = generate_explanation(result)
        assert isinstance(explanation, str)
        assert "REFUTED" in explanation


# ── WhatsApp Formatter ─────────────────────────────────────────────────────────

class TestFormatWhatsappReply:
    def test_returns_non_empty_string(self):
        response = _make_response()
        reply = format_whatsapp_reply(response)
        assert isinstance(reply, str)
        assert len(reply) > 0

    def test_contains_satyasetu_header(self):
        response = _make_response()
        reply = format_whatsapp_reply(response)
        assert "SatyaSetu" in reply

    def test_contains_overall_verdict_emoji(self):
        response = _make_response(overall_verdict=Verdict.REFUTED)
        reply = format_whatsapp_reply(response)
        assert "❌" in reply

    def test_contains_claim_text(self):
        response = _make_response()
        reply = format_whatsapp_reply(response)
        assert "Claim 1/" in reply

    def test_reply_under_max_len(self):
        response = _make_response()
        reply = format_whatsapp_reply(response)
        assert len(reply) <= MAX_REPLY_LEN

    def test_reply_hard_cap_never_exceeded(self):
        """Even with absurdly long explanation, hard cap must hold."""
        response = _make_response(explanation="A" * 5000)
        reply = format_whatsapp_reply(response)
        assert len(reply) <= WHATSAPP_HARD_CAP

    def test_empty_evidence_no_crash(self):
        result = _make_claim_result(evidence=[])
        response = _make_response(claim_results=[result])
        reply = format_whatsapp_reply(response)
        assert isinstance(reply, str)

    def test_multiple_claims_numbered(self):
        results = [
            _make_claim_result(claim="Claim A"),
            _make_claim_result(claim="Claim B", verdict=Verdict.SUPPORTED),
        ]
        response = _make_response(claim_results=results)
        reply = format_whatsapp_reply(response)
        assert "Claim 1/2" in reply
        assert "Claim 2/2" in reply

    @pytest.mark.parametrize("verdict", list(Verdict))
    def test_all_verdicts_render(self, verdict):
        response = _make_response(overall_verdict=verdict)
        reply = format_whatsapp_reply(response)
        assert isinstance(reply, str)


# ── Back-Translation ───────────────────────────────────────────────────────────

class TestTranslateReplyBack:
    def test_english_returns_unchanged(self):
        text = "Hello, this is a test reply."
        result = translate_reply_back(text, "en")
        assert result == text

    def test_no_api_key_returns_english(self, monkeypatch):
        monkeypatch.setattr("app.core.config.settings.gemini_api_key", "")
        text = "Fact-check result: REFUTED"
        result = translate_reply_back(text, "hi")
        assert result == text

    def test_empty_text_returns_empty(self):
        result = translate_reply_back("", "hi")
        assert result == ""

    def test_no_lang_code_returns_original(self):
        text = "Some reply"
        result = translate_reply_back(text, "")
        assert result == text


# ── TwiML helper (from core — avoids FastAPI import in test env) ──────────────

class TestTwimlMessage:
    def test_valid_twiml_structure(self):
        from app.core.twiml import twiml_message
        twiml = twiml_message("Hello World")
        assert twiml.startswith("<?xml")
        assert "<Response>" in twiml
        assert "<Message>" in twiml
        assert "Hello World" in twiml

    def test_escapes_ampersand(self):
        from app.core.twiml import twiml_message
        twiml = twiml_message("A & B")
        assert "&amp;" in twiml

    def test_escapes_angle_brackets(self):
        from app.core.twiml import twiml_message
        twiml = twiml_message("<script>")
        assert "&lt;script&gt;" in twiml


# ── Acceptance Tests: T6 (AT16) ──────────────────────────────────────────────

class TestT6Acceptance:
    def test_at16_no_reply_contains_confidence_percentage(self):
        """AT16: No reply contains a % character next to a confidence figure."""
        result = _make_claim_result(
            confidence=0.87,
            evidence=[
                _make_evidence(tier=Tier.TIER_1_IFCN, domain="altnews.in"),
                _make_evidence(tier=Tier.TIER_2_GOV_PIB, domain="pib.gov.in"),
            ],
        )
        response = _make_response(claim_results=[result])
        reply = format_whatsapp_reply(response)

        # Check no percentage symbol in reply
        assert "%" not in reply
        assert "87%" not in reply
        assert "Evidence strength:" in reply

