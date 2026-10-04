"""
Base interface protocol for evidence retrieval providers.
"""

from typing import List, Protocol
from app.contracts.models import EvidenceItem


class Retriever(Protocol):
    """Protocol for evidence retrieval backends."""

    def retrieve(self, query: str) -> List[EvidenceItem]:
        """Retrieve evidence items matching the given query."""
        ...
