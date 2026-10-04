"""
Verification feature package.
Exports the main public API: verify_claim and batch_verify_claims.
"""

from app.features.verification.service import batch_verify_claims, verify_claim

__all__ = ["verify_claim", "batch_verify_claims"]
