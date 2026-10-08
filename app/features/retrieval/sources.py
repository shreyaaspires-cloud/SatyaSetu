"""
Source domain classification and tier assignment.
Loads domain tiers from config/sources.yaml to categorize evidence reliability.
"""

from __future__ import annotations

import logging
import os
from urllib.parse import urlparse
from typing import Dict, List, Optional

import yaml

from app.core.constants import Tier

logger = logging.getLogger(__name__)

# In-memory cached source definitions
_sources_cache: Optional[Dict[str, List[str]]] = None


def get_sources_config_path() -> str:
    """Return the absolute path to config/sources.yaml."""
    base_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..")
    )
    return os.path.join(base_dir, "config", "sources.yaml")


def load_sources_config() -> Dict[str, List[str]]:
    """
    Load tiered domain lists from config/sources.yaml.
    Falls back to embedded defaults if file is unavailable.
    """
    global _sources_cache
    if _sources_cache is not None:
        return _sources_cache

    config_path = get_sources_config_path()
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
                _sources_cache = data
                return _sources_cache
        except Exception as exc:
            logger.warning("Failed to load %s: %s. Using default sources.", config_path, exc)

    # Embedded fallback
    _sources_cache = {
        "tier_1_ifcn": [
            "altnews.in", "boomlive.in", "factly.in", "thequint.com",
            "vishvasnews.com", "newschecker.in", "thip.media", "factcheck.org",
            "politifact.com", "snopes.com", "reuters.com", "afp.com",
        ],
        "tier_2_gov_pib": [
            "pib.gov.in", "mygov.in", "mohfw.gov.in", "icmr.gov.in", "who.int",
            "rbi.org.in", "npci.org.in", "cert-in.org.in", "sebi.gov.in", "uidai.gov.in",
            "india.gov.in", "incometax.gov.in", "incometaxindia.gov.in",
            "isro.gov.in", "ecisveep.nic.in",
        ],
        "tier_3_mainstream": [
            "thehindu.com", "indianexpress.com", "bbc.com", "bbc.co.uk",
            "ndtv.com", "apnews.com", "hindustantimes.com", "timesofindia.indiatimes.com",
        ],
        "tier_4_wikipedia": [
            "wikipedia.org", "en.wikipedia.org", "hi.wikipedia.org",
        ],
    }
    return _sources_cache


def classify_domain(url: str) -> Tier:
    """
    Extract hostname from URL and classify into its corresponding Tier.
    Defaults to Tier.TIER_5_GENERAL_WEB for unlisted domains.
    """
    if not url:
        return Tier.TIER_5_GENERAL_WEB

    try:
        parsed = urlparse(url)
        netloc = (parsed.netloc or "").lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]

        if not netloc:
            return Tier.TIER_5_GENERAL_WEB

        sources = load_sources_config()

        def _matches(domain_list: List[str]) -> bool:
            for d in domain_list:
                d = d.lower().strip()
                if netloc == d or netloc.endswith("." + d):
                    return True
            return False

        if _matches(sources.get("tier_1_ifcn", [])):
            return Tier.TIER_1_IFCN
        if _matches(sources.get("tier_2_gov_pib", [])):
            return Tier.TIER_2_GOV_PIB
        if _matches(sources.get("tier_3_mainstream", [])):
            return Tier.TIER_3_MAINSTREAM
        if _matches(sources.get("tier_4_wikipedia", [])):
            return Tier.TIER_4_WIKIPEDIA

        return Tier.TIER_5_GENERAL_WEB
    except Exception as exc:
        logger.debug("Failed to classify domain for %s: %s", url, exc)
        return Tier.TIER_5_GENERAL_WEB
