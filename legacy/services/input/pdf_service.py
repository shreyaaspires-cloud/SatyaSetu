"""
services/input/pdf_service.py
──────────────────────────────
PyMuPDF (fitz) PDF text extraction.

Rules enforced:
  - Downloads PDF with timeout=10 — never hangs
  - Rejects files over 2 MB
  - Extracts text PDFs natively; falls back to OCR for scanned/image PDFs
  - Caps extracted text at 10,000 characters (per TRD §7 critical numbers)
  - Returns empty string on failure — never raises
"""

from __future__ import annotations

import io
import logging
from typing import TypedDict

import fitz  # PyMuPDF
import requests

from lib.config import settings
from services.input.ocr_service import get_ocr_reader

logger = logging.getLogger(__name__)

MAX_FILE_BYTES = 2 * 1024 * 1024   # 2 MB
MAX_TEXT_CHARS = 10_000             # TRD critical number
MIN_TEXT_PER_PAGE = 20              # chars — below this = scanned page, use OCR fallback
CONFIDENCE_THRESHOLD = 0.6


class PDFResult(TypedDict):
    text: str
    page_count: int
    extraction_method: str   # "native" | "ocr_fallback" | "empty"


def _download_pdf(url: str) -> bytes:
    """
    Download PDF from Twilio MediaUrl using Basic Auth.
    Enforces 2 MB limit.
    Raises requests.RequestException on network failure.
    Raises ValueError if file exceeds 2 MB.
    """
    response = requests.get(
        url,
        auth=(settings.twilio_account_sid, settings.twilio_auth_token),
        timeout=10,
        stream=True,
    )
    response.raise_for_status()

    content_length = response.headers.get("Content-Length")
    if content_length and int(content_length) > MAX_FILE_BYTES:
        raise ValueError(f"PDF too large: {content_length} bytes (max {MAX_FILE_BYTES})")

    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_content(chunk_size=8192):
        total += len(chunk)
        if total > MAX_FILE_BYTES:
            raise ValueError("PDF exceeds 2 MB limit during download")
        chunks.append(chunk)

    return b"".join(chunks)


def _extract_native_text(doc: fitz.Document) -> str:
    """
    Extract text from all pages of a text-based PDF using PyMuPDF.
    Returns concatenated text, capped at MAX_TEXT_CHARS.
    """
    pages_text: list[str] = []
    for page in doc:
        page_text = page.get_text("text").strip()  # type: ignore[attr-defined]
        if page_text:
            pages_text.append(page_text)

    combined = "\n\n".join(pages_text)
    return combined[:MAX_TEXT_CHARS]


def _extract_ocr_fallback(doc: fitz.Document) -> str:
    """
    For scanned PDFs (image-only pages), render the first page to pixels
    and run EasyOCR on the resulting image.

    Only processes first page to stay within time limits.
    Returns empty string if OCR reader is not loaded.
    """
    reader = get_ocr_reader()
    if reader is None:
        logger.warning("OCR reader not loaded — cannot perform PDF OCR fallback")
        return ""

    try:
        page = doc[0]
        # Render page at 2× resolution for better OCR accuracy
        mat = fitz.Matrix(2.0, 2.0)
        pix = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)  # type: ignore[attr-defined]
        img_bytes = pix.tobytes("jpeg")

        raw_results = reader.readtext(img_bytes, detail=1, paragraph=False)
        filtered = [
            text
            for (_bbox, text, conf) in raw_results
            if conf >= CONFIDENCE_THRESHOLD and text.strip()
        ]
        return " ".join(filtered).strip()[:MAX_TEXT_CHARS]

    except Exception as exc:
        logger.error("PDF OCR fallback failed: %s", exc, exc_info=True)
        return ""


def extract_text_from_pdf(url: str) -> PDFResult:
    """
    Download PDF from `url` → attempt native text extraction →
    fall back to EasyOCR for scanned pages.

    Returns:
        PDFResult with 'text', 'page_count', and 'extraction_method'

    On ANY failure, returns PDFResult with empty text.
    Never raises — the pipeline must continue even if PDF extraction fails.
    """
    try:
        pdf_bytes = _download_pdf(url)
    except ValueError as exc:
        logger.warning("PDF rejected: %s", exc)
        return PDFResult(text="", page_count=0, extraction_method="empty")
    except requests.RequestException as exc:
        logger.warning("Failed to download PDF: %s", exc)
        return PDFResult(text="", page_count=0, extraction_method="empty")

    try:
        doc = fitz.open(stream=io.BytesIO(pdf_bytes), filetype="pdf")
        page_count = doc.page_count

        # Attempt native text extraction
        native_text = _extract_native_text(doc)

        if len(native_text.strip()) >= MIN_TEXT_PER_PAGE:
            logger.info(
                "PDF native extraction: %d chars from %d pages",
                len(native_text),
                page_count,
            )
            doc.close()
            return PDFResult(
                text=native_text,
                page_count=page_count,
                extraction_method="native",
            )

        # Native text too short — likely scanned PDF, try OCR fallback
        logger.info(
            "PDF native text too short (%d chars) — trying OCR fallback on page 1",
            len(native_text.strip()),
        )
        ocr_text = _extract_ocr_fallback(doc)
        doc.close()

        if ocr_text:
            logger.info("PDF OCR fallback: %d chars extracted", len(ocr_text))
            return PDFResult(
                text=ocr_text,
                page_count=page_count,
                extraction_method="ocr_fallback",
            )

        logger.warning("PDF extraction produced no usable text")
        return PDFResult(text="", page_count=page_count, extraction_method="empty")

    except fitz.FileDataError as exc:
        logger.error("Corrupt or invalid PDF: %s", exc)
        return PDFResult(text="", page_count=0, extraction_method="empty")
    except Exception as exc:
        logger.error("PDF extraction failed unexpectedly: %s", exc, exc_info=True)
        return PDFResult(text="", page_count=0, extraction_method="empty")
