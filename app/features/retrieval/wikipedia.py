"""
Wikipedia evidence retriever using official Wikipedia REST API.
Enforces timeout, SSRF protection via safe_get, character capping, and D8/D15 fixes.
"""

from __future__ import annotations

import logging
import urllib.parse
from typing import List, Optional

from app.contracts.models import EvidenceItem
from app.core.constants import Rating, Tier
from app.core.security import safe_get

logger = logging.getLogger(__name__)

WIKI_SEARCH_API = "https://en.wikipedia.org/w/api.php"
WIKI_REST_SUMMARY_API = "https://en.wikipedia.org/api/rest_v1/page/summary/"
MAX_SUMMARY_CHARS = 1200


def search_wikipedia(query: str, lang: str = "en") -> List[EvidenceItem]:
    """
    Search Wikipedia for relevant reference articles matching query.
    Returns EvidenceItem list marked as Tier 4 (background reference only).
    D8 fix: query driven without hardcoded topic shortcuts.
    D15 fix: uses safe_get with explicit timeout.
    """
    if not query or not query.strip():
        return []

    from app.core.redaction import redact_for_external
    cleaned_query = redact_for_external(query.strip())
    evidence_items: List[EvidenceItem] = []

    try:
        # Step 1: Search Wikipedia for top matching article titles
        search_params = {
            "action": "query",
            "list": "search",
            "srsearch": cleaned_query,
            "srlimit": 2,
            "format": "json",
        }
        search_url = f"{WIKI_SEARCH_API}?{urllib.parse.urlencode(search_params)}"
        headers = {"User-Agent": "SatyaSetu/1.0 (+https://satyasetu.org; factcheck-bot)"}

        search_resp = safe_get(search_url, timeout=5, headers=headers)
        if search_resp.status_code != 200:
            return []

        search_data = search_resp.json()
        search_results = search_data.get("query", {}).get("search", [])
        if not search_results:
            return []

        # Step 2: Fetch article summaries via Wikipedia REST API
        for result in search_results[:2]:
            title = result.get("title", "")
            if not title:
                continue

            encoded_title = urllib.parse.quote(title.replace(" ", "_"))
            summary_url = f"{WIKI_REST_SUMMARY_API}{encoded_title}"

            try:
                summary_resp = safe_get(summary_url, timeout=5, headers=headers)
                if summary_resp.status_code != 200:
                    continue

                summary_data = summary_resp.json()
                extract = summary_data.get("extract", "")
                page_url = summary_data.get("content_urls", {}).get("desktop", {}).get("page", "")

                if extract and page_url:
                    snippet = extract[:MAX_SUMMARY_CHARS].strip()
                    evidence_items.append(
                        EvidenceItem(
                            url=page_url,
                            title=f"Wikipedia: {title}",
                            snippet=snippet,
                            source_domain="en.wikipedia.org",
                            tier=Tier.TIER_4_WIKIPEDIA,
                            rating=Rating.UNVERIFIED,
                            score=0.70,
                        )
                    )
            except Exception as exc:
                logger.debug("Failed fetching Wikipedia summary for %s: %s", title, exc)

        logger.info("Wikipedia retrieval found %d evidence articles.", len(evidence_items))
        return evidence_items

    except Exception as exc:
        logger.warning("Wikipedia retrieval failed for '%s': %s", query, exc)
        return []
