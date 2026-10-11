"""
API request and response models for public-facing JSON endpoints.
Strictly decoupled from internal pipeline and DB models.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class CheckRequest(BaseModel):
    """Payload for POST /api/check."""
    model_config = ConfigDict(extra="ignore")
    text: Optional[str] = None
    claim: Optional[str] = None
    language: Optional[str] = "en"


class EvidenceItemAPI(BaseModel):
    """Public representation of an evidence item."""
    model_config = ConfigDict(extra="ignore")
    title: str = ""
    url: str = ""
    domain: str = ""
    snippet: str = ""
    tier: str = ""
    rating: str = ""
    score: float = 0.0


class CheckAPIResponse(BaseModel):
    """
    Public response model for POST /api/check.
    Does not invent fake confidence scores or synthetic fallbacks.
    Truthful evidence strength derived from verified source tiers.
    """
    model_config = ConfigDict(extra="ignore")
    verdict: str
    verdict_label: str = ""
    verdict_emoji: str = ""
    evidence_strength: str = "Insufficient"
    evidence_strength_detail: str = ""
    explanation: str = ""
    formatted_reply: str = ""
    claim: str = ""
    claim_results: List[Any] = Field(default_factory=list)
    evidence: List[Dict[str, Any]] = Field(default_factory=list)
    flags: List[str] = Field(default_factory=list)
    timings_ms: Dict[str, float] = Field(default_factory=dict)
    language: str = "en"
