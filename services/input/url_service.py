"""
services/input/url_service.py
──────────────────────────────
Article URL scraping using newspaper3k.

Rules enforced:
  - Extracts clean body text only (removes ads, nav, footer via newspaper3k)
  - Caps extracted text at 10,000 characters (per TRD §7 critical numbers)
  - Fallback: if newspaper3k fails (403 / paywall), return Open Graph description
  - Returns empty string on failure — never raises
"""

from __future__ import annotations

import logging
from typing import TypedDict

import requests
from newspaper import Article, ArticleException

logger = logging.getLogger(__name__)

MAX_TEXT_CHARS = 10_000     # TRD critical number
REQUEST_TIMEOUT = 10        # seconds


class URLResult(TypedDict):
    text: str
    title: str
    source_url: str
    extraction_method: str   # "newspaper" | "og_fallback" | "empty"


def _fetch_og_description(url: str) -> str:
    """
    Fallback: fetch raw HTML and extract Open Graph meta description.
    Used when newspaper3k hits a 403 or paywall.
    Returns empty string if nothing found.
    """
    try:
        response = requests.get(
            url,
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": "Mozilla/5.0 (compatible; FactGuard/1.0)"},
        )
        html = response.text

        # Simple regex-free OG tag extraction
        import re
        og_match = re.search(
            r'<meta\s+(?:property=["\']og:description["\']\s+content=["\']([^"\']+)["\']'
            r'|content=["\']([^"\']+)["\']\s+property=["\']og:description["\'])',
            html,
            re.IGNORECASE,
        )
        if og_match:
            return (og_match.group(1) or og_match.group(2) or "").strip()[:MAX_TEXT_CHARS]

        # Try standard meta description as last resort
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
    Scrape article text from `url` using newspaper3k.

    Process:
        1. Download + parse with newspaper3k
        2. Return title + article body text (capped at 10,000 chars)
        3. On failure (403, paywall, JS-only), fall back to Open Graph meta description
        4. On total failure, return empty string

    Returns:
        URLResult with 'text', 'title', 'source_url', 'extraction_method'

    Never raises — the pipeline must continue even if URL scraping fails.
    """
    if not url or not url.startswith(("http://", "https://")):
        logger.warning("Invalid URL provided to url_service: %s", url)
        return URLResult(text="", title="", source_url=url, extraction_method="empty")

    try:
        article = Article(url, request_timeout=REQUEST_TIMEOUT)
        article.download()
        article.parse()

        title = (article.title or "").strip()
        body = (article.text or "").strip()

        if not body:
            raise ArticleException("Empty article body after parse")

        # Combine title + body for maximum context, capped at limit
        combined = f"{title}\n\n{body}" if title else body
        combined = combined[:MAX_TEXT_CHARS]

        logger.info(
            "newspaper3k extracted %d chars from %s (title: %s)",
            len(combined),
            url,
            title[:50] if title else "N/A",
        )
        return URLResult(
            text=combined,
            title=title,
            source_url=url,
            extraction_method="newspaper",
        )

    except ArticleException as exc:
        logger.warning("newspaper3k failed for %s: %s — trying OG fallback", url, exc)

    except Exception as exc:
        logger.warning(
            "Unexpected error scraping %s: %s — trying OG fallback", url, exc
        )

    # Fallback: Open Graph / meta description
    og_text = _fetch_og_description(url)
    if og_text:
        logger.info("OG fallback extracted %d chars from %s", len(og_text), url)
        return URLResult(
            text=og_text,
            title="",
            source_url=url,
            extraction_method="og_fallback",
        )

    logger.warning("All extraction methods failed for URL: %s", url)
    return URLResult(text="", title="", source_url=url, extraction_method="empty")
