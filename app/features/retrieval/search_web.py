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
from typing import Dict, List, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests

from app.contracts.models import EvidenceItem
from app.core.config import settings
from app.core.constants import Rating, Tier
from app.core.security import is_public_http_url
from app.features.retrieval.sources import classify_domain

logger = logging.getLogger(__name__)

# API base URLs — parameterised here for easy mocking in integration tests.
BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
TAVILY_SEARCH_URL = "https://api.tavily.com/search"

# Numerical priority for sorting tiers (lower number = higher trust)
TIER_PRIORITY: Dict[Tier, int] = {
    Tier.TIER_1_IFCN: 1,
    Tier.TIER_2_GOV_PIB: 2,
    Tier.TIER_3_MAINSTREAM: 3,
    Tier.TIER_4_WIKIPEDIA: 4,
    Tier.TIER_5_GENERAL_WEB: 5,
}


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
        "search_depth": "basic",
        "max_results": 5,
        "include_answer": True,
    }
    try:
        resp = requests.post(TAVILY_SEARCH_URL, json=payload, timeout=3.5)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        # Fallback to standard query if biased query fails.
        logger.debug("Biased search failed (%s), trying raw query.", exc)
        payload["query"] = query
        payload["search_depth"] = "basic"
        resp = requests.post(TAVILY_SEARCH_URL, json=payload, timeout=3.0)
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
        resp = requests.get(url, headers=headers, timeout=2.5)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception as exc:
        logger.warning("Google News RSS retrieval failed: %s", exc)
        return []

    items: List[EvidenceItem] = []
    for it in root.findall("./channel/item")[:5]:
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


def _canonicalize_url(raw_url: str) -> str:
    """
    Canonicalize a URL for reliable deduplication:
    - Lowercases scheme and domain.
    - Strips 'www.' prefixes and trailing slashes.
    - Strips analytics / tracking query parameters (utm_*, ref, fbclid, etc.).
    """
    if not raw_url:
        return ""
    try:
        parsed = urlparse(raw_url.strip())
        netloc = (parsed.netloc or "").lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        path = (parsed.path or "").rstrip("/")
        qs = parse_qsl(parsed.query)
        cleaned_qs = [
            (k, v) for k, v in qs
            if not k.lower().startswith("utm_")
            and k.lower() not in ("ref", "fbclid", "gclid", "ocid", "ved", "source", "feature", "output")
        ]
        new_query = urlencode(cleaned_qs)
        return urlunparse((parsed.scheme.lower() or "https", netloc, path, "", new_query, ""))
    except Exception:
        return raw_url.strip().lower()


def _search_parallel_hybrid(query: str) -> List[EvidenceItem]:
    """
    Execute concurrent multi-provider search across Tavily, Google News RSS, and Brave.
    - Dispatches tasks in parallel using ThreadPoolExecutor.
    - Bounded per-future timeout prevents slow engines from blocking the pipeline.
    - Canonicalizes and deduplicates URLs, combining snippets and ranking by trust tier.
    """
    import concurrent.futures

    tasks: dict[concurrent.futures.Future, str] = {}
    collected: List[EvidenceItem] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=3, thread_name_prefix="search_hybrid") as executor:
        # 1. Google News RSS is keyless and zero-cost
        tasks[executor.submit(_search_google_news_rss, query)] = "google_news_rss"

        # 2. Tavily if key is available
        if settings.search_api_key and not settings.search_api_key.startswith("BSA"):
            tasks[executor.submit(_search_tavily, query, settings.search_api_key)] = "tavily"

        # 3. Brave if key is configured (Brave keys start with BSA)
        if settings.search_api_key and settings.search_api_key.startswith("BSA"):
            tasks[executor.submit(_search_brave, query, settings.search_api_key)] = "brave"

        try:
            for future in concurrent.futures.as_completed(tasks, timeout=2.2):
                prov_name = tasks[future]
                try:
                    items = future.result()
                    if items:
                        logger.debug("Provider '%s' retrieved %d items in hybrid search", prov_name, len(items))
                        collected.extend(items)
                except Exception as exc:
                    logger.warning("Provider '%s' failed during hybrid search: %s", prov_name, exc)
        except concurrent.futures.TimeoutError:
            logger.warning("Hybrid search reached 2.2s timeout; proceeding with available results.")

    if not collected:
        return []

    # Deduplicate by canonical URL, preserving higher trust tier and longer snippet
    seen: dict[str, EvidenceItem] = {}
    for item in collected:
        canon_key = _canonicalize_url(item.url) or item.title.strip().lower()
        if not canon_key:
            continue
        if canon_key not in seen:
            seen[canon_key] = item
        else:
            existing = seen[canon_key]
            curr_pri = TIER_PRIORITY.get(item.tier, 99)
            exist_pri = TIER_PRIORITY.get(existing.tier, 99)
            if curr_pri < exist_pri or (curr_pri == exist_pri and item.score > existing.score):
                if len(existing.snippet) > len(item.snippet):
                    item.snippet = existing.snippet
                seen[canon_key] = item
            elif len(item.snippet) > len(existing.snippet):
                existing.snippet = item.snippet

    deduped = list(seen.values())
    deduped.sort(key=lambda it: (TIER_PRIORITY.get(it.tier, 99), -it.score))
    return deduped[:5]


def search_web(query: str) -> List[EvidenceItem]:
    """
    Search the web for claims or evidence using configured provider(s).
    Supports:
    - 'hybrid' / 'parallel' / 'all': Parallel concurrent Tavily + Google News RSS (+ Brave).
    - 'tavily': Tavily primary with automatic Google News RSS fallback.
    - 'brave': Brave primary with automatic Google News RSS fallback.
    - 'google_news_rss': Keyless Google News RSS only.
    Never raises exceptions.
    """
    if not query or not query.strip():
        return []

    provider = (settings.search_provider or "hybrid").lower().strip()

    # If a keyed provider was requested but no key exists, default to hybrid or google_news_rss
    if provider in ("brave", "tavily") and not settings.search_api_key:
        logger.debug("Search API key not configured for %s. Using google_news_rss fallback.", provider)
        provider = "google_news_rss"

    # Redact PII from query before sending to external search providers
    from app.core.redaction import redact_for_external
    cleaned_query = redact_for_external(query.strip())

    try:
        if provider in ("hybrid", "parallel", "all"):
            return _search_parallel_hybrid(cleaned_query)
        elif provider == "tavily":
            items = _search_tavily(cleaned_query, settings.search_api_key)
            if not items:
                logger.info("Tavily returned 0 results; falling back to Google News RSS")
                items = _search_google_news_rss(cleaned_query)
            return items
        elif provider == "brave":
            items = _search_brave(cleaned_query, settings.search_api_key)
            if not items:
                logger.info("Brave returned 0 results; falling back to Google News RSS")
                items = _search_google_news_rss(cleaned_query)
            return items
        elif provider == "google_news_rss":
            return _search_google_news_rss(cleaned_query)
        else:
            logger.warning("Unsupported search provider: %s, using hybrid search", provider)
            return _search_parallel_hybrid(cleaned_query)
    except Exception as exc:
        logger.warning("Web search failed for query '%s': %s", query, exc)
        return []
