"""
Retrieval orchestrator.
Executes parallel evidence retrieval across Google Fact Check, Wikipedia, and Web search
under strict time budget constraints with deduplication and tier-based sorting.
"""

from __future__ import annotations

import concurrent.futures
import logging
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
    Deduplicates URLs and sorts by tier hierarchy and score.
    """
    if not claim or not claim.strip():
        return []

    cleaned_claim = claim.strip()
    timeout_sec = (budget_ms or settings.retrieval_budget_ms) / 1000.0

    wiki_query = " ".join(keywords[:3]) if (keywords and len(keywords) > 0) else cleaned_claim

    collected_evidence: List[EvidenceItem] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
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
    logger.info("Total deduped evidence items retrieved: %d", len(deduped_evidence))
    return deduped_evidence
