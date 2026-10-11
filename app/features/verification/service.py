"""
Claim verification service (Wave 6).

Orchestrates retrieval + stance scoring + verdict aggregation for a single claim,
returning a fully populated ClaimResult contract object.
"""

from __future__ import annotations

import logging
from typing import List, Optional, Tuple

from app.contracts.models import ClaimResult, EvidenceItem
from app.core.config import settings
from app.core.constants import Verdict
from app.core.timing import StageTimer
from app.features.retrieval.orchestrator import retrieve_evidence
from app.features.verification.stance import aggregate_verdict, score_stance

logger = logging.getLogger(__name__)


def _gemini_verify_claim(
    claim: str,
    evidence_items: List[EvidenceItem],
) -> Optional[Tuple[Verdict, float, str]]:
    """
    Holistically verify a claim against retrieved evidence using Gemini reasoning.
    Returns (Verdict, confidence, reason_code) or None on failure/missing key.
    """
    if not settings.gemini_api_key or not evidence_items:
        return None

    try:
        import json
        from google import genai

        client = genai.Client(api_key=settings.gemini_api_key)

        items_desc = []
        from datetime import date as _date
        today_str = _date.today().isoformat()
        for idx, item in enumerate(evidence_items[:6]):
            pub_date = getattr(item, "publish_date", None) or "date unknown"
            items_desc.append(
                f"[{idx+1}] Source: {item.source_domain} | Published: {pub_date}"
                f" | Title: {item.title[:150].strip()} | Snippet: {item.snippet[:300].strip()}"
            )

        evidence_payload = "\n".join(items_desc)

        from app.core.redaction import redact_for_external

        redacted_claim = redact_for_external(claim)

        prompt = f"""Today's date is {today_str}. You are an objective fact-checking verification engine for an Indian misinformation detection system.
Analyze the following claim against the retrieved evidence snippets and scientific/historical consensus.

IMPORTANT: Evidence published before 2025 may be stale. If the claim describes a recent event and all evidence is older than 12 months, return UNVERIFIABLE unless the evidence is definitively applicable to the present (e.g. scientific consensus, historical record).

CLAIM: "{redacted_claim}"

RETRIEVED EVIDENCE:
{evidence_payload}

Determine the factual verdict of the claim:
- "REFUTED": The claim is false, a myth, a hoax, fabricated, debunked, or medically/scientifically incorrect.
- "SUPPORTED": The claim is confirmed to be true, accurate, and substantiated by reliable sources.
- "PARTIALLY_SUPPORTED": The claim contains partial truth mixed with exaggeration, distorted context, or unverified folk beliefs.
- "OUTDATED": The claim was true in the past or references an old notice, video, photo, or policy that has expired, been withdrawn, or is no longer valid.
- "UNVERIFIABLE": The evidence is insufficient, irrelevant, or contradictory without clear resolution.

Output strictly valid JSON with NO markdown formatting:
{{
  "verdict": "REFUTED",
  "confidence": 0.88,
  "reason": "GEMINI_FACT_CHECK"
}}
"""
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
        )

        if not response or not response.text:
            return None

        raw_text = response.text.strip()
        if raw_text.startswith("```json"):
            raw_text = raw_text[7:]
        elif raw_text.startswith("```"):
            raw_text = raw_text[3:]
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3]
        raw_text = raw_text.strip()

        data = json.loads(raw_text)
        verdict_str = str(data.get("verdict", "")).upper().strip()
        conf = float(data.get("confidence", 0.85))
        conf = round(max(0.5, min(0.98, conf)), 2)

        verdict_map = {
            "REFUTED": Verdict.REFUTED,
            "SUPPORTED": Verdict.SUPPORTED,
            "PARTIALLY_SUPPORTED": Verdict.PARTIALLY_SUPPORTED,
            "PARTIALLY SUPPORTED": Verdict.PARTIALLY_SUPPORTED,
            "OUTDATED": Verdict.OUTDATED,
            "UNVERIFIABLE": Verdict.UNVERIFIABLE,
            "MISLEADING": Verdict.PARTIALLY_SUPPORTED,
        }

        if verdict_str in verdict_map:
            logger.info("Gemini holistic verification verdict: %s (conf: %.2f)", verdict_str, conf)
            return verdict_map[verdict_str], conf, "GEMINI_VERIFICATION"

    except Exception as exc:
        logger.warning("Gemini holistic verification failed: %s", exc)

    return None


