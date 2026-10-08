"""
Google Fact Check Tools API retriever.
Queries published fact checks from IFCN signatories and reputable journalists.
Enforces timeout, HTTP status checks, tenacity retry, and D10 fixes.
"""

from __future__ import annotations

import logging
from typing import List
from urllib.parse import urlparse

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.contracts.models import EvidenceItem
from app.core.config import settings
from app.core.constants import Rating, Tier
from app.core.redaction import redact_for_external
from app.core.security import is_public_http_url
from app.features.retrieval.ratings import normalize_rating
from app.features.retrieval.sources import classify_domain

logger = logging.getLogger(__name__)

API_URL = "https://factchecktools.googleapis.com/v1alpha1/claims:search"


@retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=2.0),
    retry=retry_if_exception_type((requests.RequestException,)),
    reraise=True,
)
def _fetch_google_fact_check(query: str, api_key: str) -> dict:
    """Fetch claims from Google Fact Check API with retry and timeout."""
    params = {
        "query": query,
        "key": api_key,
        "languageCode": "en",
    }
    resp = requests.get(API_URL, params=params, timeout=3.0)
    resp.raise_for_status()
    return resp.json()


def search_google_fact_check(query: str) -> List[EvidenceItem]:
    """
    Search Google Fact Check API for verified claim reviews matching query.
    Returns a list of structured EvidenceItem objects.
    Never raises exceptions.
    """
    if not settings.google_fact_check_api_key:
        logger.debug("Google Fact Check API key not configured. Skipping.")
        return []

    if not query or not query.strip():
        return []

    cleaned_query = redact_for_external(query.strip())

    try:
        data = _fetch_google_fact_check(cleaned_query, settings.google_fact_check_api_key)
        claims = data.get("claims", [])
        evidence_items: List[EvidenceItem] = []

        for item in claims:
            claim_text = item.get("text", "")
            reviews = item.get("claimReview", [])
            if not reviews:
                continue

            for review in reviews:
                url = review.get("url", "")
                if not url or not is_public_http_url(url):
                    continue

                publisher = review.get("publisher", {}).get("name", "")
                title = review.get("title") or f"{publisher} Fact Check"
                raw_rating = review.get("textualRating", "")
                rating = normalize_rating(raw_rating)
                publish_date = review.get("reviewDate")

                source_domain = (urlparse(url).netloc or "").lower()
                if source_domain.startswith("www."):
                    source_domain = source_domain[4:]

                tier = classify_domain(url)
                # Google Fact Check reviews are from certified publishers (Tier 1 or Tier 2)
                if tier not in (Tier.TIER_1_IFCN, Tier.TIER_2_GOV_PIB):
                    tier = Tier.TIER_1_IFCN

                snippet = f"Claim checked: '{claim_text}'. Verdict by {publisher}: {raw_rating}."

                evidence_items.append(
                    EvidenceItem(
                        url=url,
                        title=title,
                        snippet=snippet,
                        source_domain=source_domain,
                        tier=tier,
                        rating=rating,
                        publish_date=publish_date,
                        score=0.95,
                    )
                )

        logger.info("Google Fact Check found %d evidence items for query.", len(evidence_items))
        return evidence_items

    except Exception as exc:
        logger.warning("Google Fact Check retrieval failed for '%s': %s", query, exc)
        return []
