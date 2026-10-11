"""
app/features/retrieval/base.py
───────────────────────────────
Base interface protocol for evidence retrieval providers.

Design
───────
Using typing.Protocol (structural subtyping) rather than ABC allows retriever
implementations to satisfy the interface without explicit inheritance.  This
makes dependency injection in tests trivial: any object that exposes a
`retrieve(query: str) -> List[EvidenceItem]` method is a valid Retriever.

Implementors
─────────────
  FactCheckGoogleRetriever  — Google Fact Check Tools API
  OfficialSearchRetriever   — Programmable Search Engine (gov/pib tier)
  SearchWebRetriever        — General web search
  WikipediaRetriever        — Wikipedia article summaries
"""

from typing import List, Protocol
from app.contracts.models import EvidenceItem


class Retriever(Protocol):
    """
    Protocol for evidence retrieval backends.

    All concrete retriever classes must implement this method signature.
    The orchestrator (retrieval/orchestrator.py) iterates over a list of
    Retriever instances without knowing their concrete types.
    """

    def retrieve(self, query: str) -> List[EvidenceItem]:
        """
        Retrieve evidence items matching the given query.

        Parameters
        ──────────
        query : English-language search string derived from the verified claim.

        Returns
        ───────
        List of EvidenceItem domain objects, ranked by relevance.
        Empty list is a valid return (no evidence found).
        """
        ...
