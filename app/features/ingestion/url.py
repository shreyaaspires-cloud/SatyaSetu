"""
Article URL text extraction using newspaper3k with Open Graph meta fallback.
Guarantees SSRF validation on the target URL before any HTTP access.
"""

from __future__ import annotations

import logging
import re
from typing import Optional, TypedDict

from newspaper import Article

from app.core.security import is_public_http_url, safe_get

logger = logging.getLogger(__name__)

MAX_TEXT_CHARS = 10_000
REQUEST_TIMEOUT = 10


class URLResult(TypedDict):
    text: str
    title: str
    source_url: str
    extraction_method: str  # "newspaper" | "og_fallback" | "empty"


def fetch_og_description(url: str) -> str:
    """
    Fallback: fetch raw HTML via safe_get and extract Open Graph or meta description.
    Used when newspaper3k fails on paywalls or JS rendering.
    """
    try:
        response = safe_get(
            url,
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": "Mozilla/5.0 (compatible; SatyaSetu/1.0)"},
        )
        html = response.text

        og_match = re.search(
            r'<meta\s+(?:property=["\']og:description["\']\s+content=["\']([^"\']+)["\']'
            r'|content=["\']([^"\']+)["\']\s+property=["\']og:description["\'])',
            html,
            re.IGNORECASE,
        )
        if og_match:
            desc = og_match.group(1) or og_match.group(2) or ""
            return desc.strip()[:MAX_TEXT_CHARS]

        meta_match = re.search(
            r'<meta\s+name=["\']description["\']\s+content=["\']([^"\']+)["\']',
            html,
            re.IGNORECASE,
        )
        if meta_match:
            return meta_match.group(1).strip()[:MAX_TEXT_CHARS]

    except Exception as exc:
        logger.debug("OG fallback failed for %s: %s", url, exc)

    return ""


def extract_text_from_url(url: str) -> URLResult:
    """
    Scrape article text from URL.
    Validates URL against SSRF rules before attempting retrieval.
    Never raises exceptions. On failure, returns empty text.
    """
    if not url or not is_public_http_url(url):
        logger.warning("Rejected invalid or non-public URL in url_service: %s", url)
        return URLResult(text="", title="", source_url=url, extraction_method="empty")

    try:
        article = Article(url, request_timeout=REQUEST_TIMEOUT)
        article.download()
        article.parse()

        title = (article.title or "").strip()
        body = (article.text or "").strip()

        if body:
            logger.info("Successfully extracted article via newspaper3k (%d chars)", len(body))
            return URLResult(
                text=body[:MAX_TEXT_CHARS],
                title=title,
                source_url=url,
                extraction_method="newspaper",
            )
    except Exception as exc:
        logger.warning("newspaper3k failed for %s: %s. Trying OG fallback...", url, exc)

    # Fallback to Open Graph description
    og_text = fetch_og_description(url)
    if og_text:
        logger.info("Extracted %d chars via OG description fallback", len(og_text))
        return URLResult(
            text=og_text,
            title="",
            source_url=url,
            extraction_method="og_fallback",
        )

    return URLResult(text="", title="", source_url=url, extraction_method="empty")
