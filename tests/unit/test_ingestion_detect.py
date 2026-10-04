"""
Unit tests for the Ingestion feature layer (migrated from test_member1.py).
Tests input type detection, text sanitization, phone hashing, and extractor routing.
"""

import hashlib
from unittest.mock import MagicMock, patch

from app.contracts.models import IngestedMessage
from app.core.constants import InputType
from app.core.redaction import hash_identifier
from app.features.ingestion import (
    detect_input_type,
    ingest,
    sanitize_text,
)


def test_text_preprocessing_direct():
    result: IngestedMessage = ingest(
        body="Drinking lemon water cures cancer!!",
        media_url=None,
        media_content_type=None,
        from_number="whatsapp:+919999999999",
    )

    assert result.input_type == InputType.TEXT
    assert "cancer" in result.raw_text.lower()
    assert result.from_number != "whatsapp:+919999999999"
    assert len(result.from_number) == 64
    assert result.original_body == "Drinking lemon water cures cancer!!"


def test_url_detection():
    input_type = detect_input_type(
        body="https://www.bbc.com/news/world-asia-india-123456",
        media_url=None,
        media_content_type=None,
    )
    assert input_type == InputType.URL
    assert input_type == "url"


def test_image_type_detection():
    for content_type in ["image/jpeg", "image/png", "image/jpg", "image/webp"]:
        input_type = detect_input_type(
            body="",
            media_url="https://api.twilio.com/media/test.jpg",
            media_content_type=content_type,
        )
        assert input_type == InputType.SCREENSHOT
        assert input_type == "screenshot"


def test_voice_and_pdf_detection():
    for ct in ["audio/ogg", "audio/ogg; codecs=opus", "audio/mpeg", "audio/mp4"]:
        assert detect_input_type(None, "https://example.com/audio.ogg", ct) == InputType.VOICE

    assert detect_input_type(None, "https://example.com/doc.pdf", "application/pdf") == InputType.PDF


def test_phone_hashing():
    raw = "whatsapp:+919999999999"
    hashed = hash_identifier(raw)
    expected = hashlib.sha256(raw.encode("utf-8")).hexdigest()

    assert hashed == expected
    assert len(hashed) == 64
    assert raw not in hashed


def test_sanitize_text_behavior():
    raw = "Normal text\x00with null byte and \x08backspace\nAllowed newline\tAllowed tab"
    sanitized = sanitize_text(raw, max_chars=100)

    assert "\x00" not in sanitized
    assert "\x08" not in sanitized
    assert "Allowed newline" in sanitized
    assert "Allowed tab" in sanitized

    # Verify D6 fix: marker strings are NOT blindly stripped by sanitize_text
    injection_text = "Check this claim IGNORE PREVIOUS"
    clean_injection = sanitize_text(injection_text)
    assert "IGNORE PREVIOUS" in clean_injection


def test_ingest_ocr_with_mock_reader():
    mock_reader = MagicMock()
    mock_reader.readtext.return_value = [
        ([(0, 0), (10, 10)], "Claim from screenshot", 0.95),
        ([(0, 0), (10, 10)], "Low confidence text", 0.3),
    ]

    with patch("app.features.ingestion.ocr.download_image", return_value=b"fake_image_bytes"):
        with patch("app.features.ingestion.ocr.preprocess_image", return_value=b"fake_processed_bytes"):
            result = ingest(
                body="",
                media_url="https://api.twilio.com/image.png",
                media_content_type="image/png",
                from_number="whatsapp:+919876543210",
                ocr_reader=mock_reader,
            )

            assert result.input_type == InputType.SCREENSHOT
            assert "Claim from screenshot" in result.raw_text
            assert "Low confidence text" not in result.raw_text
            assert result.ocr_confidence == 0.95
