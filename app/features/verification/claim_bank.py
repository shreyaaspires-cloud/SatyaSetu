"""
Verified Claim Bank matching and data loader.
Provides pre-verified verdicts for common viral claims without LLM dependence.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
import yaml

from app.core.constants import Verdict
from app.features.verification.details import check_detail_conflict

logger = logging.getLogger(__name__)

_CLAIM_BANK_CACHE: Optional[List[Dict[str, Any]]] = None


class ClaimBankMatch(BaseModel):
    """Result of matching a claim against the verified claim bank."""
    claim_id: str
    canonical_claim: str
    verdict: Verdict
    confidence: float = 0.98
    explanation: str
    publisher: str
    source_url: str
    published_date: Optional[str] = None
    citation: str
    is_decisive: bool = True


def get_claim_bank_path() -> str:
    """Return the absolute path to data/claim_bank.yaml."""
    base_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..")
    )
    return os.path.join(base_dir, "data", "claim_bank.yaml")


def load_claim_bank(force_reload: bool = False) -> List[Dict[str, Any]]:
    """Load entries from data/claim_bank.yaml."""
    global _CLAIM_BANK_CACHE
    if _CLAIM_BANK_CACHE is not None and not force_reload:
        return _CLAIM_BANK_CACHE

    bank_path = get_claim_bank_path()
    if not os.path.exists(bank_path):
        logger.warning("Claim bank not found at %s", bank_path)
        _CLAIM_BANK_CACHE = []
        return _CLAIM_BANK_CACHE

    try:
        with open(bank_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or []
            _CLAIM_BANK_CACHE = data
            return _CLAIM_BANK_CACHE
    except Exception as exc:
        logger.error("Failed to load claim bank from %s: %s", bank_path, exc)
        _CLAIM_BANK_CACHE = []
        return _CLAIM_BANK_CACHE


def _tokenize(text: str) -> set[str]:
    """Tokenize text into lowercase alpha words, excluding conversational and grammatical stopwords."""
    stopwords = {
        "the", "a", "an", "is", "are", "in", "on", "of", "to", "and", "or", "for", "with",
        "causes", "issue", "issues", "there", "that", "this", "us", "we", "all", "our",
        "only", "him", "her", "he", "she", "it", "they", "them", "from", "at", "by", "be",
        "was", "were", "been", "has", "have", "had", "do", "does", "did", "bad", "news",
    }
    words = re.findall(r"\b[a-zA-Z0-9]{2,}\b", text.lower())
    return {w for w in words if w not in stopwords}


def lookup_claim_bank(claim: str, min_overlap: float = 0.5) -> Optional[ClaimBankMatch]:
    """
    Search claim bank for matching verified claims.
    Enforces:
      1. Expiration check: review_by must not be in the past.
      2. Detail conflict check: check_detail_conflict must return None.
      3. Overlap threshold between query and canonical/variants.
    """
    if not claim or not claim.strip():
        return None

    entries = load_claim_bank()
    today = date.today()
    claim_tokens = _tokenize(claim)
    if not claim_tokens:
        return None

    best_match: Optional[ClaimBankMatch] = None
    highest_score = 0.0

    for entry in entries:
        # 1. Expiration check (AT34)
        review_by_str = entry.get("review_by")
        if review_by_str:
            try:
                review_by_date = datetime.strptime(str(review_by_str), "%Y-%m-%d").date()
                if review_by_date < today:
                    logger.debug("Skipping expired claim bank entry: %s", entry.get("id"))
                    continue
            except Exception:
                pass

        canonical = entry.get("canonical_claim", "")
        variants = entry.get("variants", []) or []
        candidates = [canonical] + variants

        for cand in candidates:
            cand_tokens = _tokenize(cand)
            if not cand_tokens:
                continue

            intersection = claim_tokens.intersection(cand_tokens)
            # Use max of Jaccard and overlap coefficient so long forwards match concise claims
            overlap_coeff = len(intersection) / min(len(claim_tokens), len(cand_tokens))
            jaccard = len(intersection) / max(len(claim_tokens), len(cand_tokens))
            score = max(jaccard, 0.85 * overlap_coeff)

            if score > highest_score and score >= min_overlap:
                # 2. Key detail conflict check (AT33)
                conflict = check_detail_conflict(claim, canonical)
                if conflict is not None:
                    # Key detail mismatch (e.g. east vs north) -> cannot be decisive
                    logger.info("Claim bank candidate '%s' rejected due to detail conflict '%s'", canonical, conflict)
                    continue

                sources = entry.get("sources", [])
                primary_source = sources[0] if sources else {}
                publisher = primary_source.get("publisher", "Independent Fact Checkers")
                url = primary_source.get("url", "")
                pub_date = primary_source.get("published_date", "")

                citation = f"From a published fact check by {publisher}"
                if pub_date:
                    citation += f", {pub_date}"

                verdict_str = entry.get("verdict", "UNVERIFIABLE").upper()
                try:
                    verdict = Verdict(verdict_str)
                except Exception:
                    verdict = Verdict.UNVERIFIABLE

                highest_score = score
                best_match = ClaimBankMatch(
                    claim_id=str(entry.get("id", "")),
                    canonical_claim=canonical,
                    verdict=verdict,
                    confidence=0.98,
                    explanation=entry.get("explanation_en", ""),
                    publisher=publisher,
                    source_url=url,
                    published_date=pub_date,
                    citation=citation,
                    is_decisive=True,
                )

    return best_match
