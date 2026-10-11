"""
app/features/retrieval/orchestrator.py
────────────────────────────────────────
Retrieval orchestrator.
Executes parallel evidence retrieval across Google Fact Check, Wikipedia, and Web search
under strict time budget constraints with deduplication and tier-based sorting.

Architecture
─────────────
The orchestrator is the single public entry-point for all evidence retrieval.
It spins up a ThreadPoolExecutor and fans out to up to four sources concurrently:

  1. Google Fact Check API   — IFCN-certified verdict data (Tier 1).
  2. Official sources search — Government / health domain PSE (Tier 2).
                               Only launched when route_claim_topic() detects
                               a relevant topic (health, finance, gov scheme…).
  3. General web search      — Brave / Tavily (Tier 3–5).
  4. Wikipedia               — Background context (Tier 4).

All futures are awaited under a hard timeout (`retrieval_budget_ms`).  Sources
that exceed the budget are cancelled rather than awaited to ensure overall
pipeline latency stays within acceptable bounds.

Caching
────────
Evidence results are stored in an in-memory TTL cache keyed by a normalised
claim string (lowercased, whitespace-collapsed).  Default TTL = 10 minutes.
This prevents hammering APIs when the same viral claim arrives via multiple
WhatsApp users in a short burst.

Deduplication
──────────────
The same article may be returned by multiple sources (e.g., an AltNews article
appearing in both the Google Fact Check API and a web search result).
Deduplication is performed by a normalised URL key:
  • Strip www. prefix.
  • Strip trailing slashes.
This keeps only the first occurrence (earliest-retrieved, likely highest tier).

Sort order
───────────
Tier ascending (Tier 1 best) then score descending within the same tier.
The TIER_ORDER dict maps Tier enum values to integer ranks.
"""

from __future__ import annotations

import concurrent.futures
import logging
import threading
import time
from typing import Dict, List, Optional
from urllib.parse import urlparse

from app.contracts.models import EvidenceItem
from app.core.config import settings
from app.core.constants import Tier
from app.features.retrieval.factcheck_google import search_google_fact_check
from app.features.retrieval.official_search import route_claim_topic, search_official_sources
from app.features.retrieval.search_web import search_web
from app.features.retrieval.wikipedia import search_wikipedia

logger = logging.getLogger(__name__)

# Tier rank map: lower integer = higher trust.
# Used as the primary sort key for the final deduped evidence list.
TIER_ORDER: Dict[Tier, int] = {
    Tier.TIER_1_IFCN: 0,
    Tier.TIER_2_GOV_PIB: 1,
    Tier.TIER_3_MAINSTREAM: 2,
    Tier.TIER_4_WIKIPEDIA: 3,
    Tier.TIER_5_GENERAL_WEB: 4,
}

# ── TTL evidence cache ────────────────────────────────────────────────────────
# In-process cache keyed by normalised claim string.
# Thread-safe access via _CACHE_LOCK.
# Stored value: (expires_at: float, items: List[EvidenceItem])
_CACHE_LOCK = threading.Lock()
_EVIDENCE_CACHE: Dict[str, tuple[float, List[EvidenceItem]]] = {}
DEFAULT_CACHE_TTL_SEC: float = 600.0  # 10 minutes


def normalize_claim_for_cache(claim: str) -> str:
    """
    Normalize claim string for caching.
    Lowercases and collapses whitespace so minor formatting variations
    ('COVID vaccine' vs 'covid  vaccine') map to the same cache key.
    """
    return " ".join(claim.strip().lower().split())


def clear_evidence_cache() -> None:
    """Clear all entries from the evidence TTL cache."""
    with _CACHE_LOCK:
        _EVIDENCE_CACHE.clear()


def get_cached_evidence(claim: str) -> Optional[List[EvidenceItem]]:
    """
    Retrieve unexpired cached evidence for the given claim.
    Returns items marked with from_cache=True, or None if missing/expired.

    Expired entries are eagerly evicted on access (lazy expiration).
    The from_cache flag allows callers to skip re-logging or re-scoring.
    """
    norm_key = normalize_claim_for_cache(claim)
    with _CACHE_LOCK:
        entry = _EVIDENCE_CACHE.get(norm_key)
        if entry is None:
            return None
        expires_at, items = entry
        if time.monotonic() > expires_at:
            # Lazy eviction: remove stale entry on access.
            _EVIDENCE_CACHE.pop(norm_key, None)
            return None
        return [item.model_copy(update={"from_cache": True}) for item in items]


def set_cached_evidence(claim: str, items: List[EvidenceItem], ttl_sec: float = DEFAULT_CACHE_TTL_SEC) -> None:
    """
    Store evidence items in the TTL cache for the given claim.
    Uses monotonic time so wall-clock adjustments (DST, NTP) don't corrupt expiry.
    """
    norm_key = normalize_claim_for_cache(claim)
    with _CACHE_LOCK:
        _EVIDENCE_CACHE[norm_key] = (time.monotonic() + ttl_sec, items)


