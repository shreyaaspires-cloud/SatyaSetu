"""
Retrieval orchestrator.
Executes parallel evidence retrieval across Google Fact Check, Wikipedia, and Web search
under strict time budget constraints with deduplication and tier-based sorting.
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
from app.features.retrieval.search_web import search_web
from app.features.retrieval.wikipedia import search_wikipedia

logger = logging.getLogger(__name__)

TIER_ORDER: Dict[Tier, int] = {
    Tier.TIER_1_IFCN: 0,
    Tier.TIER_2_GOV_PIB: 1,
    Tier.TIER_3_MAINSTREAM: 2,
    Tier.TIER_4_WIKIPEDIA: 3,
    Tier.TIER_5_GENERAL_WEB: 4,
}

# In-memory evidence cache with TTL (10 minutes default)
_CACHE_LOCK = threading.Lock()
_EVIDENCE_CACHE: Dict[str, tuple[float, List[EvidenceItem]]] = {}
DEFAULT_CACHE_TTL_SEC: float = 600.0


def normalize_claim_for_cache(claim: str) -> str:
    """Normalize claim string for caching."""
    return " ".join(claim.strip().lower().split())


def clear_evidence_cache() -> None:
    """Clear all entries from the evidence TTL cache."""
    with _CACHE_LOCK:
        _EVIDENCE_CACHE.clear()


def get_cached_evidence(claim: str) -> Optional[List[EvidenceItem]]:
    """
    Retrieve unexpired cached evidence for the given claim.
    Returns items marked with from_cache=True, or None if missing/expired.
    """
    norm_key = normalize_claim_for_cache(claim)
    with _CACHE_LOCK:
        entry = _EVIDENCE_CACHE.get(norm_key)
        if entry is None:
            return None
        expires_at, items = entry
        if time.monotonic() > expires_at:
            _EVIDENCE_CACHE.pop(norm_key, None)
            return None
        return [item.model_copy(update={"from_cache": True}) for item in items]


def set_cached_evidence(claim: str, items: List[EvidenceItem], ttl_sec: float = DEFAULT_CACHE_TTL_SEC) -> None:
    """Store evidence items in the TTL cache for the given claim."""
    norm_key = normalize_claim_for_cache(claim)
    with _CACHE_LOCK:
        _EVIDENCE_CACHE[norm_key] = (time.monotonic() + ttl_sec, items)


def normalize_url_for_dedupe(url: str) -> str:
    """Normalize a URL to prevent duplicate evidence items."""
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
    """
    if not claim or not claim.strip():
        return []

    cleaned_claim = claim.strip()

    # Check evidence cache first
    cached = get_cached_evidence(cleaned_claim)
    if cached is not None:
        logger.info("Serving %d evidence items from cache for claim: '%s'", len(cached), cleaned_claim[:40])
        return cached

    timeout_sec = (budget_ms or settings.retrieval_budget_ms) / 1000.0
    wiki_query = " ".join(keywords[:3]) if (keywords and len(keywords) > 0) else cleaned_claim

    collected_evidence: List[EvidenceItem] = []

    # Non-blocking executor shutdown avoids waiting for slow threads
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=3)
    try:
        future_google = executor.submit(search_google_fact_check, cleaned_claim)
        future_wiki = executor.submit(search_wikipedia, wiki_query)
        future_web = executor.submit(search_web, cleaned_claim)

        futures_map = {
            future_google: "google_fact_check",
            future_wiki: "wikipedia",
            future_web: "web_search",
        }

        done, not_done = concurrent.futures.wait(
            futures_map.keys(),
            timeout=timeout_sec,
            return_when=concurrent.futures.ALL_COMPLETED,
        )

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
        try:
            executor.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            executor.shutdown(wait=False)

    # Deduplicate by normalized URL, keeping the item with higher score / better tier
    seen_urls: set = set()
    deduped_evidence: List[EvidenceItem] = []

    for item in collected_evidence:
        norm_url = normalize_url_for_dedupe(item.url)
        if norm_url and norm_url not in seen_urls:
            seen_urls.add(norm_url)
            deduped_evidence.append(item)

    # Sort items: Tier priority first (Tier 1 -> Tier 2 -> ...), then score descending
    def _sort_key(item: EvidenceItem):
        tier_rank = TIER_ORDER.get(item.tier, 99)
        score_rank = -item.score
        return (tier_rank, score_rank)

    deduped_evidence.sort(key=_sort_key)

    # Store in TTL cache (evidence only, never verdicts)
    set_cached_evidence(cleaned_claim, deduped_evidence)

    logger.info("Total deduped evidence items retrieved: %d", len(deduped_evidence))
    return deduped_evidence
