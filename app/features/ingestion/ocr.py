"""
EasyOCR text extraction from screenshot images.
Enforces image compression, file size limits, safe HTTP downloading,
and confidence filtering.
"""

from __future__ import annotations

import io
import logging
from typing import Any, Optional, TypedDict

from PIL import Image

from app.core.config import settings
from app.core.security import get_twilio_media_auth, safe_get

logger = logging.getLogger(__name__)

_ocr_reader: Any = None

MAX_IMAGE_WIDTH = 800  # px: resize before OCR
MAX_FILE_BYTES = 2 * 1024 * 1024  # 2 MB
CONFIDENCE_THRESHOLD = 0.6


class OCRResult(TypedDict):
    text: str
    confidence: float
    language: str


def load_ocr_reader(extra_langs: Optional[str] = None) -> Any:
    """
    Load EasyOCR reader for English plus configured extra languages.
    Called once from lifespan during application startup.
    """
    global _ocr_reader
    if _ocr_reader is None:
        import easyocr

        langs = ["en"]
        extra = extra_langs or settings.ocr_extra_langs
        if extra:
            for lang in extra.split(","):
                lang = lang.strip().lower()
                if lang and lang not in langs:
                    langs.append(lang)

        logger.info("Loading EasyOCR reader with languages: %s", langs)
        _ocr_reader = easyocr.Reader(langs, gpu=False, verbose=False)
        logger.info("EasyOCR reader loaded successfully.")
    return _ocr_reader


def get_ocr_reader() -> Any:
    """Return the cached reader or None if not loaded."""
    return _ocr_reader


def set_ocr_reader(reader: Any) -> None:
    """Set the reader manually (useful for tests and dependency injection)."""
    global _ocr_reader
    _ocr_reader = reader


def preprocess_image(image_bytes: bytes) -> bytes:
    """
    Resize image to max 800px width for OCR.
    Returns JPEG bytes ready for EasyOCR.

    BUG-15: Removed img.convert('L') grayscale step — EasyOCR handles colour
    input natively and greyscale conversion hurts Devanagari accuracy on
    coloured or low-contrast backgrounds.
    """
    with Image.open(io.BytesIO(image_bytes)) as img:
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")

        if img.width > MAX_IMAGE_WIDTH:
            ratio = MAX_IMAGE_WIDTH / img.width
            new_height = int(img.height * ratio)
            img = img.resize((MAX_IMAGE_WIDTH, new_height), Image.LANCZOS)

        # Do NOT convert to grayscale — EasyOCR handles colour; greyscale hurts Hindi OCR
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        return buf.getvalue()


def download_image(url: str) -> bytes:
    """
    Download image from URL with SSRF protection and isolated Twilio credentials.
    Enforces a strict 2 MB limit.
    """
    auth = get_twilio_media_auth(url)
    resp = safe_get(url, timeout=10, auth=auth)
    resp.raise_for_status()

    content = resp.content
    if len(content) > MAX_FILE_BYTES:
        raise ValueError(f"Image too large: {len(content)} bytes (max {MAX_FILE_BYTES})")
    return content


def extract_text_from_image(url: str, reader: Optional[Any] = None) -> OCRResult:
    """
    Download image from url, preprocess, run EasyOCR, and return extracted text.
    Never raises exceptions. On failure, returns empty text with 0.0 confidence.
    """
    active_reader = reader or get_ocr_reader()
    if active_reader is None:
        logger.warning("OCR reader not loaded. Returning empty result.")
        return OCRResult(text="", confidence=0.0, language="unknown")

    try:
        image_bytes = download_image(url)
    except Exception as exc:
        logger.warning("Failed to download image from %s: %s", url, exc)
        return OCRResult(text="", confidence=0.0, language="unknown")

    try:
        processed_bytes = preprocess_image(image_bytes)
    except Exception as exc:
        logger.warning("Image preprocessing failed: %s", exc)
        return OCRResult(text="", confidence=0.0, language="unknown")

    try:
        raw_results = active_reader.readtext(
            processed_bytes,
            detail=1,
            paragraph=False,
        )

        filtered_lines = [
            text
            for (_bbox, text, conf) in raw_results
            if conf >= CONFIDENCE_THRESHOLD and text.strip()
        ]
        full_text = " ".join(filtered_lines).strip()

        confidences = [
            conf for (_bbox, _text, conf) in raw_results if conf >= CONFIDENCE_THRESHOLD
        ]
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

        return OCRResult(
            text=full_text,
            confidence=round(avg_confidence, 3),
            language="auto",
        )
    except Exception as exc:
        logger.error("EasyOCR inference failed: %s", exc, exc_info=True)
        return OCRResult(text="", confidence=0.0, language="unknown")


def extract_text_from_bytes(image_bytes: bytes, reader: Optional[Any] = None) -> OCRResult:
    """
    Directly preprocess in-memory image bytes and run EasyOCR.
    Used by the /api/ocr screenshot upload endpoint.
    """
    active_reader = reader or get_ocr_reader()
    if active_reader is None:
        logger.warning("OCR reader not loaded. Returning empty result.")
        return OCRResult(text="", confidence=0.0, language="unknown")

    if not image_bytes or len(image_bytes) > MAX_FILE_BYTES:
        logger.warning("Image empty or exceeds max file size of %d bytes", MAX_FILE_BYTES)
        return OCRResult(text="", confidence=0.0, language="unknown")

    try:
        processed_bytes = preprocess_image(image_bytes)
    except Exception as exc:
        logger.warning("Image preprocessing failed: %s", exc)
        return OCRResult(text="", confidence=0.0, language="unknown")

    try:
        raw_results = active_reader.readtext(
            processed_bytes,
            detail=1,
            paragraph=False,
        )

        filtered_lines = [
            text
            for (_bbox, text, conf) in raw_results
            if conf >= CONFIDENCE_THRESHOLD and text.strip()
        ]
        full_text = " ".join(filtered_lines).strip()

        confidences = [
            conf for (_bbox, _text, conf) in raw_results if conf >= CONFIDENCE_THRESHOLD
        ]
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

        return OCRResult(
            text=full_text,
            confidence=round(avg_confidence, 3),
            language="auto",
        )
    except Exception as exc:
        logger.error("EasyOCR inference failed on image bytes: %s", exc, exc_info=True)
        return OCRResult(text="", confidence=0.0, language="unknown")