def normalize_url_for_dedupe(url: str) -> str:
    """
    Normalize a URL to prevent duplicate evidence items.
    Strips www. prefix and trailing slashes; lowercases the entire URL.
    """
    try:
        parsed = urlparse(url.strip().lower())
        netloc = parsed.netloc
        if netloc.startswith("www."):
            netloc = netloc[4:]
        path = parsed.path.rstrip("/")
        return f"{netloc}{path}"
    except Exception:
        return url.strip().lower()


def retrieve_evidence(
    claim: str,
    keywords: Optional[List[str]] = None,
    budget_ms: Optional[int] = None,
) -> List[EvidenceItem]:
    """
    Orchestrate multi-source evidence retrieval in parallel with hard time budget.
    Checks TTL cache first; on miss, fetches sources concurrently.
    Deduplicates URLs and sorts by tier hierarchy and score.

    Parameters
    ──────────
    claim      : English-language claim text (PII already redacted).
    keywords   : Optional keyphrases extracted by KeyBERT; first 3 used as
                 Wikipedia query to improve topical precision.
    budget_ms  : Hard timeout in milliseconds; defaults to settings.retrieval_budget_ms.

    Thread safety
    ──────────────
    Each source is executed in its own thread.  The executor is shut down with
    cancel_futures=True after the budget expires so stale threads don't
    accumulate across requests.  Python 3.9+ supports cancel_futures; earlier
    versions fall back to shutdown(wait=False).
    """
    if not claim or not claim.strip():
        return []

    # PII-redact before any external dispatch or cache key construction.
    from app.core.redaction import redact_for_external
    cleaned_claim = redact_for_external(claim.strip())

    # Check evidence cache first; avoids API round-trips on repeated claims.
    cached = get_cached_evidence(cleaned_claim)
    if cached is not None:
        logger.info("Serving %d evidence items from cache for claim: '%s'", len(cached), cleaned_claim[:40])
        return cached

    timeout_sec = (budget_ms or settings.retrieval_budget_ms) / 1000.0
    # Wikipedia query: use first 3 keywords if available for better precision.
    wiki_query = " ".join(keywords[:3]) if (keywords and len(keywords) > 0) else cleaned_claim

    collected_evidence: List[EvidenceItem] = []

    # Determine whether a topic-specific official search is warranted.
    topic, official_domains = route_claim_topic(cleaned_claim)

    # Scale thread pool to source count.
    max_workers = 4 if official_domains else 3
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
    try:
        future_google = executor.submit(search_google_fact_check, cleaned_claim)
        future_wiki = executor.submit(search_wikipedia, wiki_query)
        future_web = executor.submit(search_web, cleaned_claim)

        futures_map = {
            future_google: "google_fact_check",
            future_wiki: "wikipedia",
            future_web: "web_search",
        }
        if official_domains:
            # Official search is additive; launched only for health/gov/finance claims.
            future_official = executor.submit(search_official_sources, cleaned_claim, official_domains)
            futures_map[future_official] = f"official_search_{topic}"

        done, not_done = concurrent.futures.wait(
            futures_map.keys(),
            timeout=timeout_sec,
            return_when=concurrent.futures.ALL_COMPLETED,
        )

        # Log and cancel sources that breached the time budget.
        for f in not_done:
            name = futures_map[f]
            logger.warning("Retrieval source '%s' exceeded timeout budget (%.1fs). Cancelled.", name, timeout_sec)
            f.cancel()

        for f in done:
            name = futures_map[f]
            try:
                items = f.result()
                if items:
                    collected_evidence.extend(items)
            except Exception as exc:
                logger.warning("Retrieval source '%s' failed: %s", name, exc)
    finally:
        # Non-blocking executor shutdown avoids waiting for slow threads.
        try:
            executor.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            # Python < 3.9 doesn't support cancel_futures keyword.
            executor.shutdown(wait=False)

    # Deduplicate by normalised URL, keeping the first occurrence
    # (which will be the highest-tier result due to fan-out ordering).
    seen_urls: set = set()
    deduped_evidence: List[EvidenceItem] = []

    for item in collected_evidence:
        norm_url = normalize_url_for_dedupe(item.url)
        if norm_url and norm_url not in seen_urls:
            seen_urls.add(norm_url)
            deduped_evidence.append(item)

    # Sort items: Tier priority first (Tier 1 → Tier 2 → …), then score descending.
    def _sort_key(item: EvidenceItem):
        tier_rank = TIER_ORDER.get(item.tier, 99)
        score_rank = -item.score
        return (tier_rank, score_rank)

    deduped_evidence.sort(key=_sort_key)

    # Cache the sorted, deduped result set for future identical claims.
    set_cached_evidence(cleaned_claim, deduped_evidence)

    logger.info("Total deduped evidence items retrieved: %d", len(deduped_evidence))
    return deduped_evidence
