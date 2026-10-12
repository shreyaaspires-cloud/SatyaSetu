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

# Defensive Preprocessing & Bounds:
# - Image downsampling: MAX_IMAGE_WIDTH = 800px accelerates EasyOCR inference without accuracy loss.
# - File size limit: 2MB cap prevents decompression bomb attacks and excessive memory usage.
# - Confidence threshold: 0.6 minimum suppresses noisy OCR artifacts from camera blur.
MAX_IMAGE_WIDTH = 1280  # px: resize before OCR for high detail
MAX_FILE_BYTES = 2 * 1024 * 1024  # 2 MB
CONFIDENCE_THRESHOLD = 0.35  # lower cutoff for Devanagari script recognition


class OCRResult(TypedDict):
    text: str
    confidence: float
    language: str
    status: str
    error: str


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
        try:
            _ocr_reader = easyocr.Reader(langs, gpu=False, verbose=False)
        except Exception as ocr_init_err:
            logger.warning(
                "Could not initialize EasyOCR with langs %s (%s). Falling back to ['en', 'hi', 'mr'].",
                langs,
                ocr_init_err,
            )
            try:
                _ocr_reader = easyocr.Reader(["en", "hi", "mr"], gpu=False, verbose=False)
            except Exception:
                _ocr_reader = easyocr.Reader(["en"], gpu=False, verbose=False)
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
    Resize image up to 1280px width for OCR, fixing EXIF rotation,
    compositing alpha on white background, and guarding against 25MP decompression bombs.
    """
    from PIL import ImageOps

    with Image.open(io.BytesIO(image_bytes)) as img:
        # 1. Apply EXIF orientation
        img = ImageOps.exif_transpose(img) or img

        # 2. Decompression bomb check (< 25 megapixels)
        if (img.width * img.height) > 25_000_000:
            raise ValueError(f"Image resolution ({img.width}x{img.height}) exceeds 25 megapixel limit.")

        # 3. Composite RGBA/P on pure white background
        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            bg = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode != "RGBA":
                img = img.convert("RGBA")
            bg.paste(img, mask=img.split()[3])
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")

        # 4. Resize if width exceeds MAX_IMAGE_WIDTH
        if img.width > MAX_IMAGE_WIDTH:
            ratio = MAX_IMAGE_WIDTH / float(img.width)
            new_height = int(img.height * ratio)
            img = img.resize((MAX_IMAGE_WIDTH, new_height), Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        return buf.getvalue()


def download_image(url: str, max_bytes: int = MAX_FILE_BYTES) -> bytes:
    """
    Download image from URL with SSRF protection and isolated Twilio credentials.
    Streams download and enforces strict size limit early.
    """
    auth = get_twilio_media_auth(url)
    resp = safe_get(url, timeout=10, auth=auth, stream=True)
    resp.raise_for_status()

    content = bytearray()
    for chunk in resp.iter_content(chunk_size=65536):
        content.extend(chunk)
        if len(content) > max_bytes:
            raise ValueError(f"Image too large: {len(content)} bytes (max {max_bytes})")
    return bytes(content)


def _run_ocr(processed_bytes: bytes, reader: Any) -> OCRResult:
    """Core EasyOCR execution on preprocessed JPEG bytes with line sorting."""
    raw_results = reader.readtext(processed_bytes, detail=1, paragraph=False)

    # Sort results by vertical y coordinate first, then horizontal x coordinate
    def _box_key(item):
        bbox = item[0]
        # Top-left corner [x, y]
        return (bbox[0][1], bbox[0][0])

    sorted_results = sorted(raw_results, key=_box_key)

    filtered_lines = [
        text.strip()
        for (_bbox, text, conf) in sorted_results
        if conf >= CONFIDENCE_THRESHOLD and text.strip()
    ]

    confidences = [
        conf for (_bbox, _text, conf) in sorted_results if conf >= CONFIDENCE_THRESHOLD
    ]

    # Fallback to lower confidence text if all filtered out
    if not filtered_lines and sorted_results:
        filtered_lines = [text.strip() for (_bbox, text, conf) in sorted_results if text.strip()]
        confidences = [conf for (_bbox, _text, conf) in sorted_results]

    full_text = "\n".join(filtered_lines).strip()
    avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

    if not full_text:
        return OCRResult(
            text="",
            confidence=0.0,
            language="unknown",
            status="empty",
            error="I couldn't read any text in this image. Try a clearer screenshot.",
        )

    return OCRResult(
        text=full_text,
        confidence=round(avg_confidence, 3),
        language="auto",
        status="ok",
        error="",
    )


def extract_text_from_image(url: str, reader: Optional[Any] = None) -> OCRResult:
    """Download image, preprocess, run EasyOCR, and return result."""
    active_reader = reader or get_ocr_reader()
    if active_reader is None:
        logger.warning("OCR reader not loaded. Returning empty result.")
        return OCRResult(text="", confidence=0.0, language="unknown", status="model_unavailable", error="OCR model unavailable")

    try:
        image_bytes = download_image(url)
    except Exception as exc:
        logger.warning("Failed to download image from %s: %s", url, exc)
        return OCRResult(text="", confidence=0.0, language="unknown", status="download_failed", error=str(exc))

    try:
        processed_bytes = preprocess_image(image_bytes)
    except Exception as exc:
        logger.warning("Image preprocessing failed: %s", exc)
        return OCRResult(text="", confidence=0.0, language="unknown", status="unsupported", error=str(exc))

    try:
        return _run_ocr(processed_bytes, active_reader)
    except Exception as exc:
        logger.error("EasyOCR inference failed: %s", exc, exc_info=True)
        return OCRResult(text="", confidence=0.0, language="unknown", status="error", error=str(exc))


def extract_text_from_bytes(image_bytes: bytes, reader: Optional[Any] = None) -> OCRResult:
    """Directly preprocess in-memory image bytes and run EasyOCR."""
    active_reader = reader or get_ocr_reader()
    if active_reader is None:
        logger.warning("OCR reader not loaded. Returning empty result.")
        return OCRResult(text="", confidence=0.0, language="unknown", status="model_unavailable", error="OCR model unavailable")

    if not image_bytes or len(image_bytes) > MAX_FILE_BYTES:
        logger.warning("Image empty or exceeds max file size of %d bytes", MAX_FILE_BYTES)
        return OCRResult(text="", confidence=0.0, language="unknown", status="too_large", error=f"Image exceeds maximum size of {MAX_FILE_BYTES // 1_000_000} MB")

    try:
        processed_bytes = preprocess_image(image_bytes)
    except Exception as exc:
        logger.warning("Image preprocessing failed: %s", exc)
        return OCRResult(text="", confidence=0.0, language="unknown", status="unsupported", error=str(exc))

    try:
        return _run_ocr(processed_bytes, active_reader)
    except Exception as exc:
        logger.error("EasyOCR inference failed on bytes: %s", exc, exc_info=True)
        return OCRResult(text="", confidence=0.0, language="unknown", status="error", error=str(exc))
