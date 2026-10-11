"""
Verification feature package.

Orchestrates the full factual verdict pipeline:
- Claim-level cache lookup (LRU, millisecond latency).
- Deterministic pre-verified claim bank fast-path.
- Fan-out multi-source retrieval + NLI stance scoring.
- Gemini LLM holistic and parametric knowledge arbitration.

Public API: `verify_claim` (single) and `batch_verify_claims` (multi-claim).
"""

from app.features.verification.service import batch_verify_claims, verify_claim

__all__ = ["verify_claim", "batch_verify_claims"]
