"""
app/features/retrieval/sources.py
──────────────────────────────────
Source domain classification and tier assignment.
Loads domain tiers from config/sources.yaml to categorize evidence reliability.

Tier system
────────────
Evidence credibility in SatyaSetu is expressed as a five-level tier:

  Tier 1 (IFCN)        — International Fact Checking Network certified outlets
                          (AltNews, BoomLive, Factly, PolitiFact, Snopes, Reuters…).
  Tier 2 (Gov / PIB)   — Official government and public-health bodies
                          (pib.gov.in, who.int, rbi.org.in, uidai.gov.in…).
  Tier 3 (Mainstream)  — Established news organizations with editorial oversight
                          (The Hindu, Indian Express, BBC, NDTV…).
  Tier 4 (Wikipedia)   — Collaboratively edited encyclopedia; useful for background
                          but lacks primary-source authority.
  Tier 5 (General Web) — All other domains; treated with lowest confidence.

Configuration
──────────────
Tiers are loaded from config/sources.yaml at first call and then cached in
_sources_cache for the process lifetime.  Updating the YAML file requires an
application restart to take effect.  The embedded fallback list ensures the
service remains functional if the config file is missing (e.g., Docker image
built without config volume mount).

Domain matching
────────────────
`www.` prefixes are stripped before comparison.  Subdomain matching is suffix-
based (`netloc.endswith("." + d)`) so `health.who.int` correctly maps to the
`who.int` Tier 2 entry.
"""

from __future__ import annotations

import logging
import os
from urllib.parse import urlparse
from typing import Dict, List, Optional

import yaml

from app.core.constants import Tier

logger = logging.getLogger(__name__)

# In-memory cached source definitions.
# Populated on first call to load_sources_config(); never evicted (stable list).
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

    Caching: the parsed YAML dict is stored in _sources_cache so repeated calls
    within the same process pay no I/O cost after the first invocation.
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

    # Embedded fallback — mirrors config/sources.yaml; kept in sync manually.
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

    Steps
    ──────
    1. Parse URL with urlparse() to extract netloc.
    2. Strip leading 'www.' prefix.
    3. Walk tiers 1-4 in descending trust order; return on first match.
    4. Fall through to TIER_5_GENERAL_WEB.

    All exceptions are silently caught to ensure this function never raises:
    evidence scoring must degrade gracefully, not abort the pipeline.
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
                # Exact match OR subdomain: health.who.int matches who.int
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
