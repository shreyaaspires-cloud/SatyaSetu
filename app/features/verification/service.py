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
        for idx, item in enumerate(evidence_items[:6]):
            snippet = item.snippet[:300].strip()
            title = item.title[:150].strip()
            domain = item.source_domain
            items_desc.append(f"[{idx+1}] Source: {domain} | Title: {title} | Snippet: {snippet}")

        evidence_payload = "\n".join(items_desc)

        from app.core.redaction import redact_for_external

        redacted_claim = redact_for_external(claim)

        prompt = f"""You are an objective fact-checking verification engine for an Indian misinformation detection system.
Analyze the following claim against the retrieved evidence snippets and scientific/historical consensus.

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


def verify_claim(
    claim: str,
    keywords: Optional[List[str]] = None,
    budget_ms: int = 8000,
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

    # ── Check Pre-verified Claim Bank (Fast-path) ────────────────────────────
    from app.features.verification.claim_bank import lookup_claim_bank
    from app.core.constants import Rating, Tier
    bank_match = lookup_claim_bank(claim.strip())
    if bank_match and bank_match.is_decisive:
        logger.info("Claim Bank match found for '%.60s' -> %s (%s)", claim, bank_match.verdict, bank_match.publisher)
        bank_item = EvidenceItem(
            url=bank_match.source_url or "https://factcheck.org",
            title=f"Verified Fact Check by {bank_match.publisher}",
            snippet=bank_match.explanation or bank_match.citation,
            source_domain=bank_match.publisher.lower().replace(" ", "") + ".org",
            tier=Tier.TIER_1_IFCN,
            rating=Rating.FALSE if bank_match.verdict == Verdict.REFUTED else (Rating.TRUE if bank_match.verdict == Verdict.SUPPORTED else Rating.UNVERIFIED),
            score=bank_match.confidence,
            stance="REFUTES" if bank_match.verdict == Verdict.REFUTED else ("SUPPORTS" if bank_match.verdict == Verdict.SUPPORTED else "NEUTRAL"),
            reason="CLAIM_BANK_GOLD_MATCH",
        )
        return ClaimResult(
            claim=claim.strip(),
            verdict=bank_match.verdict,
            confidence=bank_match.confidence,
            reason_code="CLAIM_BANK_MATCH",
            evidence=[bank_item],
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
    logger.info("Retrieval completed in %.0fms, %d items", t_ret.elapsed_ms, len(evidence))

    with StageTimer("stance_scoring"):
        evidence = score_stance(claim=claim.strip(), evidence_items=evidence)

    with StageTimer("verdict_aggregation"):
        agg_verdict, agg_conf, agg_reason = aggregate_verdict(
            claim=claim.strip(),
            evidence_items=evidence,
        )
        # T5: the aggregator result is always final.
        # Gemini is only permitted to classify per-item stance (score_stance),
        # not to override the verdict produced by evidence sufficiency rules.
        verdict, confidence, reason_code = agg_verdict, agg_conf, agg_reason

    logger.info(
        "Claim verdict=%s confidence=%.2f reason=%s evidence_count=%d",
        verdict,
        confidence,
        reason_code,
        len(evidence),
    )

    return ClaimResult(
        claim=claim.strip(),
        verdict=verdict,
        confidence=confidence,
        reason_code=reason_code,
        evidence=evidence,
        guard_passed=True,
    )


def batch_verify_claims(
    claims: List[str],
    keywords: Optional[List[str]] = None,
    budget_ms: int = 8000,
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
