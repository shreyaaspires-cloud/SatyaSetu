"""
Admin dashboard API endpoints (BUG-18 / PRD §6 FR-13).

Protected by X-API-Key header matching settings.admin_api_key.
Provides claim history, stats, and manual verdict override endpoints.

Note: Claim persistence (SQLAlchemy / SQLite) is scaffolded here.
      Wire up MISSING-05 (ClaimLog model) when the DB layer is added.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query, status

from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


# ── Auth dependency ───────────────────────────────────────────────────────────

def _require_api_key(x_api_key: str = Header(..., alias="X-API-Key")) -> None:
    """Require X-API-Key header matching ADMIN_API_KEY env var."""
    if not settings.admin_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin API is not configured on this server.",
        )
    if x_api_key != settings.admin_api_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key.",
        )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/stats", summary="Return claim volume and verdict distribution")
def get_stats(x_api_key: str = Header(..., alias="X-API-Key")) -> dict:
    """
    Return aggregate statistics:
    - Total claims processed
    - Verdict distribution (REFUTED / SUPPORTED / PARTIALLY_SUPPORTED / UNVERIFIABLE)
    - Average pipeline processing time

    Requires X-API-Key header.
    """
    _require_api_key(x_api_key)

    from app.core.cache import _memory_cache
    from app.db.claims_db import query_stats
    db_stats = query_stats()

    return {
        "status": "ok",
        "cached_claims": len(_memory_cache),
        "total_processed": db_stats.get("total_processed", 0),
        "verdict_distribution": db_stats.get("verdict_distribution", {}),
        "avg_pipeline_ms": db_stats.get("avg_pipeline_ms", 0),
    }


@router.get("/claims", summary="Paginated claim history with filters")
def get_claims(
    x_api_key: str = Header(..., alias="X-API-Key"),
    page: int = Query(default=1, ge=1),
    verdict: Optional[str] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict:
    """
    Return paginated claim history.
    Optional ?verdict= filter (REFUTED / SUPPORTED / PARTIALLY_SUPPORTED / UNVERIFIABLE).

    Requires X-API-Key header.
    """
    _require_api_key(x_api_key)

    from app.db.claims_db import query_claims
    total, rows = query_claims(page=page, limit=limit, verdict=verdict)

    return {
        "page": page,
        "limit": limit,
        "verdict_filter": verdict,
        "total": total,
        "claims": rows,
    }


@router.patch("/claims/{claim_id}/override", summary="Manually override a claim verdict")
def override_claim_verdict(
    claim_id: int,
    x_api_key: str = Header(..., alias="X-API-Key"),
    new_verdict: str = Query(..., description="New verdict: REFUTED | SUPPORTED | PARTIALLY_SUPPORTED | UNVERIFIABLE"),
    reason: str = Query(default="", description="Optional reason for override"),
) -> dict:
    """
    Manually override the verdict for a logged claim.
    Requires X-API-Key header.
    """
    _require_api_key(x_api_key)

    valid_verdicts = {"REFUTED", "SUPPORTED", "PARTIALLY_SUPPORTED", "UNVERIFIABLE", "OUTDATED"}
    if new_verdict.upper() not in valid_verdicts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid verdict '{new_verdict}'. Must be one of {valid_verdicts}",
        )

    from app.db.claims_db import update_claim_verdict
    updated = update_claim_verdict(claim_id, new_verdict.upper())

    logger.info("Admin verdict override: claim_id=%s new_verdict=%s reason=%s updated=%s", claim_id, new_verdict, reason, updated)

    return {
        "claim_id": claim_id,
        "override_applied": updated,
        "new_verdict": new_verdict.upper(),
        "reason": reason,
    }
