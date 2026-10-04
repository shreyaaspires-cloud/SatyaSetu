"""
Stance scoring engine.

Uses a cross-encoder Natural Language Inference (NLI) model to determine
whether each piece of retrieved evidence SUPPORTS, REFUTES, or is NEUTRAL
toward a claim.

Model: roberta-large-mnli (configurable via settings.nli_model_name)
Fallback: lexical overlap scoring when the model is unavailable.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from app.contracts.models import EvidenceItem
from app.core.constants import Verdict
from app.core.config import settings

logger = logging.getLogger(__name__)

# NLI label indices for bart-large-mnli and roberta-large-mnli
_NLI_LABEL_MAP: Dict[int, str] = {0: "CONTRADICTION", 1: "NEUTRAL", 2: "ENTAILMENT"}

# Module-level model cache to avoid reload on every call
_nli_model_cache: Dict[str, Tuple[Any, Any]] = {}


def _load_nli_model(model_name: str) -> Optional[Tuple[Any, Any]]:
    """Lazily load the NLI tokenizer and model, caching after first load."""
    if model_name in _nli_model_cache:
        return _nli_model_cache[model_name]

    try:
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        logger.info("Loading NLI model '%s' …", model_name)
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        model = AutoModelForSequenceClassification.from_pretrained(model_name)
        model.eval()
        _nli_model_cache[model_name] = (tokenizer, model)
        logger.info("NLI model loaded: %s", model_name)
        return tokenizer, model
    except Exception as exc:
        logger.warning("NLI model load failed (%s): %s. Will use lexical fallback.", model_name, exc)
        return None


def _nli_stance(
    premise: str,
    hypothesis: str,
    tokenizer: Any,
    model: Any,
) -> Tuple[str, float]:
    """
    Run one NLI inference pass.
    Returns (label, confidence) where label ∈ {'ENTAILMENT','NEUTRAL','CONTRADICTION'}.
    """
    try:
        import torch

        inputs = tokenizer(
            premise,
            hypothesis,
            return_tensors="pt",
            truncation=True,
            max_length=512,
        )
        with torch.no_grad():
            logits = model(**inputs).logits
        probs = torch.softmax(logits, dim=-1)[0].tolist()
        best_idx = int(torch.argmax(logits, dim=-1).item())
        label = _NLI_LABEL_MAP.get(best_idx, "NEUTRAL")
        return label, float(probs[best_idx])
    except Exception as exc:
        logger.warning("NLI inference error: %s", exc)
        return "NEUTRAL", 0.5


def _lexical_overlap_score(claim: str, evidence_text: str) -> float:
    """
    Fallback stance heuristic based on keyword overlap between claim and evidence.
    Returns a score in [0, 1].
    """
    def tokenize(text: str) -> set:
        return set(re.findall(r"\b\w{3,}\b", text.lower()))

    claim_words = tokenize(claim)
    ev_words = tokenize(evidence_text)
    if not claim_words:
        return 0.0
    intersection = claim_words & ev_words
    return round(len(intersection) / len(claim_words), 3)


def score_stance(
    claim: str,
    evidence_items: List[EvidenceItem],
) -> List[EvidenceItem]:
    """
    Score and annotate each EvidenceItem with a stance label and updated score.

    Stance labels written to EvidenceItem.stance:
      - 'SUPPORTS'   — NLI ENTAILMENT or high lexical overlap
      - 'REFUTES'    — NLI CONTRADICTION
      - 'NEUTRAL'    — neither

    The EvidenceItem.score is updated to the NLI confidence / overlap score.

    Args:
        claim:           The English claim text to verify.
        evidence_items:  Retrieved evidence list (modified in-place and returned).

    Returns:
        The same list with stance and score fields populated.
    """
    if not claim.strip() or not evidence_items:
        return evidence_items

    model_tuple = _load_nli_model(settings.nli_model_name)

    for item in evidence_items:
        # Build a premise from snippet + title (truncated to ~500 chars)
        premise = f"{item.title}. {item.snippet}"[:500].strip()

        if model_tuple is not None:
            tokenizer, model = model_tuple
            label, confidence = _nli_stance(premise, claim, tokenizer, model)
            if label == "ENTAILMENT":
                item.stance = "SUPPORTS"
            elif label == "CONTRADICTION":
                item.stance = "REFUTES"
            else:
                item.stance = "NEUTRAL"
            item.score = round(confidence, 3)
        else:
            # Lexical fallback
            overlap = _lexical_overlap_score(claim, premise)
            item.stance = "SUPPORTS" if overlap > 0.3 else "NEUTRAL"
            item.score = overlap

    return evidence_items


def aggregate_verdict(
    claim: str,
    evidence_items: List[EvidenceItem],
) -> Tuple[Verdict, float, str]:
    """
    Aggregate per-item stances into a single Verdict with confidence and reason code.

    Verdict logic (in priority order):
    1. Any TIER_1/TIER_2 item with rating FALSE/MISLEADING  → REFUTED
    2. Any TIER_1/TIER_2 item with rating TRUE              → SUPPORTED
    3. Majority stance across all items
    4. Insufficient evidence                                → UNVERIFIABLE

    Returns:
        (verdict, confidence_0_to_1, reason_code)
    """
    from app.core.constants import Rating, Tier

    tier_weight = {
        Tier.TIER_1_IFCN: 1.0,
        Tier.TIER_2_GOV_PIB: 0.9,
        Tier.TIER_3_MAINSTREAM: 0.7,
        Tier.TIER_4_WIKIPEDIA: 0.5,
        Tier.TIER_5_GENERAL_WEB: 0.3,
    }

    if not evidence_items:
        return Verdict.UNVERIFIABLE, 0.0, "NO_EVIDENCE"

    # Priority: authoritative fact-checker ratings
    for item in evidence_items:
        weight = tier_weight.get(item.tier, 0.3)
        if weight >= 0.9:  # Tier 1 or 2
            if item.rating in (Rating.FALSE, Rating.MISLEADING):
                conf = round(min(item.score + 0.3, 1.0), 3)
                return Verdict.REFUTED, conf, "AUTHORITATIVE_FACT_CHECK"
            if item.rating == Rating.TRUE:
                conf = round(min(item.score + 0.3, 1.0), 3)
                return Verdict.SUPPORTED, conf, "AUTHORITATIVE_FACT_CHECK"
            if item.rating == Rating.PARTLY_TRUE:
                conf = round(min(item.score + 0.2, 1.0), 3)
                return Verdict.MISLEADING, conf, "AUTHORITATIVE_FACT_CHECK"

    # Stance aggregation weighted by tier
    stance_scores: Dict[str, float] = {"SUPPORTS": 0.0, "REFUTES": 0.0, "NEUTRAL": 0.0}
    for item in evidence_items:
        w = tier_weight.get(item.tier, 0.3)
        stance_key = item.stance or "NEUTRAL"
        if stance_key in stance_scores:
            stance_scores[stance_key] += item.score * w

    total = sum(stance_scores.values())
    if total < 0.05:
        return Verdict.UNVERIFIABLE, 0.0, "LOW_EVIDENCE_SIGNAL"

    best_stance = max(stance_scores, key=lambda k: stance_scores[k])
    best_score = stance_scores[best_stance]
    confidence = round(min(best_score / total, 1.0), 3)

    if best_stance == "SUPPORTS" and confidence > 0.5:
        return Verdict.SUPPORTED, confidence, "STANCE_MAJORITY"
    if best_stance == "REFUTES" and confidence > 0.5:
        return Verdict.REFUTED, confidence, "STANCE_MAJORITY"

    return Verdict.UNVERIFIABLE, confidence, "INCONCLUSIVE"
