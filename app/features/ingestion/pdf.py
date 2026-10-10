"""
PyMuPDF (fitz) PDF text extraction with OCR fallback for scanned documents.
Enforces safe downloading, size limits, and length bounds.
"""

from __future__ import annotations

import io
import logging
from typing import Any, Optional, TypedDict

try:
    import pymupdf as fitz  # Modern PyMuPDF import
except ImportError:
    import fitz  # Fallback for older PyMuPDF versions

from app.core.security import get_twilio_media_auth, safe_get
from app.features.ingestion.ocr import CONFIDENCE_THRESHOLD, get_ocr_reader

logger = logging.getLogger(__name__)

MAX_FILE_BYTES = 2 * 1024 * 1024  # 2 MB
MAX_TEXT_CHARS = 10_000
MIN_TEXT_PER_PAGE = 20


class PDFResult(TypedDict):
    text: str
    page_count: int
    extraction_method: str  # "native" | "ocr_fallback" | "empty"


def download_pdf(url: str) -> bytes:
    """
    Download PDF from URL with SSRF protection and isolated Twilio credentials.
    Enforces a strict 2 MB limit.
    """
    auth = get_twilio_media_auth(url)
    resp = safe_get(url, timeout=10, auth=auth)
    resp.raise_for_status()

    content = resp.content
    if len(content) > MAX_FILE_BYTES:
        raise ValueError(f"PDF too large: {len(content)} bytes (max {MAX_FILE_BYTES})")
    return content


def extract_native_text(doc: Any) -> str:
    """
    Extract text natively from all pages of the PDF.
    Capped at MAX_TEXT_CHARS.
    BUG-14: doc is typed as Any to prevent mypy/runtime errors when aliasing pymupdf as fitz.
    """
    pages_text: list[str] = []
    for page in doc:
        page_text = page.get_text("text").strip()
        if page_text:
            pages_text.append(page_text)

    combined = "\n\n".join(pages_text)
    return combined[:MAX_TEXT_CHARS]


def extract_ocr_fallback(doc: Any, reader: Optional[Any] = None) -> str:
    """
    For scanned / image-only PDFs, render the first page to an image
    and run EasyOCR.
    """
    active_reader = reader or get_ocr_reader()
    if active_reader is None:
        logger.warning("OCR reader not loaded. Cannot run PDF OCR fallback.")
        return ""

    try:
        page = doc[0]
        # Render page at 2x resolution for OCR clarity
        pix = page.get_pixmap(dpi=150)
        img_bytes = pix.tobytes("jpeg")

        raw_results = active_reader.readtext(img_bytes, detail=1, paragraph=False)
        lines = [
            text
            for (_bbox, text, conf) in raw_results
            if conf >= CONFIDENCE_THRESHOLD and text.strip()
        ]
        return " ".join(lines).strip()[:MAX_TEXT_CHARS]
    except Exception as exc:
        logger.warning("PDF OCR fallback failed: %s", exc)
        return ""


def extract_text_from_pdf_bytes(pdf_bytes: bytes, reader: Optional[Any] = None) -> PDFResult:
    """
    Extract text directly from PDF bytes.
    Uses native PyMuPDF text extraction first, falling back to EasyOCR
    if the document is scanned.
    """
    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            page_count = len(doc)
            if page_count == 0:
                return PDFResult(text="", page_count=0, extraction_method="empty")

            native_text = extract_native_text(doc)

            # If native text extraction yielded substantial text, return it
            if len(native_text) >= MIN_TEXT_PER_PAGE:
                logger.info(
                    "Extracted %d chars natively from %d pages",
                    len(native_text),
                    page_count,
                )
                return PDFResult(
                    text=native_text,
                    page_count=page_count,
                    extraction_method="native",
                )

            # Fallback to OCR for scanned documents
            logger.info("PDF has insufficient native text. Attempting OCR fallback on page 1...")
            ocr_text = extract_ocr_fallback(doc, reader=reader)
            method = "ocr_fallback" if ocr_text else "empty"
            return PDFResult(
                text=ocr_text,
                page_count=page_count,
                extraction_method=method,
            )
    except Exception as exc:
        logger.error("Failed to parse PDF bytes: %s", exc, exc_info=True)
        return PDFResult(text="", page_count=0, extraction_method="empty")


def extract_text_from_pdf(url: str, reader: Optional[Any] = None) -> PDFResult:
    """
    Download PDF from url and extract text.
    Never raises exceptions. On failure, returns empty text.
    """
    try:
        pdf_bytes = download_pdf(url)
    except Exception as exc:
        logger.warning("Failed to download PDF from %s: %s", url, exc)
        return PDFResult(text="", page_count=0, extraction_method="empty")

    return extract_text_from_pdf_bytes(pdf_bytes, reader=reader)

