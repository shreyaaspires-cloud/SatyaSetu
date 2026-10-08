"""
Integration smoke tests for SatyaSetu (Wave 9).
Tests end-to-end flows:
  1. IngestedMessage -> run_pipeline -> CheckResponse
  2. Multilingual / Hindi / Hinglish claim processing
  3. FastAPI endpoints (/health, /health/detailed, /webhook/twilio) via TestClient
  4. Timing and verdict propagation
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from app_main import app
from app.contracts.models import CheckResponse, IngestedMessage
from app.core.constants import InputType, Verdict
from app.pipeline import run_pipeline


@pytest.fixture
def client():
    return TestClient(app)


class TestPipelineEndToEnd:
    def test_pipeline_english_claim(self):
        """Standard English claim through entire pipeline."""
        msg = IngestedMessage(
            raw_text="Drinking bleach cures COVID-19 immediately.",
            input_type=InputType.TEXT,
            from_number="sender_hash_123",
            original_body="Drinking bleach cures COVID-19 immediately.",
        )
        response = run_pipeline(msg)
        assert isinstance(response, CheckResponse)
        assert response.language in ("en", "hi", "mr", "ta", "te", "bn", "gu", "kn", "ml", "pa")
        assert response.overall_verdict in list(Verdict)
        assert isinstance(response.claim_results, list)
        assert len(response.formatted_reply) > 0
        assert "*SatyaSetu Fact Check*" in response.formatted_reply
        assert "timings_ms" in response.model_dump()
        assert "total_ms" in response.timings_ms

    def test_pipeline_multilingual_hindi(self):
        """Hindi text processed through pipeline without errors."""
        msg = IngestedMessage(
            raw_text="हल्दी का पानी पीने से सभी रोग ठीक हो जाते हैं।",
            input_type=InputType.TEXT,
            from_number="sender_hash_456",
            original_body="हल्दी का पानी पीने से सभी रोग ठीक हो जाते हैं।",
        )
        response = run_pipeline(msg)
        assert isinstance(response, CheckResponse)
        assert len(response.formatted_reply) > 0
        assert response.overall_verdict in list(Verdict)

    def test_pipeline_short_unverifiable_claim(self):
        """Empty or ambiguous text gracefully produces an unverifiable response."""
        msg = IngestedMessage(
            raw_text="hello good morning",
            input_type=InputType.TEXT,
            from_number="sender_hash_789",
            original_body="hello good morning",
        )
        response = run_pipeline(msg)
        assert isinstance(response, CheckResponse)
        assert response.overall_verdict in list(Verdict)
        assert len(response.formatted_reply) > 0


class TestEndpointsSmoke:
    def test_health_endpoint(self, client):
        """GET /health returns 200 with status ok and uptime."""
        res = client.get("/health")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert "uptime_seconds" in data
        assert "version" in data

    def test_health_detailed_endpoint(self, client):
        """GET /health/detailed returns 200 with diagnostics."""
        res = client.get("/health/detailed")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert "environment" in data
        assert "features_enabled" in data
        assert "uptime_seconds" in data

    def test_webhook_twilio_empty_payload(self, client):
        """POST /webhook/twilio with empty body gracefully returns TwiML."""
        from unittest.mock import patch
        with patch("app.routers.webhook.run_pipeline"):
            res = client.post(
                "/webhook/twilio",
                data={"Body": "Is water wet?", "From": "whatsapp:+919876543210"},
            )
            assert res.status_code == 200
            assert "<Response><Message>" in res.text
            assert "</Message></Response>" in res.text
