"""
Evidence retrieval feature package for SatyaSetu.

Implements a five-tier trust hierarchy for evidence sourcing:
- Tier 1 (IFCN): Google Fact Check Tools API — professional, peer-reviewed fact checks.
- Tier 2 (Gov/PIB): Official government domain searches via site: query restriction.
- Tier 3 (Mainstream): Reputable news publishers (The Hindu, BBC, Reuters, etc.).
- Tier 4 (Wikipedia): Encyclopedia summaries with editorial gatekeeping.
- Tier 5 (Web): General search results used as contextual background.

Fan-out concurrency: retrieval across all tiers runs in parallel via ThreadPoolExecutor.
"""

from app.features.retrieval.base import Retriever
from app.features.retrieval.factcheck_google import search_google_fact_check
from app.features.retrieval.orchestrator import retrieve_evidence
from app.features.retrieval.ratings import normalize_rating
from app.features.retrieval.search_web import search_web
from app.features.retrieval.sources import classify_domain
from app.features.retrieval.wikipedia import search_wikipedia

__all__ = [
    "Retriever",
    "classify_domain",
    "normalize_rating",
    "retrieve_evidence",
    "search_google_fact_check",
    "search_web",
    "search_wikipedia",
]