def _gemini_knowledge_verify(claim: str) -> Optional[Tuple[Verdict, float, str]]:
    """
    Ask Gemini to verify a claim using its own knowledge when retrieved evidence is insufficient.
    Targets well-known Indian hoaxes, government policies, health myths, viral rumors.
    """
    if not settings.gemini_api_key:
        return None

    try:
        import json
        from google import genai
        from app.core.redaction import redact_for_external

        client = genai.Client(api_key=settings.gemini_api_key)
        redacted = redact_for_external(claim)

        prompt = f"""You are a fact-checking system with expert knowledge of:
- Indian government policies (RBI, NPCI, PIB, Ministry of Finance, etc.)
- Common Indian WhatsApp hoaxes and viral misinformation
- Medical and scientific consensus
- Recent news events up to your knowledge cutoff

Evaluate this claim using your knowledge:
CLAIM: "{redacted}"

Classify as one of:
- "REFUTED": The claim is false, a hoax, a myth, or factually incorrect.
- "SUPPORTED": The claim is factually accurate and verifiable.
- "PARTIALLY_SUPPORTED": The claim contains partial truth mixed with exaggeration.
- "UNVERIFIABLE": You genuinely cannot determine truth or falsehood with confidence.

Only return UNVERIFIABLE if you truly have no knowledge about this topic.
For common Indian hoaxes (UPI charges, WhatsApp shutdown, free government schemes, 
5G health claims, home remedy cures), you should have enough knowledge to give a verdict.

Respond with valid JSON only:
{{"verdict": "REFUTED", "confidence": 0.82, "reason": "GEMINI_KNOWLEDGE_BASE"}}"""

        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
        )
        if not response or not response.text:
            return None

        raw = response.text.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        data = json.loads(raw)
        verdict_str = str(data.get("verdict", "")).upper().strip()
        conf = round(max(0.5, min(0.92, float(data.get("confidence", 0.75)))), 2)

        verdict_map = {
            "REFUTED": Verdict.REFUTED,
            "SUPPORTED": Verdict.SUPPORTED,
            "PARTIALLY_SUPPORTED": Verdict.PARTIALLY_SUPPORTED,
            "OUTDATED": Verdict.OUTDATED,
            "UNVERIFIABLE": Verdict.UNVERIFIABLE,
        }
        if verdict_str in verdict_map and verdict_str != "UNVERIFIABLE":
            return verdict_map[verdict_str], conf, "GEMINI_KNOWLEDGE_BASE"

    except Exception as exc:
        logger.warning("Gemini knowledge-base verification failed: %s", exc)

    return None


