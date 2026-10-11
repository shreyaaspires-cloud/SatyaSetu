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


def search_web(query: str) -> List[EvidenceItem]:
    """
    Search the web for claims or evidence using the configured provider (Brave or Tavily).
    Returns a list of structured EvidenceItem objects. Never raises exceptions.

    Caller contract: this function is safe to call unconditionally.  An absent
    API key, network timeout, or provider error all return an empty list so the
    pipeline can continue with partial evidence rather than aborting.
    """
    if not settings.search_api_key:
        logger.debug("Search API key not configured. Skipping web search.")
        return []

    if not query or not query.strip():
        return []

    # Redact PII from query before sending to external search provider.
    from app.core.redaction import redact_for_external
    cleaned_query = redact_for_external(query.strip())

    try:
        provider = (settings.search_provider or "brave").lower().strip()
        if provider == "brave":
            return _search_brave(cleaned_query, settings.search_api_key)
        elif provider == "tavily":
            return _search_tavily(cleaned_query, settings.search_api_key)
        else:
            logger.warning("Unsupported search provider: %s", provider)
            return []
    except Exception as exc:
        logger.warning("Web search failed for query '%s': %s", query, exc)
        return []
