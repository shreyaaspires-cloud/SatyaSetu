"""
Evidence retrieval feature package for SatyaSetu.
Provides tiered multi-source retrieval across fact checkers, official sources, and web.
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
