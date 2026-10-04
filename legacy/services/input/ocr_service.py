"""
services/input/ocr_service.py
──────────────────────────────
EasyOCR-based image text extraction.

Rules enforced:
  - Reader loaded ONCE at module import (called from lifespan in main.py)
  - Image compressed to max 800px width + converted to grayscale before OCR
  - Media downloaded with timeout=10 — never hangs
  - Rejects files over 2 MB
  - Returns empty string on any failure — never raises
  - Confidence threshold: 0.6 (drops blurry/noisy detections)
"""

from __future__ import annotations

import io
import logging
from typing import TypedDict

import easyocr
import requests
from PIL import Image

from lib.config import settings

logger = logging.getLogger(__name__)

# ── Module-level reader (initialised once at startup) ─────────────────────────
_ocr_reader: easyocr.Reader | None = None

MAX_IMAGE_WIDTH = 800       # px — resize before OCR
MAX_FILE_BYTES = 2 * 1024 * 1024  # 2 MB
CONFIDENCE_THRESHOLD = 0.6


class OCRResult(TypedDict):
    text: str
    confidence: float
    language: str


def load_ocr_reader() -> easyocr.Reader:
    """
    Load EasyOCR reader for English + Hindi.
    Called ONCE from lifespan() in main.py and stored in app.state.
    NOT GPU — cpu_mode keeps it portable on Render free tier.
    """
    global _ocr_reader
    if _ocr_reader is None:
        logger.info("Loading EasyOCR reader (en + hi)...")
        _ocr_reader = easyocr.Reader(
            ["en", "hi"],
            gpu=False,
            verbose=False,
        )
        logger.info("EasyOCR reader loaded successfully.")
    return _ocr_reader


def get_ocr_reader() -> easyocr.Reader | None:
    """Return the cached reader or None if not yet loaded."""
    return _ocr_reader


def _preprocess_image(image_bytes: bytes) -> bytes:
    """
    Resize image to max 800px width and convert to grayscale.
    Returns JPEG bytes ready for EasyOCR.
    Raises ValueError for corrupt / unreadable image data.
    """
    with Image.open(io.BytesIO(image_bytes)) as img:
        # Convert RGBA → RGB (JPEG doesn't support alpha)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")

        # Resize to max width maintaining aspect ratio
        if img.width > MAX_IMAGE_WIDTH:
            ratio = MAX_IMAGE_WIDTH / img.width
            new_height = int(img.height * ratio)
            img = img.resize((MAX_IMAGE_WIDTH, new_height), Image.LANCZOS)

        # Grayscale conversion improves OCR accuracy + reduces processing time
        img = img.convert("L")

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return buf.getvalue()


def _download_image(url: str) -> bytes:
    """
    Download image from Twilio MediaUrl.
    Uses Basic Auth (SID + Auth Token) as Twilio requires it for media.
    Raises requests.RequestException on failure.
    Raises ValueError if file exceeds 2 MB.
    """
    response = requests.get(
        url,
        auth=(settings.twilio_account_sid, settings.twilio_auth_token),
        timeout=10,
        stream=True,
    )
    response.raise_for_status()

    # Check Content-Length header first (fast rejection)
    content_length = response.headers.get("Content-Length")
    if content_length and int(content_length) > MAX_FILE_BYTES:
        raise ValueError(f"Image too large: {content_length} bytes (max {MAX_FILE_BYTES})")

    # Stream-read and enforce size limit
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_content(chunk_size=8192):
        total += len(chunk)
        if total > MAX_FILE_BYTES:
            raise ValueError(f"Image exceeds 2 MB limit during download")
        chunks.append(chunk)

    return b"".join(chunks)


def extract_text_from_image(url: str) -> OCRResult:
    """
    Download image from `url` → preprocess → run EasyOCR → return text.

    Returns:
        OCRResult with 'text' (str), 'confidence' (float 0–1), 'language' (str)

    On ANY failure, returns OCRResult with empty text and zero confidence.
    Never raises — the pipeline must continue even if OCR fails.
    """
    reader = get_ocr_reader()
    if reader is None:
        logger.error("OCR reader not loaded — was load_ocr_reader() called in lifespan?")
        return OCRResult(text="", confidence=0.0, language="unknown")

    try:
        # 1. Download
        image_bytes = _download_image(url)
    except ValueError as exc:
        logger.warning("Image rejected: %s", exc)
        return OCRResult(text="", confidence=0.0, language="unknown")
    except requests.RequestException as exc:
        logger.warning("Failed to download image from %s: %s", url, exc)
        return OCRResult(text="", confidence=0.0, language="unknown")

    try:
        # 2. Preprocess
        processed_bytes = _preprocess_image(image_bytes)
    except Exception as exc:
        logger.warning("Image preprocessing failed: %s", exc)
        return OCRResult(text="", confidence=0.0, language="unknown")

    try:
        # 3. OCR — reader.readtext returns [(bbox, text, confidence), ...]
        raw_results = reader.readtext(
            processed_bytes,
            detail=1,
            paragraph=False,
        )

        # 4. Filter by confidence threshold and join
        filtered_lines = [
            text
            for (_bbox, text, conf) in raw_results
            if conf >= CONFIDENCE_THRESHOLD and text.strip()
        ]
        full_text = " ".join(filtered_lines).strip()

        # Compute average confidence
        confidences = [conf for (_bbox, _text, conf) in raw_results if conf >= CONFIDENCE_THRESHOLD]
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

        logger.info(
            "OCR extracted %d chars with avg confidence %.2f",
            len(full_text),
            avg_confidence,
        )
        return OCRResult(text=full_text, confidence=round(avg_confidence, 3), language="auto")

    except Exception as exc:
        logger.error("EasyOCR inference failed: %s", exc, exc_info=True)
        return OCRResult(text="", confidence=0.0, language="unknown")
