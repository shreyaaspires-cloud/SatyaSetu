#!/usr/bin/env python
"""
scripts/precache_demo.py — MISSING-04
Pre-warms the SatyaSetu claim cache before a live demo or judging session.

Usage:
    python scripts/precache_demo.py

Requires the full app environment (set up .env or export env vars first).
"""

from __future__ import annotations

import sys
import os
import time

# Ensure the workspace root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.contracts.models import IngestedMessage, InputType  # noqa: E402
from app.pipeline import run_pipeline  # noqa: E402

# ── Demo claims to pre-cache ──────────────────────────────────────────────────

DEMO_CLAIMS = [
    # Hindi misinformation
    "नई सरकारी योजना – गैस सिलेंडर अब मुफ्त! आगे फॉरवर्ड करें",
    # Health misinformation
    "Drinking hot water kills coronavirus completely",
    # 5G misinformation
    "5G towers cause cancer and spread viruses",
    # UPI banking
    "NPCI charges 2 percent transaction fee on normal UPI payments",
    # Railway scam
    "Government announced free railway tickets for senior citizens across India",
    # Lemon cancer
    "Lemon juice cures cancer in 48 hours without chemotherapy",
    # Celebrity death hoax
    "Nana Patekar passed away recently — is no more in this world",
    # ISRO true claim
    "ISRO launched Aditya-L1 solar observation mission to L1 Lagrange point",
    # CBSE fake
    "CBSE Board Exam Date Sheet 2026 has been leaked on Telegram groups",
    # Government cash
    "Government announced 5000 rupees direct bank transfer to all students this week",
]


def main() -> None:
    print("=" * 60)
    print("SatyaSetu — Pre-cache Demo Claims")
    print("=" * 60)

    success = 0
    for i, claim in enumerate(DEMO_CLAIMS, 1):
        print(f"\n[{i}/{len(DEMO_CLAIMS)}] Caching: {claim[:70]}...")
        t0 = time.monotonic()
        try:
            msg = IngestedMessage(
                raw_text=claim,
                input_type=InputType.TEXT,
                from_number="demo_precache",
                original_body=claim,
            )
            result = run_pipeline(msg)
            elapsed_ms = round((time.monotonic() - t0) * 1000, 0)
            cached_flag = " (cache hit)" if result.cached else ""
            print(f"    → {result.overall_verdict}{cached_flag} [{elapsed_ms:.0f}ms]")
            success += 1
        except Exception as exc:
            print(f"    ✗ ERROR: {exc}")

    print("\n" + "=" * 60)
    print(f"Done. {success}/{len(DEMO_CLAIMS)} claims cached successfully.")
    print("Cache is now warm — demo replies will be near-instant.")
    print("=" * 60)


if __name__ == "__main__":
    main()
