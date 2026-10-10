"""
Security controls for SSRF protection, Twilio authentication isolation,
and safe outbound HTTP communications.
"""

import ipaddress
import logging
import socket
from typing import Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests

from app.core.config import settings
from app.core.errors import SSRFSecurityError

logger = logging.getLogger(__name__)


def is_ip_private_or_reserved(ip_str: str) -> bool:
    """
    Check if an IP address string belongs to private, loopback, link-local,
    multicast, or reserved ranges.
    """
    try:
        ip = ipaddress.ip_address(ip_str)
        return (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        )
    except ValueError:
        return True


def is_public_http_url(url: str) -> bool:
    """
    Validate that a URL uses http/https and does not resolve to private,
    loopback, or cloud-metadata network addresses.
    Prevents SSRF attacks on internal services.
    """
    if not url or not isinstance(url, str):
        return False

    try:
        parsed = urlparse(url.strip())
        if parsed.scheme.lower() not in ("http", "https"):
            return False

        hostname = parsed.hostname
        if not hostname:
            return False

        hostname_lower = hostname.lower()

        # Reject obvious local hostnames
        if hostname_lower in ("localhost", "0.0.0.0"):
            return False
        if (
            hostname_lower.endswith(".local")
            or hostname_lower.endswith(".internal")
            or hostname_lower.endswith(".lan")
        ):
            return False

        # If hostname is an IP literal, check it directly
        try:
            ipaddress.ip_address(hostname)
            return not is_ip_private_or_reserved(hostname)
        except ValueError:
            # Hostname is a domain name, proceed to DNS resolution
            pass

        # If hostname is a domain name, resolve DNS to inspect actual target IPs
        port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
        try:
            addr_info = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
            if not addr_info:
                return False

            for entry in addr_info:
                sockaddr = entry[4]
                ip_str = sockaddr[0]
                if is_ip_private_or_reserved(ip_str):
                    logger.warning("SSRF blocked: %s resolved to private IP %s", hostname, ip_str)
                    return False

            return True
        except (socket.gaierror, socket.herror):
            return False

    except Exception as exc:
        logger.warning("URL validation failed for %s: %s", url, exc)
        return False


def get_twilio_media_auth(url: str) -> Optional[Tuple[str, str]]:
    """
    Return Basic Auth (sid, token) for Twilio URLs only. Never for non-Twilio hosts.

    BUG-12: Previously misnamed 'twilio_media_auth' causing BUG-01 in webhook.py
    where it was incorrectly called as a validator. This function is a credential
    helper only — it returns (account_sid, auth_token) or None.
    """
    if not url or not isinstance(url, str):
        return None

    try:
        parsed = urlparse(url.strip())
        if parsed.scheme == "https" and parsed.netloc == "api.twilio.com":
            if settings.twilio_account_sid and settings.twilio_auth_token:
                return (settings.twilio_account_sid, settings.twilio_auth_token)
        return None
    except Exception:
        return None


# BUG-12 backwards-compat alias — callers in ocr.py, asr.py, pdf.py use this name
twilio_media_auth = get_twilio_media_auth


def safe_get(
    url: str,
    max_redirects: int = 3,
    timeout: int = 10,
    headers: Optional[dict] = None,
    auth: Optional[Tuple[str, str]] = None,
    **kwargs,
) -> requests.Response:
    """
    Perform an HTTP GET request with SSRF validation on the initial URL
    and after every redirect hop (up to max_redirects).
    """
    current_url = url
    session = requests.Session()

    for hop in range(max_redirects + 1):
        if not is_public_http_url(current_url):
            raise SSRFSecurityError(
                f"Blocked potential SSRF access to non-public URL: {current_url}"
            )

        # BUG-06 / Credential isolation: only attach Twilio auth if destination is
        # still api.twilio.com. get_twilio_media_auth(url) returns None for any
        # non-Twilio host, so auth is automatically dropped on CDN redirect hops.
        should_send_auth = auth is not None and get_twilio_media_auth(current_url) is not None
        req_auth = auth if should_send_auth else None

        req_headers = {"User-Agent": "SatyaSetu/1.0 (+https://satyasetu.org)"}
        if headers:
            req_headers.update(headers)

        req = requests.Request(
            "GET",
            current_url,
            headers=req_headers,
            auth=req_auth,
            **kwargs,
        )
        prep = session.prepare_request(req)
        resp = session.send(prep, allow_redirects=False, timeout=timeout)

        if resp.is_redirect or resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("Location")
            if not location:
                return resp
            current_url = urljoin(current_url, location)
            continue

        return resp

    raise SSRFSecurityError(
        f"Exceeded maximum allowed redirects ({max_redirects}) starting from: {url}"
    )
