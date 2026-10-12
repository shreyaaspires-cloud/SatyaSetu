"""
app/features/retrieval/search_web.py
──────────────────────────────────────
Web search engine adapter supporting Brave Search and Tavily.
Enforces API key isolation, SSRF URL checks, and tiered domain classification.

Provider abstraction
─────────────────────
The public entry-point `search_web()` dispatches to one of two concrete
backends based on settings.search_provider:

  "brave"  → Brave Search API (count=5, JSON response).
  "tavily" → Tavily Search API (advanced depth, up to 7 results).

Adding a new provider requires implementing a `_search_<name>()` function
following the same (query: str, api_key: str) → List[EvidenceItem] signature
and registering it in the dispatcher switch.

Security
─────────
* API keys are loaded from environment variables via settings; never hardcoded.
* Each returned URL is validated through is_public_http_url() before being
  stored in an EvidenceItem — this prevents SSRF if a search engine returns
  internal or metadata-service URLs in its results.
* PII is redacted from the query before dispatch (redact_for_external).

Tavily fact-check bias
───────────────────────
Tavily's "advanced" search is biased with a "fact check:" prefix unless the
query already contains fact-checking vocabulary.  This increases the probability
of retrieving debunking articles over raw news reports.  If the biased query
fails (timeout / API error), the adapter retries with the raw query at "basic"
depth to ensure a result is always attempted.

Score normalization
────────────────────
Brave returns no result-level relevance score, so all items default to 0.80.
Tavily provides a float `score`; we clamp it to [0.2, 0.95] to prevent
pathological values from dominating the upstream ranking stage.
"""

from __future__ import annotations

import logging
from typing import List
from urllib.parse import urlparse

import requests

from app.contracts.models import EvidenceItem
from app.core.config import settings
from app.core.constants import Rating
from app.core.security import is_public_http_url
from app.features.retrieval.sources import classify_domain

logger = logging.getLogger(__name__)

# API base URLs — parameterised here for easy mocking in integration tests.
BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
TAVILY_SEARCH_URL = "https://api.tavily.com/search"


def _search_brave(query: str, api_key: str) -> List[EvidenceItem]:
    """
    Execute search using Brave Search API.

    Returns up to 5 results (count=5).  Each URL is validated via
    is_public_http_url() to block SSRF payloads in search results.
    Domain is classified into the five-tier trust system via classify_domain().
    """
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        # API key in header — never exposed in the URL query string.
        "X-Subscription-Token": api_key,
    }
    params = {"q": query, "count": 5}

    resp = requests.get(BRAVE_SEARCH_URL, headers=headers, params=params, timeout=5.0)
    resp.raise_for_status()

    data = resp.json()
    web_results = data.get("web", {}).get("results", [])
    items: List[EvidenceItem] = []

    for r in web_results:
        url = r.get("url", "")
        # Filter out internal / non-HTTP URLs from search results.
        if not url or not is_public_http_url(url):
            continue

        title = r.get("title", "")
        snippet = r.get("description", "")
        source_domain = (urlparse(url).netloc or "").lower()
        if source_domain.startswith("www."):
            source_domain = source_domain[4:]

        tier = classify_domain(url)
        items.append(
            EvidenceItem(
                url=url,
                title=title,
                snippet=snippet,
                source_domain=source_domain,
                tier=tier,
                rating=Rating.UNVERIFIED,
                score=0.80,  # Brave has no per-result relevance score; use fixed baseline.
            )
        )

    return items


