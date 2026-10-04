"""
System-wide enums and constants for SatyaSetu.
"""

from enum import Enum


class InputType(str, Enum):
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
    UNVERIFIED = "UNVERIFIED"


class Verdict(str, Enum):
    SUPPORTED = "SUPPORTED"
    REFUTED = "REFUTED"
    MISLEADING = "MISLEADING"
    UNVERIFIABLE = "UNVERIFIABLE"


# Default supported languages across Indic models
SUPPORTED_INDIC_LANGS = ("hi", "mr", "ta", "te", "bn", "en")
