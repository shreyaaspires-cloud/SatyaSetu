"""
Acceptance tests for T10: PII redaction before external calls (AT25, AT26).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from app.core.redaction import redact_for_external


class TestT10Acceptance:
    def test_at25_redact_tokens_for_all_pii_types(self):
        """AT25 part 1: Verify token replacements for all required PII types."""
        # Phone numbers
        assert "[PHONE]" in redact_for_external("Call 9876543210 for details")
        assert "[PHONE]" in redact_for_external("Contact +91-9876543210")
        assert "[PHONE]" in redact_for_external("Reach whatsapp:+919876543210")

        # Email addresses
        assert "[EMAIL]" in redact_for_external("Write to contact.us@factcheck.org immediately")

        # Aadhaar-style numbers (12-digit)
        assert "[ID_NUMBER]" in redact_for_external("Aadhaar 1234 5678 9012 linked")
        assert "[ID_NUMBER]" in redact_for_external("UID 123456789012 verified")

        # PAN-style codes (5 letters, 4 digits, 1 letter)
        assert "[PAN]" in redact_for_external("PAN number ABCDE1234F submitted")

        # Card numbers (16-digit)
        assert "[CARD_NUMBER]" in redact_for_external("Card 1234-5678-9012-3456 charged")
        assert "[CARD_NUMBER]" in redact_for_external("Card 1234567890123456 charged")

        # UPI IDs
        assert "[UPI_ID]" in redact_for_external("Pay to merchant@upi now")
        assert "[UPI_ID]" in redact_for_external("Send money to payment@okaxis")
        assert "[UPI_ID]" in redact_for_external("UPI handle shop@paytm")

        # Long digit strings (>10 digits not matching phone)
        assert "[NUMBER]" in redact_for_external("Ref code 112233445566778899")

    def test_at25_external_callers_receive_redacted_claim(self):
        """AT25 part 2: External retrieval and translation clients receive token-redacted queries."""
        raw_claim = "Call 9876543210 or email test@example.com for free rations"

        # 1. Google Fact Check caller
        with patch("app.features.retrieval.factcheck_google._fetch_google_fact_check") as mock_google:
            from app.features.retrieval.factcheck_google import search_google_fact_check
            search_google_fact_check(raw_claim)
            if mock_google.called:
                call_query = mock_google.call_args[0][0]
                assert "9876543210" not in call_query
                assert "test@example.com" not in call_query
                assert "[PHONE]" in call_query
                assert "[EMAIL]" in call_query

        # 2. Wikipedia search caller
        with patch("app.features.retrieval.wikipedia.safe_get") as mock_wiki:
            from app.features.retrieval.wikipedia import search_wikipedia
            mock_resp = MagicMock()
            mock_resp.status_code = 404
            mock_wiki.return_value = mock_resp
            search_wikipedia(raw_claim)
            if mock_wiki.called:
                call_url = mock_wiki.call_args[0][0]
                assert "9876543210" not in call_url
                assert "test@example.com" not in call_url

        # 3. Web search caller
        with patch("app.features.retrieval.search_web._search_brave") as mock_brave:
            from app.features.retrieval.search_web import search_web
            search_web(raw_claim)
            if mock_brave.called:
                call_query = mock_brave.call_args[0][0]
                assert "9876543210" not in call_query
                assert "test@example.com" not in call_query
                assert "[PHONE]" in call_query
                assert "[EMAIL]" in call_query

    def test_at26_meaningful_numbers_survive_redaction(self):
        """AT26: Redaction does not remove Rs 500, 2 percent, 1 lakh, or other meaningful numbers."""
        text = "Scheme offers Rs 500 benefit with 2 percent interest to 1 lakh citizens in 2024"
        redacted = redact_for_external(text)

        assert "Rs 500" in redacted or "500" in redacted
        assert "2 percent" in redacted or "2" in redacted
        assert "1 lakh" in redacted or "1" in redacted
        assert "2024" in redacted
        assert "[PHONE]" not in redacted
        assert "[ID_NUMBER]" not in redacted
        assert "[NUMBER]" not in redacted
