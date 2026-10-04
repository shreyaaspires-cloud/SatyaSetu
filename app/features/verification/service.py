"""
Claim verification service (Wave 6).

Orchestrates retrieval + stance scoring + verdict aggregation for a single claim,
returning a fully populated ClaimResult contract object.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from app.contracts.models import ClaimResult, EvidenceItem
from app.core.constants import Verdict
from app.core.timing import StageTimer
from app.features.retrieval.orchestrator import retrieve_evidence
from app.features.verification.stance import aggregate_verdict, score_stance

logger = logging.getLogger(__name__)


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
      3. Aggregate individual stances into a single Verdict

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
        verdict, confidence, reason_code = aggregate_verdict(
            claim=claim.strip(),
            evidence_items=evidence,
        )

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
