"""
Unit tests for Wave 7 / Phase 1: Simple reply formatter, truth score rules, and concise generator.
All tests are offline — no external API calls required.
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
    compute_truth_score,
    compute_evidence_strength,
    format_whatsapp_reply,
    get_plain_verdict_label,
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


# ── Truth Score Calculation ────────────────────────────────────────────────────

class TestTruthScoreCalculation:
    def test_refuted_score_clamped(self):
        # confidence 0.9 -> round(0.1 * 10) = 1
        assert compute_truth_score(Verdict.REFUTED, 0.90) == 1
        # confidence 0.99 -> round(0.01 * 10) = 0
        assert compute_truth_score(Verdict.REFUTED, 0.99) == 0
        # confidence 0.70 -> round(0.3 * 10) = 3 clamped to 2
        assert compute_truth_score(Verdict.REFUTED, 0.70) == 2

    def test_supported_score_clamped(self):
        # confidence 0.95 -> round(0.95 * 10) = 10 (or 9.5 -> 10)
        assert compute_truth_score(Verdict.SUPPORTED, 0.95) == 10
        # confidence 0.82 -> round(8.2) = 8
        assert compute_truth_score(Verdict.SUPPORTED, 0.82) == 8
        # confidence 0.70 -> clamped to 8
        assert compute_truth_score(Verdict.SUPPORTED, 0.70) == 8

    def test_partially_supported_fixed_score(self):
        assert compute_truth_score(Verdict.PARTIALLY_SUPPORTED) == 5

    def test_outdated_fixed_score(self):
        assert compute_truth_score(Verdict.OUTDATED) == 3

    def test_unverifiable_no_score(self):
        assert compute_truth_score(Verdict.UNVERIFIABLE) is None


# ── Explanation Generator ──────────────────────────────────────────────────────

class TestExplanationGenerator:
    def test_template_returns_string(self):
        result = _make_claim_result(verdict=Verdict.REFUTED)
        explanation = _template_explanation(result)
        assert isinstance(explanation, str)
        assert len(explanation) > 0

    def test_all_verdicts_produce_explanation(self):
        for verdict in Verdict:
            result = _make_claim_result(verdict=verdict, evidence=[])
            explanation = _template_explanation(result)
            assert isinstance(explanation, str)
            assert len(explanation) > 5

    def test_health_claim_advisory(self):
        result = _make_claim_result(
            claim="Drinking bleach cures cancer",
            verdict=Verdict.UNVERIFIABLE,
            evidence=[],
        )
        explanation = _template_explanation(result)
        assert "WHO.int" in explanation or "doctor" in explanation

    def test_no_api_key_uses_template(self, monkeypatch):
        monkeypatch.setattr("app.core.config.settings.gemini_api_key", "")
        result = _make_claim_result()
        explanation = generate_explanation(result)
        assert isinstance(explanation, str)
        assert len(explanation) > 0


# ── WhatsApp Formatter ─────────────────────────────────────────────────────────

class TestFormatWhatsappReply:
    def test_returns_clean_string(self):
        response = _make_response()
        reply = format_whatsapp_reply(response)
        assert isinstance(reply, str)
        assert "❌ *Fake*" in reply
        assert "Truth score: 1/10" in reply
        assert "*Claim:*" in reply
        assert "*Why:*" in reply
        assert "*Check:*" in reply
        assert "_Send this to whoever forwarded it._" in reply

    def test_length_under_600_chars(self):
        response = _make_response()
        reply = format_whatsapp_reply(response)
        assert len(reply) < 600

    def test_hindi_reply_localization(self):
        result = _make_claim_result(claim="नींबू पानी से कैंसर ठीक होता है")
        response = _make_response(claim_results=[result], language="hi")
        reply = format_whatsapp_reply(response)
        assert "झूठ" in reply
        assert "सत्यता स्कोर" in reply
        assert "*दावा:*" in reply
        assert "*कारण:*" in reply
        assert "फॉरवर्ड करें" in reply

    def test_unverifiable_shows_not_enough_proof(self):
        result = _make_claim_result(
            claim="Unverified rumour",
            verdict=Verdict.UNVERIFIABLE,
            evidence=[],
        )
        response = _make_response(claim_results=[result], overall_verdict=Verdict.UNVERIFIABLE)
        reply = format_whatsapp_reply(response)
        assert "❓ *Can't confirm*" in reply
        assert "Not enough proof yet." in reply

    def test_multiple_claims_compact_layout(self):
        results = [
            _make_claim_result(claim="Claim A"),
            _make_claim_result(claim="Claim B", verdict=Verdict.SUPPORTED),
        ]
        response = _make_response(claim_results=results)
        reply = format_whatsapp_reply(response)
        assert "Claim A" in reply
        assert "Claim B" in reply
        assert len(reply) < 700

    def test_no_percentage_signs(self):
        response = _make_response()
        reply = format_whatsapp_reply(response)
        assert "%" not in reply

    def test_hard_cap_respected(self):
        long_exp = "A" * 5000
        response = _make_response(explanation=long_exp)
        reply = format_whatsapp_reply(response)
        assert len(reply) <= WHATSAPP_HARD_CAP


# ── Back-Translation ───────────────────────────────────────────────────────────

class TestTranslateReplyBack:
    def test_english_returns_unchanged(self):
        text = "Hello, this is a test reply."
        result = translate_reply_back(text, "en")
        assert result == text

    def test_no_api_key_returns_english(self, monkeypatch):
        monkeypatch.setattr("app.core.config.settings.gemini_api_key", "")
        text = "Fact-check result: Fake"
        result = translate_reply_back(text, "hi")
        assert result == text

    def test_empty_text_returns_empty(self):
        assert translate_reply_back("", "hi") == ""
