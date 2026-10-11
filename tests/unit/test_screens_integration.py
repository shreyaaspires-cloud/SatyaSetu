"""
test_screens_integration.py
───────────────────────────
Integration and endpoint tests for all connected frontend screens and APIs:
- GET / (Landing Screen)
- GET /check (Check Your Message Screen)
- GET /processing (Verification Processing Screen)
- GET /result (Fact-Check Result Screen)
- GET /whatsapp & GET /demo (WhatsApp Web Fact-Checking Screen)
- GET /api/sample-claims
- POST /api/check
- POST /api/ocr
"""

from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

from app_main import app
from app.contracts.models import CheckResponse, Verdict


@pytest.fixture
def client():
    return TestClient(app)


def test_root_screen_serves_whatsapp_portal(client):
    """GET / should directly serve the WhatsApp Web AI portal."""
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "chat-input" in resp.text
    assert "SatyaSetu Bot" in resp.text


def test_whatsapp_screen_served(client):
    """GET /whatsapp and GET /demo should serve the WhatsApp Web simulation screen."""
    for path in ["/whatsapp", "/demo"]:
        resp = client.get(path)
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "chat-input" in resp.text
        assert "SatyaSetu Bot" in resp.text


def test_sample_claims_endpoint_removed(client):
    """GET /api/sample-claims should return 404 (removed in Phase 1 cleanup)."""
    resp = client.get("/api/sample-claims")
    assert resp.status_code == 404


def test_api_check_with_rich_metadata(client):
    """POST /api/check should return clean CheckAPIResponse with authentic evidence strength."""
    mock_res = CheckResponse(
        overall_verdict=Verdict.REFUTED,
        explanation="Lemon juice does not cure cancer.",
        formatted_reply="*VERDICT: REFUTED*\n\nLemon juice does not cure cancer.",
        language="en",
        claim_results=[],
        flags=[],
        timings_ms={"total_ms": 20.0},
    )
    with patch("app.routers.check.run_pipeline", return_value=mock_res):
        resp = client.post("/api/check", json={"text": "Lemon juice cures cancer in 48 hours"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["verdict"] == "REFUTED"
        assert data["verdict_label"] == "REFUTED"
        assert data["verdict_emoji"] == "❌"
        assert "evidence_strength" in data
        assert "evidence_strength_detail" in data
        assert "explanation" in data
        assert "formatted_reply" in data
        assert "evidence" in data
        assert "confidence" not in data
        assert "real_news" not in data
        assert "explanations" not in data


def test_api_ocr_endpoint_empty_file(client):
    """POST /api/ocr returns graceful error for empty file."""
    resp = client.post("/api/ocr", files={"file": ("test.png", b"", "image/png")})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
