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


_REFUTE_KEYWORDS = {
    "false", "fake", "myth", "hoax", "debunk", "untrue", "incorrect",
    "misleading", "disproven", "rumor", "rumour", "no evidence",
    "baseless", "fabricated", "not true", "refuted", "danger myth",
    "discredited", "no scientific basis", "no proof", "unfounded",
    "busted", "pseudoscience"
}


def _gemini_stance_batch(claim: str, evidence_items: List[EvidenceItem]) -> bool:
    """
    Classify the stance of evidence items against the claim in a single Gemini call.
    Annotates evidence_items in-place. Returns True if successful, False otherwise.
    """
    if not settings.gemini_api_key or not evidence_items:
        return False

    try:
        import json
        from google import genai

        client = genai.Client(api_key=settings.gemini_api_key)

        items_desc = []
        for idx, item in enumerate(evidence_items):
            snippet = item.snippet[:320].strip()
            title = item.title[:150].strip()
            domain = item.source_domain
            items_desc.append(f"[{idx}] Source: {domain} | Title: {title} | Snippet: {snippet}")

        evidence_payload = "\n".join(items_desc)

        from app.core.redaction import redact_for_external
        redacted_claim = redact_for_external(claim)

        prompt = f"""You are an expert fact-checking NLI (Natural Language Inference) classifier.
Evaluate how each evidence snippet relates to the following CLAIM.

CLAIM: "{redacted_claim}"

EVIDENCE ITEMS:
{evidence_payload}

For each item [0] to [{len(evidence_items)-1}], assign:
- "stance": "REFUTES" if the snippet disproves, contradicts, debunks the claim or shows it has no factual basis, is a myth/hoax, or states it is false.
- "stance": "SUPPORTS" if the snippet confirms or proves the claim is factually true.
- "stance": "NEUTRAL" if the snippet is off-topic, discusses related words without verifying or debunking the specific claim, or is inconclusive.
- "confidence": A float between 0.50 and 0.99.

Output strictly valid JSON only with NO markdown fences, matching this structure:
{{
  "results": [
    {{"index": 0, "stance": "REFUTES", "confidence": 0.90}},
    {{"index": 1, "stance": "NEUTRAL", "confidence": 0.65}}
  ]
}}
"""
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
        )

        if not response or not response.text:
            return False

        raw_text = response.text.strip()
        if raw_text.startswith("```json"):
            raw_text = raw_text[7:]
        elif raw_text.startswith("```"):
            raw_text = raw_text[3:]
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3]
        raw_text = raw_text.strip()

        data = json.loads(raw_text)
        results = data.get("results", [])
        if not results:
            return False

        for r in results:
            idx = r.get("index")
            if idx is not None and 0 <= idx < len(evidence_items):
                st = str(r.get("stance", "NEUTRAL")).upper().strip()
                if st in ("SUPPORTS", "REFUTES", "NEUTRAL"):
                    evidence_items[idx].stance = st
                conf = r.get("confidence")
                if conf is not None:
                    try:
                        evidence_items[idx].score = round(max(0.2, min(1.0, float(conf))), 3)
                    except (ValueError, TypeError):
                        pass

        logger.info("Successfully classified %d evidence items via Gemini stance batch.", len(evidence_items))
        return True

    except Exception as exc:
        logger.warning("Gemini stance batch classification failed: %s. Using lexical fallback.", exc)
        return False


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
      - 'SUPPORTS'   — NLI ENTAILMENT or verified support
      - 'REFUTES'    — NLI CONTRADICTION or debunk signal
      - 'NEUTRAL'    — neither

    Priority:
      1. Local NLI transformer model (if installed)
      2. Gemini batch stance classifier (if GEMINI_API_KEY is available)
      3. Upgraded lexical overlap & debunk keyword detection fallback
    """
    if not claim.strip() or not evidence_items:
        return evidence_items

    # 1. Try local NLI model
    model_tuple = _load_nli_model(settings.nli_model_name)
    if model_tuple is not None:
        tokenizer, model = model_tuple
        for item in evidence_items:
            premise = f"{item.title}. {item.snippet}"[:500].strip()
            label, confidence = _nli_stance(premise, claim, tokenizer, model)
            if label == "ENTAILMENT":
                item.stance = "SUPPORTS"
            elif label == "CONTRADICTION":
                item.stance = "REFUTES"
            else:
                item.stance = "NEUTRAL"
            item.score = round(confidence, 3)
        return evidence_items

    # 2. Try Gemini batch stance
    if _gemini_stance_batch(claim, evidence_items):
        return evidence_items

    # 3. Upgraded lexical fallback
    for item in evidence_items:
        premise = f"{item.title}. {item.snippet}"[:500].strip()
        premise_lower = premise.lower()
        overlap = _lexical_overlap_score(claim, premise)
        has_refute_signal = any(kw in premise_lower for kw in _REFUTE_KEYWORDS)

        if has_refute_signal and overlap > 0.15:
            item.stance = "REFUTES"
            item.score = round(min(0.90, max(0.60, overlap + 0.3)), 3)
        elif overlap > 0.50:
            item.stance = "SUPPORTS"
            item.score = overlap
        else:
            item.stance = "NEUTRAL"
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
    3. Stance aggregation weighted by tier
    4. Mixed signals                                        → MISLEADING
    5. Insufficient evidence                                → UNVERIFIABLE

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

    # OUTDATED rule for official sources (Tier 2):
    # Snippet mentions scheme/rule/notice being withdrawn, discontinued, replaced, or no longer valid
    for item in evidence_items:
        if item.tier == Tier.TIER_2_GOV_PIB:
            combined_text = f"{item.title} {item.snippet}".lower()
            withdrawal_kws = [
                "withdrawn", "discontinued", "replaced", "no longer valid",
                "expired", "cancelled", "repealed", "revoked",
            ]
            if any(re.search(r"\b" + re.escape(kw) + r"\b", combined_text) for kw in withdrawal_kws):
                claim_words = set(re.findall(r"\w{3,}", claim.lower()))
                stopwords = {"the", "and", "for", "with", "that", "this", "from", "have", "been", "has", "are", "was"}
                relevant_words = claim_words - stopwords
                text_words = set(re.findall(r"\w{3,}", combined_text))
                if not relevant_words or (relevant_words & text_words) or item.score >= 0.3:
                    conf = round(min((item.score or 0.7) + 0.2, 1.0), 3)
                    return Verdict.OUTDATED, conf, "OFFICIAL_NOTICE_WITHDRAWN"

    # Priority 1 & 2: authoritative fact-checker ratings
    for item in evidence_items:
        weight = tier_weight.get(item.tier, 0.3)
        if weight >= 0.9:  # Tier 1 or 2
            if item.tier == Tier.TIER_2_GOV_PIB:
                from app.features.retrieval.official_search import passes_detail_check
                if not passes_detail_check(claim, f"{item.title} {item.snippet}"):
                    continue
            if item.rating == Rating.OUTDATED:
                conf = round(min(item.score + 0.3, 1.0), 3)
                return Verdict.OUTDATED, conf, "AUTHORITATIVE_FACT_CHECK"
            if item.rating == Rating.PARTLY_TRUE:
                conf = round(min(item.score + 0.2, 1.0), 3)
                return Verdict.PARTIALLY_SUPPORTED, conf, "AUTHORITATIVE_FACT_CHECK"
            if item.rating in (Rating.FALSE, Rating.MISLEADING):
                conf = round(min(item.score + 0.3, 1.0), 3)
                return Verdict.REFUTED, conf, "AUTHORITATIVE_FACT_CHECK"
            if item.rating == Rating.TRUE:
                conf = round(min(item.score + 0.3, 1.0), 3)
                return Verdict.SUPPORTED, conf, "AUTHORITATIVE_FACT_CHECK"

    # Stance aggregation weighted by tier
    stance_scores: Dict[str, float] = {"SUPPORTS": 0.0, "REFUTES": 0.0, "NEUTRAL": 0.0}
    for item in evidence_items:
        if item.tier == Tier.TIER_2_GOV_PIB:
            from app.features.retrieval.official_search import passes_detail_check
            if not passes_detail_check(claim, f"{item.title} {item.snippet}"):
                continue
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

    # Detect mixed or conflicting evidence (ADR-003: maps to UNVERIFIABLE)
    if stance_scores["SUPPORTS"] > 0.25 and stance_scores["REFUTES"] > 0.25:
        return Verdict.UNVERIFIABLE, confidence, "CONFLICTING_EVIDENCE"

    if best_stance == "SUPPORTS" and confidence > 0.5:
        return Verdict.SUPPORTED, confidence, "STANCE_MAJORITY"
    if best_stance == "REFUTES" and confidence > 0.5:
        return Verdict.REFUTED, confidence, "STANCE_MAJORITY"

    return Verdict.UNVERIFIABLE, confidence, "INCONCLUSIVE"
