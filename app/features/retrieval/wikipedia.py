"""
app/features/retrieval/wikipedia.py
─────────────────────────────────────
Wikipedia evidence retriever using official Wikipedia REST API.
Enforces timeout, SSRF protection via safe_get, character capping, and D8/D15 fixes.

Role in the pipeline
─────────────────────
Wikipedia articles provide background context for claims rather than authoritative
verdicts.  All results are tagged Tier.TIER_4_WIKIPEDIA and Rating.UNVERIFIED so
the scoring layer weights them appropriately — Wikipedia cannot itself confirm or
deny a specific recent news claim, but it can supply encyclopedic context about
the entities involved (organisations, chemicals, events).

Security (D15 fix)
───────────────────
* All HTTP calls go through app.core.security.safe_get() which:
    - Validates the target URL against an allowlist (wikipedia.org).
    - Blocks SSRF redirects to cloud metadata endpoints (169.254.169.254 etc.).
    - Enforces a hard 5-second socket timeout.
* Query text is PII-redacted (redact_for_external) before being sent to the
  Wikipedia API so phone numbers and Aadhaar IDs in user input never reach
  external services.

Content limits
───────────────
MAX_SUMMARY_CHARS = 1200 limits the extract payload returned per article.
Wikipedia REST summaries can be several thousand characters; truncating at 1200
prevents the explanation generator from receiving an excessively long context
window that would inflate LLM token costs.
"""

from __future__ import annotations

import logging
import sys
import urllib.parse
from typing import List, Optional

from app.contracts.models import EvidenceItem
from app.core.constants import Rating, Tier
from app.core.security import safe_get

logger = logging.getLogger(__name__)

# Wikipedia API endpoints — pinned to English edition; can be parameterised for
# multilingual retrieval if Indic Wikipedia coverage improves in future.
WIKI_SEARCH_API = "https://en.wikipedia.org/w/api.php"
WIKI_REST_SUMMARY_API = "https://en.wikipedia.org/api/rest_v1/page/summary/"

# Cap article extract at 1200 chars to avoid bloating the explanation context window.
MAX_SUMMARY_CHARS = 1200


def search_wikipedia(query: str, lang: str = "en") -> List[EvidenceItem]:
    """
    Search Wikipedia for relevant reference articles matching query.
    Returns EvidenceItem list marked as Tier 4 (background reference only).

    D8 fix: query is driven entirely by the extracted claim text without
            hardcoded topic shortcuts that would bias retrieval results.
    D15 fix: uses safe_get with explicit timeout to prevent SSRF and hanging.

    Two-step workflow
    ──────────────────
    1. MediaWiki Action API (action=query&list=search) — returns article titles.
    2. Wikipedia REST v1 summary endpoint — returns extract + canonical URL.

    Returns up to 2 EvidenceItem objects (srlimit=2).  More results add noise
    without meaningfully improving the verdict for short claims.
    """
    if not query or not query.strip():
        return []

    # PII redaction before external dispatch (D15 compliance).
    from app.core.redaction import redact_for_external
    cleaned_query = redact_for_external(query.strip())
    evidence_items: List[EvidenceItem] = []

    try:
        # Step 1: Search Wikipedia for top matching article titles.
        search_params = {
            "action": "query",
            "list": "search",
            "srsearch": cleaned_query,
            "srlimit": 2,
            "format": "json",
        }
        search_url = f"{WIKI_SEARCH_API}?{urllib.parse.urlencode(search_params)}"
        # Bot-identification User-Agent per Wikipedia API etiquette guidelines.
        headers = {"User-Agent": "SatyaSetu/1.0 (+https://satyasetu.org; factcheck-bot)"}

        search_resp = safe_get(search_url, timeout=5, headers=headers)
        if search_resp.status_code != 200:
            return []

        search_data = search_resp.json()
        search_results = search_data.get("query", {}).get("search", [])
        if not search_results:
            return []

        # Step 2: Fetch article summaries via Wikipedia REST API.
        for result in search_results[:2]:
            title = result.get("title", "")
            if not title:
                continue

            # URL-encode title for REST endpoint; spaces → underscores per Wikipedia convention.
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
                    # Truncate extract to limit downstream token cost.
                    snippet = extract[:MAX_SUMMARY_CHARS].strip()
                    evidence_items.append(
                        EvidenceItem(
                            url=page_url,
                            title=f"Wikipedia: {title}",
                            snippet=snippet,
                            source_domain="en.wikipedia.org",
                            tier=Tier.TIER_4_WIKIPEDIA,
                            rating=Rating.UNVERIFIED,
                            # score=0.70: Wikipedia provides context but not a verdict.
                            score=0.70,
                        )
                    )
            except Exception as exc:
                logger.debug("Failed fetching Wikipedia summary for %s: %s", title, exc)

        return evidence_items

    except Exception as exc:
        logger.warning("Wikipedia retrieval failed for '%s': %s", query, exc)
        return []
