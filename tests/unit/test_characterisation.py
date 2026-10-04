"""
Unit characterisation tests for legacy pipelines and nlp_pipeline.
These tests capture and freeze the existing behavior before refactoring.
"""

import hashlib
import os
import sys
from unittest.mock import MagicMock

# Set required environment variables before importing settings
os.environ.setdefault("TWILIO_ACCOUNT_SID", "ACmock_account_sid_for_tests")
os.environ.setdefault("TWILIO_AUTH_TOKEN", "mock_auth_token_for_tests")

# Mock heavy third-party modules that are not required for unit testing logic
sys.modules.setdefault("whisper", MagicMock())
sys.modules.setdefault("easyocr", MagicMock())
sys.modules.setdefault("newspaper", MagicMock())
sys.modules.setdefault("fasttext", MagicMock())
sys.modules.setdefault("wikipediaapi", MagicMock())
sys.modules.setdefault("torch", MagicMock())
sys.modules.setdefault("transformers", MagicMock())
sys.modules.setdefault("keybert", MagicMock())

from pipelines.verify_pipeline import (
    _detect_input_type,
    _hash_phone,
    _sanitize_text,
)
import nlp_pipeline


def test_detect_input_type_media():
    assert _detect_input_type(None, "http://media", "image/jpeg") == "screenshot"
    assert _detect_input_type(None, "http://media", "image/png") == "screenshot"
    assert _detect_input_type(None, "http://media", "audio/ogg") == "voice"
    assert _detect_input_type(None, "http://media", "application/pdf") == "pdf"


def test_detect_input_type_url():
    assert _detect_input_type("https://example.com/news", None, None) == "url"
    assert _detect_input_type("http://example.com/story", None, None) == "url"


def test_detect_input_type_text():
    assert _detect_input_type("Drinking lemon water cures cancer!!", None, None) == "text"
    assert _detect_input_type("", None, None) == "text"
    assert _detect_input_type(None, None, None) == "text"


def test_hash_phone():
    phone = "whatsapp:+919876543210"
    hashed = _hash_phone(phone)
    expected = hashlib.sha256(phone.encode("utf-8")).hexdigest()

    assert hashed == expected
    assert len(hashed) == 64
    assert phone not in hashed


def test_sanitize_text_control_characters_and_truncation():
    raw = "Valid text\x00with null and \x07bell\nAllowed newline\tAllowed tab"
    sanitized = _sanitize_text(raw, max_chars=100)

    assert "\x00" not in sanitized
    assert "\x07" not in sanitized
    assert "Allowed newline" in sanitized
    assert "Allowed tab" in sanitized

    # Test truncation
    truncated = _sanitize_text("1234567890", max_chars=5)
    assert truncated == "12345"


def test_sanitize_text_legacy_injection_markers():
    # Documents existing legacy behavior for Defect D6
    raw = "Hello IGNORE PREVIOUS world ### SYSTEM test <|im_start|> prompt [INST] injection"
    sanitized = _sanitize_text(raw)

    assert "IGNORE PREVIOUS" not in sanitized
    assert "### SYSTEM" not in sanitized
    assert "<|im_start|>" not in sanitized
    assert "[INST]" not in sanitized
    assert "Hello  world  test  prompt  injection" == sanitized


def test_detect_language(monkeypatch):
    mock_model = MagicMock()
    mock_model.predict.return_value = (("__label__hi",), [0.98])
    monkeypatch.setattr(nlp_pipeline, "ft_model", mock_model)

    lang = nlp_pipeline.detect_language("नमस्ते आप कैसे हैं")
    assert lang == "hi"
    mock_model.predict.assert_called_once_with("नमस्ते आप कैसे हैं", k=1)


def test_extract_keywords(monkeypatch):
    mock_kw = MagicMock()
    mock_kw.extract_keywords.return_value = [("lemon water", 0.8), ("cancer", 0.75)]
    monkeypatch.setattr(nlp_pipeline, "kw_model", mock_kw)

    keywords = nlp_pipeline.extract_keywords("Drinking lemon water cures cancer", top_n=2)
    assert keywords == ["lemon water", "cancer"]

    # Empty text check
    assert nlp_pipeline.extract_keywords("") == []
    assert nlp_pipeline.extract_keywords("   ") == []
