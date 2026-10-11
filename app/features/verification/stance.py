"""
Stance scoring and consensus aggregation engine.

Determines whether each piece of retrieved evidence SUPPORTS, REFUTES, or is NEUTRAL
toward a claim, and aggregates evidence into a deterministic factual verdict.

Tri-Tier Classification Cascade:
1. Local RoBERTa-large MNLI Cross-Encoder: Fast, local zero-shot Natural Language Inference.
2. Gemini Batch Stance Classifier: Contextual LLM stance classification with JSON structured output.
3. Lexical & Polarity Heuristic Fallback: Token overlap and negation detection for offline execution.

Consensus & Guardrails:
- Detail Mismatch Pre-filtering: Items failing typed entity agreement (directions, numbers, currency)
  are forced to NEUTRAL and prevented from skewing verdicts.
- Tier-Weighted Scoring: IFCN (Tier 1) and Government (Tier 2) sources carry highest decisive weights.
- Recency Decay: Stale evidence (> 365 days) is discounted when evaluating fast-moving claims.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from app.contracts.models import EvidenceItem
from app.core.config import settings
from app.core.constants import Verdict
from app.features.verification.details import check_detail_conflict, has_negation

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


def _has_negated_refute_signal(premise_lower: str) -> bool:
    """
    Returns True only when a REFUTE keyword appears AND is NOT preceded by
    a negation word within 50 characters before it.

    "NOT a hoax"     → False   "claim is a hoax" → True
    "no evidence"    → False   "confirmed false"  → True
    """
    _NEGATION_PATTERN = r"\b(not|no|never|deny|denying|debunking the|isn't|aren't|doesn't|don't)\b"

    for kw in _REFUTE_KEYWORDS:
        if kw not in premise_lower:
            continue
        kw_idx = premise_lower.find(kw)
        lookbehind_window = premise_lower[max(0, kw_idx - 50): kw_idx]
        if re.search(_NEGATION_PATTERN, lookbehind_window):
            continue  # negation precedes keyword → skip
        return True  # genuine refute signal

    return False


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

    # Pre-pass: key detail agreement check (T2).
    # Runs before any NLI/Gemini/lexical scoring.
    # Items with a detail conflict are marked NEUTRAL immediately and excluded
    # from further stance scoring so they cannot SUPPORT or REFUTE.
    _to_score: list[EvidenceItem] = []
    for item in evidence_items:
        premise = f"{item.title}. {item.snippet}"[:500].strip()
        conflict = check_detail_conflict(claim, premise)
        if conflict == "DETAIL_MISMATCH":
            item.stance = "NEUTRAL"
            item.reason = "DETAIL_MISMATCH"
            # Keep existing score so sorting still works
        else:
            _to_score.append(item)

    # If all items were mismatched, return early
    if not _to_score:
        return evidence_items

    def _apply_recency_weight(item: EvidenceItem) -> None:
        from datetime import date, datetime
        today = date.today()
        if getattr(item, "publish_date", None):
            try:
                pub = datetime.strptime(str(item.publish_date)[:10], "%Y-%m-%d").date()
                age_months = (today - pub).days / 30.44
                if age_months > 36:
                    item.score = round(item.score * 0.60, 3)
                elif age_months > 18:
                    item.score = round(item.score * 0.80, 3)
            except Exception:
                pass

    # 1. Try local NLI model
    model_tuple = _load_nli_model(settings.nli_model_name)
    if model_tuple is not None:
        tokenizer, model = model_tuple
        for item in _to_score:
            premise = f"{item.title}. {item.snippet}"[:500].strip()
            label, confidence = _nli_stance(premise, claim, tokenizer, model)
            if label == "ENTAILMENT":
                item.stance = "SUPPORTS"
            elif label == "CONTRADICTION":
                item.stance = "REFUTES"
            else:
                item.stance = "NEUTRAL"
            item.score = round(confidence, 3)
            _apply_recency_weight(item)
        return evidence_items

    # 2. Try Gemini batch stance (only on non-mismatched items)
    if _gemini_stance_batch(claim, _to_score):
        for item in _to_score:
            _apply_recency_weight(item)
        return evidence_items

    # 3. Negation-aware lexical fallback
    for item in _to_score:
        premise = f"{item.title}. {item.snippet}"[:500].strip()
        premise_lower = premise.lower()
        overlap = _lexical_overlap_score(claim, premise)

        genuine_refute_signal = _has_negated_refute_signal(premise_lower)

        if genuine_refute_signal and overlap > 0.20:   # raised from 0.15
            item.stance = "REFUTES"
            item.score = round(min(0.90, max(0.60, overlap + 0.3)), 3)
        elif overlap > 0.50:
            item.stance = "SUPPORTS"
            item.score = overlap
        else:
            item.stance = "NEUTRAL"
            item.score = overlap
        _apply_recency_weight(item)

    return evidence_items


def aggregate_verdict(
    claim: str,
    evidence_items: List[EvidenceItem],
) -> Tuple[Verdict, float, str]:
    """
    Aggregate per-item stances into a single Verdict with confidence and reason code.

    Verdict logic — applied in order (T3 sufficiency rules):

    1. Demoted / detail-mismatched items (reason in {RELATED_NOT_SAME, DETAIL_MISMATCH})
       are excluded from the decisive path. They may contribute to context display only.

    2. REFUTED: 1 relevant Tier-1/2 item with a FALSE rating that passed the
       relevance gate, OR ≥ 2 independent Tier-1/2/3 items that REFUTE.

    3. SUPPORTED: ≥ 2 independent domains with Tier-1/2/3 items that SUPPORT,
       at least one of them Tier-1/2/3, with no REFUTES from Tier-1/2/3 sources
       and no DETAIL_MISMATCH on any supporting item.

    4. UNVERIFIABLE (CONFLICTING_EVIDENCE): Tier-1/2/3 items both SUPPORT
       and REFUTE — cannot resolve.

    5. Tier-4 (Wikipedia) and Tier-5 evidence alone are NEVER decisive.
       Wikipedia alone → always UNVERIFIABLE.

    6. Default: UNVERIFIABLE.

    Returns:
        (verdict, confidence_0_to_1, reason_code)
    """
    from app.core.constants import Rating, Tier

    _DECISIVE_TIERS = {Tier.TIER_1_IFCN, Tier.TIER_2_GOV_PIB, Tier.TIER_3_MAINSTREAM}
    _NON_DECISIVE_REASONS = {"RELATED_NOT_SAME", "DETAIL_MISMATCH"}

    if not evidence_items:
        return Verdict.UNVERIFIABLE, 0.0, "NO_EVIDENCE"

    # Partition: decisive candidates vs context-only
    decisive: List[EvidenceItem] = []
    for item in evidence_items:
        if getattr(item, "reason", None) in _NON_DECISIVE_REASONS:
            continue  # context only — excluded from verdict
        decisive.append(item)

    # OUTDATED rule for official sources (Tier 2):
    # Snippet mentions scheme/rule/notice being withdrawn, discontinued, replaced, or no longer valid
    for item in decisive:
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

    # Outdated authoritative fact check:
    tier12_outdated = [
        i for i in decisive
        if i.tier in (Tier.TIER_1_IFCN, Tier.TIER_2_GOV_PIB)
        and i.rating == Rating.OUTDATED
    ]
    if tier12_outdated:
        best = max(tier12_outdated, key=lambda i: i.score)
        return Verdict.OUTDATED, round(min(best.score + 0.3, 1.0), 3), "AUTHORITATIVE_FACT_CHECK"

    def _is_tier2_detail_valid(item: EvidenceItem) -> bool:
        if item.tier == Tier.TIER_2_GOV_PIB:
            from app.features.retrieval.official_search import passes_detail_check
            return passes_detail_check(claim, f"{item.title} {item.snippet}")
        return True

    # -----------------------------------------------------------------------
    # Rule 2: REFUTED — authoritative FALSE rating that passed gate
    # BUG-B.2: Require corroboration OR publish_date no older than 18 months
    # -----------------------------------------------------------------------
    from datetime import date, datetime
    today = date.today()

    tier12_false = [
        i for i in decisive
        if i.tier in (Tier.TIER_1_IFCN, Tier.TIER_2_GOV_PIB)
        and i.rating in (Rating.FALSE, Rating.MISLEADING)
        and i.stance != "NEUTRAL"
        and _is_tier2_detail_valid(i)
    ]
    if tier12_false:
        best = max(tier12_false, key=lambda i: i.score)
        # Check corroboration (at least 2 items supporting REFUTES)
        has_corroboration = len([i for i in decisive if i.stance == "REFUTES" and i.tier in _DECISIVE_TIERS]) >= 2
        is_fresh = False
        if best.publish_date:
            try:
                pub_d = datetime.strptime(str(best.publish_date)[:10], "%Y-%m-%d").date()
                if (today - pub_d).days / 30.44 <= 18:
                    is_fresh = True
            except Exception:
                is_fresh = False

        if not has_corroboration and not is_fresh:
            return Verdict.UNVERIFIABLE, round(min(best.score, 1.0), 3), "SINGLE_STALE_SOURCE"

        return Verdict.REFUTED, round(min(best.score, 1.0), 3), "AUTHORITATIVE_FACT_CHECK"

    # -----------------------------------------------------------------------
    # Rule 2b: SUPPORTED — authoritative TRUE rating that passed gate
    # -----------------------------------------------------------------------
    tier12_true = [
        i for i in decisive
        if i.tier in (Tier.TIER_1_IFCN, Tier.TIER_2_GOV_PIB)
        and i.rating == Rating.TRUE
        and i.stance != "NEUTRAL"
        and _is_tier2_detail_valid(i)
    ]
    if tier12_true:
        best = max(tier12_true, key=lambda i: i.score)
        return Verdict.SUPPORTED, round(min(best.score, 1.0), 3), "AUTHORITATIVE_FACT_CHECK"

    # -----------------------------------------------------------------------
    # Rule 2c: PARTLY_TRUE → PARTIALLY_SUPPORTED (authoritative)
    # -----------------------------------------------------------------------
    tier12_partly = [
        i for i in decisive
        if i.tier in (Tier.TIER_1_IFCN, Tier.TIER_2_GOV_PIB)
        and i.rating == Rating.PARTLY_TRUE
        and _is_tier2_detail_valid(i)
    ]
    if tier12_partly:
        best = max(tier12_partly, key=lambda i: i.score)
        return Verdict.PARTIALLY_SUPPORTED, round(min(best.score, 1.0), 3), "AUTHORITATIVE_FACT_CHECK"

    # -----------------------------------------------------------------------
    # Rule 2d: Conflicting policy evidence → PARTIALLY_SUPPORTED (BUG-B.3)
    # If decisive items have BOTH REFUTES and SUPPORTS stances from the same
    # domain or government sources with > 18 months age difference
    # -----------------------------------------------------------------------
    decisive_t123 = [i for i in decisive if i.tier in _DECISIVE_TIERS and _is_tier2_detail_valid(i)]
    supports_t123 = [i for i in decisive_t123 if i.stance == "SUPPORTS"]
    refutes_t123 = [i for i in decisive_t123 if i.stance == "REFUTES"]

    if supports_t123 and refutes_t123:
        # Check if SUPPORTS and REFUTES come from same domain or government domains with date difference > 18 months
        conflicting_policy = False
        max_conf = max(max(s.score for s in supports_t123), max(r.score for r in refutes_t123))

        for s in supports_t123:
            for r in refutes_t123:
                same_or_gov = (
                    (s.source_domain and s.source_domain == r.source_domain)
                    or (s.tier == Tier.TIER_2_GOV_PIB and r.tier == Tier.TIER_2_GOV_PIB)
                )
                if same_or_gov and s.publish_date and r.publish_date:
                    try:
                        s_dt = datetime.strptime(str(s.publish_date)[:10], "%Y-%m-%d").date()
                        r_dt = datetime.strptime(str(r.publish_date)[:10], "%Y-%m-%d").date()
                        diff_months = abs((s_dt - r_dt).days) / 30.44
                        if diff_months > 18:
                            conflicting_policy = True
                            break
                    except Exception:
                        pass
            if conflicting_policy:
                break

        if conflicting_policy:
            return Verdict.PARTIALLY_SUPPORTED, round(min(max_conf, 1.0), 3), "CONFLICTING_POLICY_EVIDENCE"

    # -----------------------------------------------------------------------
    # From here on: only stance-based evaluation of decisive Tier-1/2/3 items
    # -----------------------------------------------------------------------
    # Rule 4: conflicting decisive evidence → UNVERIFIABLE (CONFLICTING_EVIDENCE)
    if supports_t123 and refutes_t123:
        return Verdict.UNVERIFIABLE, 0.5, "CONFLICTING_EVIDENCE"

    # Rule 2 (stance): ≥2 independent Tier-1/2/3 items REFUTE
    if len(refutes_t123) >= 2:
        unique_domains = {i.source_domain for i in refutes_t123}
        if len(unique_domains) >= 2:
            best_conf = round(max(i.score for i in refutes_t123), 3)
            return Verdict.REFUTED, best_conf, "STANCE_MAJORITY"

    # Rule 3: ≥2 independent domains of Tier-1/2/3 SUPPORT, no refutes
    if len(supports_t123) >= 2 and not refutes_t123:
        unique_domains = {i.source_domain for i in supports_t123}
        if len(unique_domains) >= 2:
            best_conf = round(max(i.score for i in supports_t123), 3)
            return Verdict.SUPPORTED, best_conf, "STANCE_MAJORITY"

    # -----------------------------------------------------------------------
    # Rule 5: Tier-4/5 only evidence is NEVER decisive
    # -----------------------------------------------------------------------
    has_only_weak = all(i.tier not in _DECISIVE_TIERS for i in decisive) if decisive else True
    if has_only_weak:
        return Verdict.UNVERIFIABLE, 0.0, "INSUFFICIENT_TIER"

    # -----------------------------------------------------------------------
    # Default: insufficient decisive evidence
    # -----------------------------------------------------------------------
    return Verdict.UNVERIFIABLE, 0.0, "INCONCLUSIVE"

