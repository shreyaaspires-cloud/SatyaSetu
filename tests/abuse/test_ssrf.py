"""
Abuse test suite for SSRF (Server-Side Request Forgery) protection,
safe HTTP fetching, and Twilio credential leak prevention.
"""

from unittest.mock import MagicMock, patch
import pytest

from app.core.config import settings
from app.core.errors import SSRFSecurityError
from app.core.security import is_public_http_url, safe_get, twilio_media_auth


# ── SSRF URL Filter Tests ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "invalid_url",
    [
        "file:///etc/passwd",
        "file:///C:/Windows/win.ini",
        "ftp://example.com/secret.txt",
        "javascript:alert(1)",
        "data:text/plain;base64,SGVsbG8sIFdvcmxkIQ==",
        "gopher://127.0.0.1:70/",
        "",
        "not_a_url",
    ],
)
def test_reject_non_http_schemes(invalid_url):
    assert is_public_http_url(invalid_url) is False


@pytest.mark.parametrize(
    "private_ip_url",
    [
        "http://127.0.0.1:8000/api",
        "http://127.0.0.2:80/",
        "http://localhost:8000/",
        "http://localhost/",
        "http://0.0.0.0:8000/",
        "http://[::1]/",
        "http://10.0.0.1/admin",
        "http://10.255.255.255/",
        "http://172.16.0.1/",
        "http://172.25.0.1/",
        "http://172.31.255.255/",
        "http://192.168.0.1/router",
        "http://192.168.1.254/",
        "http://169.254.169.254/latest/meta-data/",
        "http://169.254.169.254/computeMetadata/v1/",
    ],
)
def test_reject_private_and_loopback_ips(private_ip_url):
    assert is_public_http_url(private_ip_url) is False


def test_reject_dns_resolving_to_private_ip():
    with patch("socket.getaddrinfo") as mock_dns:
        # Mock DNS returning loopback IP 127.0.0.1
        mock_dns.return_value = [
            (2, 1, 6, "", ("127.0.0.1", 80))
        ]
        assert is_public_http_url("http://malicious-local-redirect.com/secret") is False


def test_allow_valid_public_urls():
    with patch("socket.getaddrinfo") as mock_dns:
        # Mock DNS returning public IP 93.184.216.34 (example.com)
        mock_dns.return_value = [
            (2, 1, 6, "", ("93.184.216.34", 443))
        ]
        assert is_public_http_url("https://example.com/article") is True
        assert is_public_http_url("https://pib.gov.in/PressReleasePage.aspx?PRID=12345") is True


# ── Twilio Media Auth Guard Tests ───────────────────────────────────────────


def test_twilio_media_auth_only_for_official_twilio_domain():
    orig_sid = settings.twilio_account_sid
    orig_token = settings.twilio_auth_token
    try:
        settings.twilio_account_sid = "ACtest_account"
        settings.twilio_auth_token = "test_auth_token"

        # Valid Twilio API endpoint
        valid_twilio_url = "https://api.twilio.com/2010-04-01/Accounts/ACtest/Recordings/RE123"
        auth = twilio_media_auth(valid_twilio_url)
        assert auth == ("ACtest_account", "test_auth_token")

        # Insecure HTTP to Twilio must be rejected
        insecure_url = "http://api.twilio.com/media/123"
        assert twilio_media_auth(insecure_url) is None

        # Attacker subdomains / mimics must be rejected
        assert twilio_media_auth("https://api.twilio.com.attacker.com/media") is None
        assert twilio_media_auth("https://attacker.com/api.twilio.com") is None
        assert twilio_media_auth("https://evil-site.com/image.png") is None
        assert twilio_media_auth("https://not-twilio.com") is None
    finally:
        settings.twilio_account_sid = orig_sid
        settings.twilio_auth_token = orig_token


# ── Safe GET Execution Tests ────────────────────────────────────────────────


def test_safe_get_raises_on_ssrf():
    with pytest.raises(SSRFSecurityError):
        safe_get("http://169.254.169.254/latest/meta-data/")


def test_safe_get_follows_safe_redirects():
    with patch("app.core.security.is_public_http_url", return_value=True):
        with patch("requests.Session.send") as mock_send:
            # First response redirects (302) to safe public url
            res1 = MagicMock()
            res1.is_redirect = True
            res1.status_code = 302
            res1.headers = {"Location": "https://example.com/final"}

            # Second response is 200 OK
            res2 = MagicMock()
            res2.is_redirect = False
            res2.status_code = 200
            res2.content = b"OK content"

            mock_send.side_effect = [res1, res2]

            resp = safe_get("https://example.com/initial", max_redirects=3)
            assert resp.status_code == 200


def test_safe_get_blocks_redirect_to_private_ip():
    with patch("app.core.security.is_public_http_url") as mock_check:
        # Initial url is public, redirect target is private
        mock_check.side_effect = lambda url: "127.0.0.1" not in url

        with patch("requests.Session.send") as mock_send:
            res1 = MagicMock()
            res1.is_redirect = True
            res1.status_code = 302
            res1.headers = {"Location": "http://127.0.0.1/admin"}
            mock_send.return_value = res1

            with pytest.raises(SSRFSecurityError):
                safe_get("https://example.com/redirect-to-internal")
