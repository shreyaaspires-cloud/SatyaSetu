"""
Pydantic v2 data contracts for SatyaSetu pipeline stages.
Guarantees clean schema validation and type safety across all layer boundaries.
"""

from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field

from app.core.constants import InputType, Rating, Tier, Verdict


class IngestedMessage(BaseModel):
    """
    Standardized payload produced by the Ingestion layer.
    """
    model_config = ConfigDict(extra="ignore")

    raw_text: str
    input_type: InputType
    from_number: str = Field(description="SHA-256 hashed sender identity, never raw phone number")
    original_body: str = ""
    ocr_confidence: Optional[float] = None
    audio_duration_sec: Optional[float] = None
    source_url: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class NLPResult(BaseModel):
    """
    Structured analysis produced by the NLP layer.
    """
    model_config = ConfigDict(extra="ignore")

    detected_language: str
    language_confidence: float
    translated_text: str
    claims: list[str] = Field(default_factory=list)
    check_worthiness_score: float = 0.0
    has_forward_pressure: bool = False
    keywords: list[str] = Field(default_factory=list)


class EvidenceItem(BaseModel):
    """
    A single piece of retrieved fact-check or web evidence.
    """
    model_config = ConfigDict(extra="ignore")

    url: str
    title: str
    snippet: str
    source_domain: str
    tier: Tier
    rating: Rating = Rating.UNVERIFIED
    publish_date: Optional[str] = None
    score: float = 0.0
    stance: Optional[str] = None


class ClaimResult(BaseModel):
    """
    Verification outcome for a single claim.
    """
    model_config = ConfigDict(extra="ignore")

    claim: str
    verdict: Verdict
    confidence: float
    reason_code: str
    evidence: list[EvidenceItem] = Field(default_factory=list)
    guard_passed: bool = True


class CheckResponse(BaseModel):
    """
    Complete end-to-end response returned to the caller or API client.
    """
    model_config = ConfigDict(extra="ignore")

    claim_results: list[ClaimResult] = Field(default_factory=list)
    overall_verdict: Verdict
    explanation: str
    formatted_reply: str
    language: str
    timings_ms: dict[str, float] = Field(default_factory=dict)
    cached: bool = False


class WebhookPayload(BaseModel):
    """
    Payload received from Twilio WhatsApp webhook.
    """
    model_config = ConfigDict(extra="ignore")

    From: str = ""
    To: str = ""
    Body: str = ""
    NumMedia: int = 0
    MediaUrl0: Optional[str] = None
    MediaContentType0: Optional[str] = None
    MessageSid: str = ""
    AccountSid: str = ""