def verify_claim(
    claim: str,
    keywords: Optional[List[str]] = None,
    budget_ms: int = 12000,
) -> ClaimResult:
    """
    Run end-to-end verification for a single claim.

    Steps:
      1. Retrieve multi-source evidence (Google Fact Check, Wikipedia, Web)
      2. Score stance of each evidence item against the claim
      3. Aggregate stances and verify holistically with Gemini / authoritative checks

    Args:
        claim:      English claim text (already translated upstream).
        keywords:   Optional keyword list to guide Wikipedia retrieval.
        budget_ms:  Total millisecond budget for retrieval phase.

    Returns:
        ClaimResult with verdict, confidence, reason_code, and evidence list.
    """
    if not claim or not claim.strip():
        return ClaimResult(
            claim=claim,
            verdict=Verdict.UNVERIFIABLE,
            confidence=0.0,
            reason_code="EMPTY_CLAIM",
            evidence=[],
            guard_passed=True,
        )

    # MISSING-02: Check dynamic claim-level cache
    from app.core.cache import claim_cache_get, claim_cache_set
    cached_claim = claim_cache_get(claim.strip())
    if cached_claim:
        logger.info("Claim-level cache hit for: '%.60s'", claim)
        return ClaimResult(**cached_claim)

    # ── Check Pre-verified Claim Bank (Fast-path) ────────────────────────────
    from app.features.verification.claim_bank import lookup_claim_bank
    from app.core.constants import Rating, Tier
    bank_match = lookup_claim_bank(claim.strip())
    if bank_match and bank_match.is_decisive:
        logger.info(
            "Claim Bank match found for '%.60s' -> %s (%s)",
            claim, bank_match.verdict, bank_match.publisher,
        )
        bank_item = EvidenceItem(
            url=bank_match.source_url or "https://factcheck.org",
            title=f"Verified Fact Check by {bank_match.publisher}",
            snippet=bank_match.explanation or bank_match.citation,
            source_domain=bank_match.publisher.lower().replace(" ", "") + ".org",
            tier=Tier.TIER_1_IFCN,
            rating=(
                Rating.FALSE if bank_match.verdict == Verdict.REFUTED
                else Rating.TRUE if bank_match.verdict == Verdict.SUPPORTED
                else Rating.UNVERIFIED
            ),
            score=bank_match.confidence,
            stance=(
                "REFUTES" if bank_match.verdict == Verdict.REFUTED
                else "SUPPORTS" if bank_match.verdict == Verdict.SUPPORTED
                else "NEUTRAL"
            ),
            reason="CLAIM_BANK_GOLD_MATCH",
        )

        # For SUPPORTED (TRUE) claims: also fetch live evidence for richer explanation.
        # For REFUTED: skip — bank match is authoritative, don't risk adding noise.
        if bank_match.verdict == Verdict.SUPPORTED:
            try:
                live_evidence = retrieve_evidence(
                    claim=claim.strip(),
                    keywords=None,
                    budget_ms=6000,
                )
                combined_evidence = [bank_item] + live_evidence[:3]
            except Exception as exc:
                logger.warning(
                    "Live evidence fetch failed for TRUE bank claim: %s. Bank item only.", exc
                )
                combined_evidence = [bank_item]
        else:
            combined_evidence = [bank_item]

        return ClaimResult(
            claim=claim.strip(),
            verdict=bank_match.verdict,
            confidence=bank_match.confidence,
            reason_code="CLAIM_BANK_MATCH",
            evidence=combined_evidence,
            guard_passed=True,
            matched_claim=bank_match.canonical_claim,
            match_score=0.98,
        )

    with StageTimer("retrieval") as t_ret:
        evidence: List[EvidenceItem] = retrieve_evidence(
            claim=claim.strip(),
            keywords=keywords,
            budget_ms=budget_ms,
        )

    # BUG-A.3: When bank_match exists but is_decisive=False, add bank_match as first evidence item
    if bank_match and not bank_match.is_decisive:
        bank_item = EvidenceItem(
            url=bank_match.source_url or "https://factcheck.org",
            title=f"Historical Fact Check by {bank_match.publisher}",
            snippet=bank_match.explanation or bank_match.citation,
            source_domain=bank_match.publisher.lower().replace(" ", "") + ".org",
            tier=Tier.TIER_1_IFCN,
            rating=Rating.FALSE if bank_match.verdict == Verdict.REFUTED else (Rating.TRUE if bank_match.verdict == Verdict.SUPPORTED else Rating.UNVERIFIED),
            score=bank_match.confidence,
            stance="REFUTES" if bank_match.verdict == Verdict.REFUTED else ("SUPPORTS" if bank_match.verdict == Verdict.SUPPORTED else "NEUTRAL"),
            reason="CLAIM_BANK_HISTORICAL_CONTEXT",
            publish_date=bank_match.published_date or None,
        )
        evidence.insert(0, bank_item)

    logger.info("Retrieval completed in %.0fms, %d items", t_ret.elapsed_ms, len(evidence))

    with StageTimer("stance_scoring"):
        evidence = score_stance(claim=claim.strip(), evidence_items=evidence)

    with StageTimer("verdict_aggregation"):
        agg_verdict, agg_conf, agg_reason = aggregate_verdict(
            claim=claim.strip(),
            evidence_items=evidence,
        )
        verdict, confidence, reason_code = agg_verdict, agg_conf, agg_reason

    if verdict == Verdict.UNVERIFIABLE:
        # Pass 1: Gemini reasoning over retrieved evidence (existing)
        if evidence:
            gemini_result = _gemini_verify_claim(claim.strip(), evidence)
            if gemini_result:
                g_verdict, g_conf, g_reason = gemini_result
                has_strong_evidence = any(getattr(i, "tier", None) in (Tier.TIER_1_IFCN, Tier.TIER_2_GOV_PIB, Tier.TIER_3_MAINSTREAM) for i in evidence)
                if g_verdict == Verdict.SUPPORTED and not has_strong_evidence:
                    logger.info("Gemini SUPPORTED override blocked: insufficient decisive tier evidence (AT14)")
                else:
                    verdict, confidence, reason_code = g_verdict, g_conf, g_reason
                    logger.info("Gemini evidence-based override: verdict=%s conf=%.2f", verdict, confidence)

        # Pass 2: If still UNVERIFIABLE, ask Gemini using its own parametric knowledge
        if verdict == Verdict.UNVERIFIABLE and settings.gemini_api_key:
            gemini_kb_result = _gemini_knowledge_verify(claim.strip())
            if gemini_kb_result:
                verdict, confidence, reason_code = gemini_kb_result
                logger.info("Gemini KB override: verdict=%s conf=%.2f", verdict, confidence)


    logger.info(
        "Claim verdict=%s confidence=%.2f reason=%s evidence_count=%d",
        verdict,
        confidence,
        reason_code,
        len(evidence),
    )

    result = ClaimResult(
        claim=claim.strip(),
        verdict=verdict,
        confidence=confidence,
        reason_code=reason_code,
        evidence=evidence,
        guard_passed=True,
    )
    # MISSING-02: Save into claim-level cache
    try:
        claim_cache_set(claim.strip(), result.model_dump())
    except Exception as exc:
        logger.warning("Failed to set claim-level cache: %s", exc)

    return result


def batch_verify_claims(
    claims: List[str],
    keywords: Optional[List[str]] = None,
    budget_ms: int = 12000,
) -> List[ClaimResult]:
    """
    Verify multiple claims sequentially.
    Each claim receives its own retrieval pass.
    The budget is divided evenly among claims to avoid runaway latency.

    Args:
        claims:     List of English claim strings.
        keywords:   Shared keyword list for retrieval guidance.
        budget_ms:  Total millisecond budget split across claims.

    Returns:
        List of ClaimResult objects in the same order as the input claims.
    """
    if not claims:
        return []

    per_claim_budget = max(1000, budget_ms // len(claims))
    results: List[ClaimResult] = []

    for idx, claim in enumerate(claims):
        logger.info("Verifying claim %d/%d: %.80s…", idx + 1, len(claims), claim)
        result = verify_claim(
            claim=claim,
            keywords=keywords,
            budget_ms=per_claim_budget,
        )
        results.append(result)

    return results
