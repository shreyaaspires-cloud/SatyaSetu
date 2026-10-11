"""
Contracts package — Pydantic data models and API schemas for SatyaSetu.

Provides the single source of truth for all inter-layer data shapes:
- IngestedMessage: Normalised inbound payload from any modality.
- ClaimResult: Structured per-claim verification outcome with evidence and confidence.
- EvidenceItem: Individual retrieved source with tier, rating, stance, and metadata.
- CheckResponse / NLPResult / WebhookPayload: HTTP API and Twilio request contracts.

Downstream modules MUST import contract types from this package to guarantee
schema consistency across ingestion, NLP, retrieval, verification, and explanation layers.
"""

from app.contracts.models import (
    CheckResponse,
    ClaimResult,
    EvidenceItem,
    IngestedMessage,
    NLPResult,
    WebhookPayload,
)

__all__ = [
    "CheckResponse",
    "ClaimResult",
    "EvidenceItem",
    "IngestedMessage",
    "NLPResult",
    "WebhookPayload",
]
