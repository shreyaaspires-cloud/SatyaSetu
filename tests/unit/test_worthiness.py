"""
Unit tests for check-worthiness scoring evaluated against labelled fixtures.
"""

import os
import yaml

from app.features.nlp.worthiness import is_check_worthy, score_check_worthiness


def test_worthiness_with_fixtures():
    fixture_path = os.path.join(
        os.path.dirname(__file__), "..", "fixtures", "worthiness.yaml"
    )
    with open(fixture_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    for item in data.get("claims", []):
        text = item["text"]
        expected_worthy = item["worthy"]
        label = item["label"]

        score = score_check_worthiness(text)
        actual_worthy = is_check_worthy(text, threshold=0.50)

        if expected_worthy:
            assert actual_worthy is True, f"Failed for worthy claim [{label}]: '{text}', score={score}"
            assert score >= 0.50
        else:
            assert actual_worthy is False, f"Failed for non-worthy text [{label}]: '{text}', score={score}"
            assert score < 0.50


def test_empty_or_short_texts():
    assert score_check_worthiness("") == 0.0
    assert score_check_worthiness("hi") < 0.30
    assert is_check_worthy("hello") is False
