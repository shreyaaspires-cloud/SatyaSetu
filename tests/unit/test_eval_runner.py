"""
Unit acceptance tests for T15: Evaluation Set + Eval Runner (AT35, AT36).
"""

import os
import subprocess
import sys
import pytest


def test_at35_offline_eval_runs_and_writes_report():
    """
    AT35: python scripts/eval.py --offline runs without keys and writes eval/report.md.
    """
    base_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..")
    )
    script_path = os.path.join(base_dir, "scripts", "eval.py")
    report_path = os.path.join(base_dir, "eval", "report.md")

    if os.path.exists(report_path):
        os.remove(report_path)

    cmd = [sys.executable, script_path, "--offline"]
    result = subprocess.run(cmd, cwd=base_dir, capture_output=True, text=True)
    assert result.returncode == 0, f"eval.py failed with stderr: {result.stderr}\nstdout: {result.stdout}"
    assert os.path.exists(report_path), "eval/report.md was not generated"

    content = open(report_path, "r", encoding="utf-8").read()
    assert "Coverage" in content
    assert "Confident wrong rate" in content


def test_at36_report_groups_errors_by_cause():
    """
    AT36: Report lists wrong answers with cause grouped as:
    retrieval / language / detail mismatch / rule / model.
    """
    base_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..")
    )
    report_path = os.path.join(base_dir, "eval", "report.md")
    assert os.path.exists(report_path), "eval/report.md should exist after AT35"

    content = open(report_path, "r", encoding="utf-8").read()
    # Check that error categorization causes are present in the report
    for cause in ["retrieval", "language", "detail mismatch", "rule", "model"]:
        assert cause in content.lower(), f"Expected cause category '{cause}' in report"
