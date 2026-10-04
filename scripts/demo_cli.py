#!/usr/bin/env python3
"""
SatyaSetu Interactive Demo CLI
──────────────────────────────
Use this script for live judging, local testing, and PPT demo recordings.
Allows running claims in English, Hindi, or Hinglish directly through the
full SatyaSetu pipeline and seeing the exact formatted WhatsApp response.

Usage:
  python scripts/demo_cli.py
  python scripts/demo_cli.py --claim "5G causes COVID-19"
  python scripts/demo_cli.py --claim "हल्दी का पानी पीने से कोरोना ठीक होता है"
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Add project root to sys.path so app is discoverable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.contracts.models import IngestedMessage
from app.core.constants import InputType
from app.pipeline import run_pipeline


def run_demo(claim_text: str) -> None:
    print("\n" + "=" * 60)
    print(" 🛡️  SATYASETU FACT-CHECK DEMO")
    print("=" * 60)
    print(f"📥 Input Claim : {claim_text}")
    print("-" * 60)

    msg = IngestedMessage(
        raw_text=claim_text,
        input_type=InputType.TEXT,
        from_number="demo_user_hash",
        original_body=claim_text,
    )

    t0 = time.perf_counter()
    response = run_pipeline(msg)
    elapsed = time.perf_counter() - t0

    print(f"🌐 Detected Language : {response.language}")
    print(f"⚖️  Overall Verdict   : {response.overall_verdict.value}")
    print(f"⏱️  Pipeline Latency  : {elapsed:.2f}s ({response.timings_ms.get('total_ms', 0):.0f}ms backend)")
    print("-" * 60)
    print("📱 WhatsApp Formatted Reply Received By User:")
    print("=" * 60)
    print(response.formatted_reply)
    print("=" * 60)
    print("\nStage Latencies:")
    for stage, ms in response.timings_ms.items():
        print(f"  • {stage:16s}: {ms:.1f}ms")
    print("\n" + "=" * 60)


def main():
    parser = argparse.ArgumentParser(description="SatyaSetu Live Demo CLI")
    parser.add_argument("--claim", "-c", type=str, help="Claim to fact check")
    args = parser.parse_args()

    if args.claim:
        run_demo(args.claim)
    else:
        sample_claims = [
            "Drinking bleach cures viral infections within 24 hours.",
            "हल्दी का पानी पीने से सभी गंभीर बीमारियां दूर हो जाती हैं।",
            "5G mobile radiation is responsible for bird deaths in Mumbai.",
            "Water boils at 100 degrees Celsius at sea level.",
        ]
        print("\nSatyaSetu Interactive Demo")
        print("Select a sample claim or enter your own:")
        for idx, sc in enumerate(sample_claims, 1):
            print(f"  [{idx}] {sc}")
        print("  [0] Custom claim...")

        try:
            choice = input("\nEnter choice [1-4, or 0]: ").strip()
            if choice in ("1", "2", "3", "4"):
                run_demo(sample_claims[int(choice) - 1])
            else:
                custom = input("Enter custom claim: ").strip()
                if custom:
                    run_demo(custom)
        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")


if __name__ == "__main__":
    main()
