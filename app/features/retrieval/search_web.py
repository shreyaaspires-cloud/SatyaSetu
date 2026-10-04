"""
Web search engine adapter supporting Brave Search and Tavily.
Enforces API key isolation, SSRF URL checks, and tiered domain classification.
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

BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
TAVILY_SEARCH_URL = "https://api.tavily.com/search"


def _search_brave(query: str, api_key: str) -> List[EvidenceItem]:
    """Execute search using Brave Search API."""
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
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
                score=0.80,
            )
        )

    return items


def _search_tavily(query: str, api_key: str) -> List[EvidenceItem]:
    """Execute search using Tavily Search API."""
    payload = {
        "api_key": api_key,
        "query": query,
        "search_depth": "basic",
        "max_results": 5,
    }
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
        items.append(
            EvidenceItem(
                url=url,
                title=title,
                snippet=snippet,
                source_domain=source_domain,
                tier=tier,
                rating=Rating.UNVERIFIED,
                score=0.80,
            )
        )

    return items


def search_web(query: str) -> List[EvidenceItem]:
    """
    Search the web for claims or evidence using the configured provider (Brave or Tavily).
    Returns a list of structured EvidenceItem objects. Never raises exceptions.
    """
    if not settings.search_api_key:
        logger.debug("Search API key not configured. Skipping web search.")
        return []

    if not query or not query.strip():
        return []

    try:
        provider = (settings.search_provider or "brave").lower().strip()
        if provider == "brave":
            return _search_brave(query.strip(), settings.search_api_key)
        elif provider == "tavily":
            return _search_tavily(query.strip(), settings.search_api_key)
        else:
            logger.warning("Unsupported search provider: %s", provider)
            return []
    except Exception as exc:
        logger.warning("Web search failed for query '%s': %s", query, exc)
        return []
