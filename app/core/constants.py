"""
System-wide enums and constants for SatyaSetu.

Defines foundational vocabulary and typing contracts across the system:
- InputType: Permitted inbound payload modalities for ingestion demuxing.
- Tier: Source authority hierarchy for confidence weighting and conflict resolution.
- Rating: Normalized fact-check verdict ratings reported by external investigative sources.
- Verdict: Canonical system verdicts rendered by the synthesis and arbitration engines.
"""

from enum import Enum


class InputType(str, Enum):
    """Supported multimodal input channels for inbound message processing."""
    TEXT = "text"
    SCREENSHOT = "screenshot"
    VOICE = "voice"
    PDF = "pdf"
    URL = "url"



class Tier(str, Enum):
    TIER_1_IFCN = "tier_1_ifcn"
    TIER_2_GOV_PIB = "tier_2_gov_pib"
    TIER_3_MAINSTREAM = "tier_3_mainstream"
    TIER_4_WIKIPEDIA = "tier_4_wikipedia"
    TIER_5_GENERAL_WEB = "tier_5_general_web"


class Rating(str, Enum):
    TRUE = "TRUE"
    FALSE = "FALSE"
    MISLEADING = "MISLEADING"
    PARTLY_TRUE = "PARTLY_TRUE"
    OUTDATED = "OUTDATED"
    UNVERIFIED = "UNVERIFIED"


class Verdict(str, Enum):
    SUPPORTED = "SUPPORTED"
    REFUTED = "REFUTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    OUTDATED = "OUTDATED"
    UNVERIFIABLE = "UNVERIFIABLE"


# Default supported languages across Indic models
SUPPORTED_INDIC_LANGS = ("hi", "mr", "ta", "te", "bn", "en")
