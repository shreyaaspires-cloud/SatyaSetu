"""
Unit tests for Wave 8: End-to-end pipeline orchestrator.
Tests the run_pipeline function with mock/offline inputs.
Network calls are short-circuited via low budget_ms settings.
"""

from __future__ import annotations

import pytest

from app.contracts.models import CheckResponse, IngestedMessage
from app.core.constants import InputType, Verdict
from app.pipeline import _derive_overall_verdict, run_pipeline


# ── _derive_overall_verdict ────────────────────────────────────────────────────

class TestDeriveOverallVerdict:
    def test_empty_returns_unverifiable(self):
        assert _derive_overall_verdict([]) == Verdict.UNVERIFIABLE

    def test_any_refuted_gives_refuted(self):
        from app.contracts.models import ClaimResult

        results = [
            ClaimResult(claim="a", verdict=Verdict.SUPPORTED, confidence=0.9, reason_code="X"),
            ClaimResult(claim="b", verdict=Verdict.REFUTED, confidence=0.8, reason_code="Y"),
        ]
        assert _derive_overall_verdict(results) == Verdict.REFUTED

    def test_refuted_priority_over_misleading(self):
        from app.contracts.models import ClaimResult

        results = [
            ClaimResult(claim="a", verdict=Verdict.MISLEADING, confidence=0.7, reason_code="X"),
            ClaimResult(claim="b", verdict=Verdict.REFUTED, confidence=0.8, reason_code="Y"),
        ]
        assert _derive_overall_verdict(results) == Verdict.REFUTED

    def test_misleading_without_refuted(self):
        from app.contracts.models import ClaimResult

        results = [
            ClaimResult(claim="a", verdict=Verdict.SUPPORTED, confidence=0.7, reason_code="X"),
            ClaimResult(claim="b", verdict=Verdict.MISLEADING, confidence=0.6, reason_code="Y"),
        ]
        assert _derive_overall_verdict(results) == Verdict.MISLEADING

    def test_all_supported_gives_supported(self):
        from app.contracts.models import ClaimResult

        results = [
            ClaimResult(claim="a", verdict=Verdict.SUPPORTED, confidence=0.9, reason_code="X"),
            ClaimResult(claim="b", verdict=Verdict.SUPPORTED, confidence=0.85, reason_code="Y"),
        ]
        assert _derive_overall_verdict(results) == Verdict.SUPPORTED

    def test_mix_supported_unverifiable_gives_unverifiable(self):
        from app.contracts.models import ClaimResult

        results = [
            ClaimResult(claim="a", verdict=Verdict.SUPPORTED, confidence=0.9, reason_code="X"),
            ClaimResult(claim="b", verdict=Verdict.UNVERIFIABLE, confidence=0.0, reason_code="Y"),
        ]
        assert _derive_overall_verdict(results) == Verdict.UNVERIFIABLE


# ── run_pipeline ───────────────────────────────────────────────────────────────

def _make_message(text: str = "Test claim about vaccines.", lang: str = "en") -> IngestedMessage:
    return IngestedMessage(
        raw_text=text,
        input_type=InputType.TEXT,
        from_number="abc123hash",
        original_body=text,
    )


class TestRunPipeline:
    def test_returns_check_response(self):
        """Pipeline must always return a CheckResponse, even under tight budget."""
        msg = _make_message()
        response = run_pipeline(msg)
        assert isinstance(response, CheckResponse)

    def test_language_field_populated(self):
        msg = _make_message("Hello this is a test")
        response = run_pipeline(msg)
        assert isinstance(response.language, str)
        assert len(response.language) > 0

    def test_formatted_reply_is_non_empty(self):
        msg = _make_message("The earth is flat and NASA is lying about space.")
        response = run_pipeline(msg)
        assert isinstance(response.formatted_reply, str)
        assert len(response.formatted_reply) > 0

    def test_timings_ms_has_total(self):
        msg = _make_message("Is this fact true?")
        response = run_pipeline(msg)
        assert "total_ms" in response.timings_ms
        assert response.timings_ms["total_ms"] >= 0

    def test_greeting_returns_prompt_reply(self):
        """Low check-worthiness greeting should short-circuit with a prompt."""
        msg = _make_message("Hi")
        response = run_pipeline(msg)
        assert isinstance(response.formatted_reply, str)
        assert response.overall_verdict == Verdict.UNVERIFIABLE

    def test_empty_text_does_not_raise(self):
        """Empty input must not crash the pipeline."""
        msg = _make_message("")
        response = run_pipeline(msg)
        assert isinstance(response, CheckResponse)

    def test_claim_results_list(self):
        msg = _make_message("The moon landing was faked by NASA in 1969.")
        response = run_pipeline(msg)
        assert isinstance(response.claim_results, list)

    def test_verdict_is_valid_enum(self):
        msg = _make_message("Drinking bleach cures all diseases.")
        response = run_pipeline(msg)
        assert response.overall_verdict in list(Verdict)
