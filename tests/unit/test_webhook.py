"""
Unit tests for non-blocking webhook, deduplication, and /api/check endpoint (T9).
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app_main import app


@pytest.fixture
def client():
    return TestClient(app)


class TestT9Acceptance:
    def test_at22_webhook_returns_under_2s_even_when_pipeline_takes_10s(self, client):
        """AT22: Webhook returns in < 2 s even when pipeline takes 10 s."""
        def slow_pipeline(*args, **kwargs):
            time.sleep(10.0)
            mock_res = MagicMock()
            mock_res.formatted_reply = "Done"
            return mock_res

        with patch("app.routers.webhook.run_pipeline", side_effect=slow_pipeline):
            t0 = time.monotonic()
            resp = client.post(
                "/webhook/twilio",
                data={
                    "From": "whatsapp:+919876543210",
                    "Body": "Claim taking 10 seconds",
                    "MessageSid": "SM_test_at22_unique",
                },
            )
            elapsed = time.monotonic() - t0

            assert resp.status_code == 200
            assert elapsed < 2.0
            assert "<Response><Message>" in resp.text
            assert "Checking this, one moment..." in resp.text

    def test_at23_same_messagesid_sent_twice_triggers_only_one_pipeline_run(self, client):
        """AT23: Same MessageSid sent twice triggers only one pipeline run."""
        mock_pipeline = MagicMock()
        mock_res = MagicMock()
        mock_res.formatted_reply = "Done"
        mock_pipeline.return_value = mock_res

        with patch("app.routers.webhook.run_pipeline", mock_pipeline):
            sid = f"SM_test_at23_{time.time()}"
            resp1 = client.post(
                "/webhook/twilio",
                data={
                    "From": "whatsapp:+919876543210",
                    "Body": "Duplicate claim test",
                    "MessageSid": sid,
                },
            )
            assert resp1.status_code == 200

            resp2 = client.post(
                "/webhook/twilio",
                data={
                    "From": "whatsapp:+919876543210",
                    "Body": "Duplicate claim test",
                    "MessageSid": sid,
                },
            )
            assert resp2.status_code == 200

            # Allow background tasks a brief slice to register
            time.sleep(0.3)
            assert mock_pipeline.call_count == 1

    def test_at24_two_simultaneous_requests_do_not_block_each_other(self, client):
        """AT24: Two simultaneous requests do not block each other."""
        import concurrent.futures

        def moderate_pipeline(*args, **kwargs):
            time.sleep(0.5)
            mock_res = MagicMock()
            mock_res.formatted_reply = "Moderate Done"
            return mock_res

        with patch("app.routers.webhook.run_pipeline", side_effect=moderate_pipeline):
            def send_req(msg_id: str):
                t0 = time.monotonic()
                r = client.post(
                    "/webhook/twilio",
                    data={
                        "From": f"whatsapp:+91987654321{msg_id}",
                        "Body": f"Simultaneous claim {msg_id}",
                        "MessageSid": f"SM_simul_{msg_id}_{time.time()}",
                    },
                )
                return r.status_code, time.monotonic() - t0

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                f1 = executor.submit(send_req, "1")
                f2 = executor.submit(send_req, "2")
                res1 = f1.result()
                res2 = f2.result()

            assert res1[0] == 200
            assert res2[0] == 200
            # Both webhooks return immediately (< 1.0s), not waiting 0.5s sequentially
            assert res1[1] < 1.0
            assert res2[1] < 1.0


class TestApiCheckEndpoint:
    def test_api_check_json_endpoint(self, client):
        """POST /api/check verifies a claim and returns JSON response."""
        from app.contracts.models import CheckResponse, Verdict
        mock_response = CheckResponse(
            overall_verdict=Verdict.REFUTED,
            explanation="Boiled water does not cure all diseases.",
            formatted_reply="*VERDICT: REFUTED*\n\nBoiled water does not cure all diseases.",
            language="en",
            claim_results=[],
            flags=[],
            timings_ms={"total_ms": 15.0},
        )
        with patch("app.routers.check.run_pipeline", return_value=mock_response):
            resp = client.post(
                "/api/check",
                json={"text": "Drinking boiled water cures all diseases"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["verdict"] == "REFUTED"
            assert "explanation" in data
            assert "formatted_reply" in data
