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
from app.core.security import is_public_http_url
from app.features.retrieval.ratings import normalize_rating
from app.features.retrieval.sources import classify_domain

import re

logger = logging.getLogger(__name__)

API_URL = "https://factchecktools.googleapis.com/v1alpha1/claims:search"

_STOPWORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are", "aren't",
    "as", "at", "be", "because", "been", "before", "being", "below", "between", "both", "but", "by",
    "can", "can't", "cannot", "could", "couldn't", "did", "didn't", "do", "does", "doesn't", "doing",
    "don't", "down", "during", "each", "few", "for", "from", "further", "had", "hadn't", "has", "hasn't",
    "have", "haven't", "having", "he", "he'd", "he'll", "he's", "her", "here", "here's", "hers", "herself",
    "him", "himself", "his", "how", "how's", "i", "i'd", "i'll", "i'm", "i've", "if", "in", "into", "is",
    "isn't", "it", "it's", "its", "itself", "let's", "me", "more", "most", "mustn't", "my", "myself", "no",
    "nor", "not", "of", "off", "on", "once", "only", "or", "other", "ought", "our", "ours", "ourselves",
    "out", "over", "own", "same", "shan't", "she", "she'd", "she'll", "she's", "should", "shouldn't", "so",
    "some", "such", "than", "that", "that's", "the", "their", "theirs", "them", "themselves", "then",
    "there", "there's", "these", "they", "they'd", "they'll", "they're", "they've", "this", "those",
    "through", "to", "too", "under", "until", "up", "very", "was", "wasn't", "we", "we'd", "we'll",
    "we're", "we've", "were", "weren't", "what", "what's", "when", "when's", "where", "where's", "which",
    "while", "who", "who's", "whom", "why", "why's", "with", "won't", "would", "wouldn't", "you", "you'd",
    "you'll", "you're", "you've", "your", "yours", "yourself", "yourselves"
}


def _normalize_token(w: str) -> str:
    """Normalize token by lowercasing and stripping common suffixes."""
    w = w.lower()
    for suffix in ("ing", "ies", "es", "ed", "s"):
        if len(w) > len(suffix) + 2 and w.endswith(suffix):
            if suffix == "ies":
                return w[:-3] + "y"
            return w[:-len(suffix)]
    return w


def _extract_content_tokens(text: str) -> set[str]:
    """Extract content word tokens excluding stopwords."""
    raw_tokens = re.findall(r"\b[a-zA-Z0-9_\-]{2,}\b", text.lower())
    return {_normalize_token(t) for t in raw_tokens if t not in _STOPWORDS}


def compute_claim_match_score(claim: str, matched_claim: str) -> float:
    """
    Compute relevance match score (0.0 to 1.0) between user claim and matched claim.
    Uses content word overlap with stopwords removed.
    """
    if not claim or not matched_claim:
        return 0.0

    tokens1 = _extract_content_tokens(claim)
    tokens2 = _extract_content_tokens(matched_claim)

    if not tokens1 or not tokens2:
        return 0.0

    intersection = tokens1 & tokens2
    if not intersection:
        return 0.0

    dice = 2.0 * len(intersection) / (len(tokens1) + len(tokens2))
    overlap_coeff = len(intersection) / min(len(tokens1), len(tokens2))
    lexical_score = max(dice, 0.85 * overlap_coeff)
    return round(min(1.0, max(0.0, lexical_score)), 3)


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

    try:
        data = _fetch_google_fact_check(query.strip(), settings.google_fact_check_api_key)
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

                domain_tier = classify_domain(url)
                match_score = compute_claim_match_score(query, claim_text)
                min_match = settings.factcheck_min_match

                snippet = f"Claim checked: '{claim_text}'. Verdict by {publisher}: {raw_rating}."

                if match_score < min_match:
                    # Below threshold: context only, Tier 5, score capped at 0.3, stance NEUTRAL
                    evidence_items.append(
                        EvidenceItem(
                            url=url,
                            title=title,
                            snippet=snippet,
                            source_domain=source_domain,
                            tier=Tier.TIER_5_GENERAL_WEB,
                            rating=rating,
                            publish_date=publish_date,
                            score=min(match_score, 0.3),
                            stance="NEUTRAL",
                            matched_claim=claim_text,
                            match_score=match_score,
                            reason="RELATED_NOT_SAME",
                        )
                    )
                else:
                    # Relevance gate passed: domain tier preserved, score reflects match relevance
                    evidence_items.append(
                        EvidenceItem(
                            url=url,
                            title=title,
                            snippet=snippet,
                            source_domain=source_domain,
                            tier=domain_tier,
                            rating=rating,
                            publish_date=publish_date,
                            score=round(match_score, 3),
                            matched_claim=claim_text,
                            match_score=match_score,
                        )
                    )

        logger.info("Google Fact Check found %d evidence items for query.", len(evidence_items))
        return evidence_items

    except Exception as exc:
        logger.warning("Google Fact Check retrieval failed for '%s': %s", query, exc)
        return []