def _search_tavily(query: str, api_key: str) -> List[EvidenceItem]:
    """
    Execute search using Tavily Search API with fact-checking query optimization.

    Query bias: prepends "fact check:" unless the query already uses
    fact-checking vocabulary.  On failure, falls back to the raw query at
    basic search depth to guarantee at least one retrieval attempt.
    """
    # Bias query toward fact checking if not already present.
    lower_q = query.lower()
    search_q = query
    if not any(k in lower_q for k in ["fact check", "debunk", "myth", "true or false", "hoax", "rumor"]):
        search_q = f"fact check: {query}"

    payload = {
        "api_key": api_key,
        "query": search_q,
        "search_depth": "advanced",
        "max_results": 7,
        "include_answer": True,
    }
    try:
        resp = requests.post(TAVILY_SEARCH_URL, json=payload, timeout=7.0)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        # Fallback to standard query if biased query fails.
        logger.debug("Biased search failed (%s), trying raw query.", exc)
        payload["query"] = query
        payload["search_depth"] = "basic"
        resp = requests.post(TAVILY_SEARCH_URL, json=payload, timeout=5.0)
        resp.raise_for_status()
        data = resp.json()

    results = data.get("results", [])
    items: List[EvidenceItem] = []

    for r in results:
        url = r.get("url", "")
        if not url or not is_public_http_url(url):
            continue

        title = r.get("title", "")
        snippet = r.get("content", "")
        source_domain = (urlparse(url).netloc or "").lower()
        if source_domain.startswith("www."):
            source_domain = source_domain[4:]

        tier = classify_domain(url)
        # Clamp Tavily's relevance score to [0.2, 0.95] to prevent outliers.
        raw_score = r.get("score")
        if raw_score is not None:
            try:
                item_score = round(max(0.2, min(0.95, float(raw_score))), 3)
            except (ValueError, TypeError):
                item_score = 0.75
        else:
            item_score = 0.75

        items.append(
            EvidenceItem(
                url=url,
                title=title,
                snippet=snippet,
                source_domain=source_domain,
                tier=tier,
                rating=Rating.UNVERIFIED,
                score=item_score,
            )
        )

    return items


def _search_google_news_rss(query: str, window: str = "7d") -> List[EvidenceItem]:
    """
    Keyless search provider using Google News RSS.
    Retrieves recent headlines and articles with publication dates and domain classification.
    """
    import xml.etree.ElementTree as ET
    from urllib.parse import quote_plus, urlparse

    q = quote_plus(f"{query} when:{window}") if window else quote_plus(query)
    url = f"https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) SatyaSetu/1.0"}

    try:
        resp = requests.get(url, headers=headers, timeout=5.0)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception as exc:
        logger.warning("Google News RSS retrieval failed: %s", exc)
        return []

    items: List[EvidenceItem] = []
    for it in root.findall("./channel/item")[:7]:
        src = it.find("source")
        domain = (urlparse(src.get("url")).hostname or "").lower() if src is not None and src.get("url") else ""
        if domain.startswith("www."):
            domain = domain[4:]

        title = it.findtext("title", "").strip()
        link = it.findtext("link", "").strip()
        pub = it.findtext("pubDate", "").strip()

        if not domain and link:
            domain = (urlparse(link).hostname or "").lower()
            if domain.startswith("www."):
                domain = domain[4:]

        tier = classify_domain(domain or link)
        items.append(
            EvidenceItem(
                url=link,
                title=title,
                snippet=title,
                source_domain=domain or "news.google.com",
                tier=tier,
                rating=Rating.UNVERIFIED,
                publish_date=pub,
                score=0.75,
            )
        )
    return items


def search_web(query: str) -> List[EvidenceItem]:
    """
    Search the web for claims or evidence using the configured provider.
    Supports Brave, Tavily, and keyless Google News RSS.
    Never raises exceptions.
    """
    if not query or not query.strip():
        return []

    provider = (settings.search_provider or "google_news_rss").lower().strip()

    # If provider requires an API key but none is configured, gracefully fall back to Google News RSS
    if provider in ("brave", "tavily") and not settings.search_api_key:
        logger.debug("Search API key not configured for %s. Using google_news_rss fallback.", provider)
        provider = "google_news_rss"

    # Redact PII from query before sending to external search provider.
    from app.core.redaction import redact_for_external
    cleaned_query = redact_for_external(query.strip())

    try:
        if provider == "google_news_rss":
            return _search_google_news_rss(cleaned_query)
        elif provider == "brave":
            return _search_brave(cleaned_query, settings.search_api_key)
        elif provider == "tavily":
            return _search_tavily(cleaned_query, settings.search_api_key)
        else:
            logger.warning("Unsupported search provider: %s, falling back to google_news_rss", provider)
            return _search_google_news_rss(cleaned_query)
    except Exception as exc:
        logger.warning("Web search failed for query '%s': %s", query, exc)
        return []
