"""
Abuse test suite for Rate Limiting and DoS Protection (Wave 9).
Verifies:
  1. Hashing ensures no raw phone numbers are leaked into rate store keys.
  2. Sliding window rate limiter enforces settings.rate_limit_per_minute limit.
  3. Excessive requests within 60 seconds trigger rate limiting.
  4. Webhook returns a polite rate-limit notification without crashing or exposing stack traces.
  5. Different senders have independent rate limits.
"""

from __future__ import annotations

import time
import pytest
from starlette.testclient import TestClient

from app_main import app
from app.core.config import settings
from app.routers.webhook import _hash_sender, _is_rate_limited, _rate_store, _rate_lock


@pytest.fixture(autouse=True)
def clean_rate_store():
    with _rate_lock:
        _rate_store.clear()
    yield
    with _rate_lock:
        _rate_store.clear()


class TestRateLimiterCore:
    def test_phone_number_hashing(self):
        """Raw phone number is hashed with SHA-256 and truncated to 12 chars."""
        raw_phone = "+919876543210"
        hashed = _hash_sender(raw_phone)
        assert len(hashed) == 12
        assert raw_phone not in hashed
        assert hashed == _hash_sender(raw_phone)

    def test_different_senders_have_distinct_hashes(self):
        h1 = _hash_sender("+919876543210")
        h2 = _hash_sender("+919876543211")
        assert h1 != h2

    def test_rate_limiter_allows_up_to_configured_limit(self, monkeypatch):
        monkeypatch.setattr(settings, "rate_limit_per_minute", 3)
        sender = "sender_a"

        assert _is_rate_limited(sender) is False
        assert _is_rate_limited(sender) is False
        assert _is_rate_limited(sender) is False
        # 4th request exceeds limit of 3
        assert _is_rate_limited(sender) is True

    def test_different_senders_do_not_block_each_other(self, monkeypatch):
        monkeypatch.setattr(settings, "rate_limit_per_minute", 2)
        sender1 = "sender_1"
        sender2 = "sender_2"

        assert _is_rate_limited(sender1) is False
        assert _is_rate_limited(sender1) is False
        assert _is_rate_limited(sender1) is True

        # sender2 still has their quota available
        assert _is_rate_limited(sender2) is False
        assert _is_rate_limited(sender2) is False
        assert _is_rate_limited(sender2) is True


class TestWebhookRateLimitIntegration:
    def test_webhook_rate_limit_reply(self, monkeypatch):
        monkeypatch.setattr(settings, "rate_limit_per_minute", 2)
        client = TestClient(app)
        phone = "+919999988888"

        # Request 1: OK
        res1 = client.post("/webhook/twilio", data={"Body": "Claim 1", "From": f"whatsapp:{phone}"})
        assert res1.status_code == 200

        # Request 2: OK
        res2 = client.post("/webhook/twilio", data={"Body": "Claim 2", "From": f"whatsapp:{phone}"})
        assert res2.status_code == 200

        # Request 3: Exceeds rate limit -> Graceful 429
        res3 = client.post("/webhook/twilio", data={"Body": "Claim 3", "From": f"whatsapp:{phone}"})
        assert res3.status_code == 429
        assert "too many messages" in res3.text.lower()

    def test_ip_rate_limiting_middleware(self, monkeypatch):
        import app_main
        monkeypatch.setattr(app_main, "IP_RATE_LIMIT_PER_MINUTE", 2)
        client = TestClient(app)

        with app_main._ip_rate_lock:
            app_main._ip_rate_store.clear()

        # Request 1 & 2 pass
        r1 = client.get("/health")
        assert r1.status_code == 200
        r2 = client.get("/health")
        assert r2.status_code == 200

        # Request 3 hits IP limit
        r3 = client.get("/health")
        assert r3.status_code == 429
        assert r3.headers.get("retry-after") == "60"
        data = r3.json()
        assert data["code"] == "RATE_LIMIT_EXCEEDED"

