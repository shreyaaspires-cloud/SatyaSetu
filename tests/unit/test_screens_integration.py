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


def test_landing_screen_served(client):
    """GET / should serve the main portal landing screen."""
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "SatyaSetu" in resp.text
    assert "hero-input" in resp.text


def test_check_screen_served(client):
    """GET /check should serve the message submission screen."""
    resp = client.get("/check")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "message-input" in resp.text


def test_processing_screen_served(client):
    """GET /processing should serve the verification progress screen."""
    resp = client.get("/processing")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Verifying" in resp.text or "SatyaSetu" in resp.text


def test_result_screen_served(client):
    """GET /result should serve the comprehensive fact-check report screen."""
    resp = client.get("/result")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "verdict-heading" in resp.text


def test_whatsapp_screen_served(client):
    """GET /whatsapp and GET /demo should serve the WhatsApp Web simulation screen."""
    for path in ["/whatsapp", "/demo"]:
        resp = client.get(path)
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "chat-input" in resp.text
        assert "SatyaSetu Bot" in resp.text


def test_sample_claims_endpoint(client):
    """GET /api/sample-claims should return curated claims."""
    resp = client.get("/api/sample-claims")
    assert resp.status_code == 200
    data = resp.json()
    assert "samples" in data
    assert len(data["samples"]) >= 3


def test_api_check_with_rich_metadata(client):
    """POST /api/check should return verdict, labels, explanations, and evidence."""
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
        assert "verdict_label" in data
        assert "verdict_label_hi" in data
        assert "evidence_strength" in data
        assert "explanations" in data
        assert "evidence" in data


def test_api_ocr_endpoint_empty_file(client):
    """POST /api/ocr returns graceful error for empty file."""
    resp = client.post("/api/ocr", files={"file": ("test.png", b"", "image/png")})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
