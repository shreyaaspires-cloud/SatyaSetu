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

# Document Ingestion Safeguards:
# - File size limit: 2MB cap prevents denial-of-service from massive documents.
# - Output bound: 10,000 characters limit bounds downstream NLP processing time.
# - Hybrid extraction: Attempts native PDF text first, falls back to OCR if page has <20 chars.
MAX_FILE_BYTES = 8 * 1024 * 1024  # 8 MB (raised from 2MB for scanned circulars/notices)
MAX_TEXT_CHARS = 10_000
MIN_TEXT_PER_PAGE = 20
MAX_PAGES_TO_PROCESS = 3


class PDFResult(TypedDict):
    text: str
    page_count: int
    extraction_method: str  # "native" | "ocr_fallback" | "hybrid" | "empty"
    status: str             # "ok" | "empty" | "encrypted" | "too_large" | "error"
    error: str


def download_pdf(url: str, max_bytes: int = MAX_FILE_BYTES) -> bytes:
    """
    Download PDF from URL with SSRF protection and isolated Twilio credentials.
    Enforces a strict 8 MB limit via streaming.
    """
    auth = get_twilio_media_auth(url)
    resp = safe_get(url, timeout=10, auth=auth, stream=True)
    resp.raise_for_status()

    content = bytearray()
    for chunk in resp.iter_content(chunk_size=65536):
        content.extend(chunk)
        if len(content) > max_bytes:
            raise ValueError(f"PDF too large: {len(content)} bytes (max {max_bytes})")
    return bytes(content)


def extract_text_from_pdf_bytes(pdf_bytes: bytes, reader: Optional[Any] = None) -> PDFResult:
    """
    Extract text directly from PDF bytes using per-page hybrid extraction (PyMuPDF + EasyOCR).
    Handles password-protected PDFs and caps processing to first 3 pages.
    """
    if not pdf_bytes:
        return PDFResult(text="", page_count=0, extraction_method="empty", status="empty", error="Empty PDF file uploaded.")

    if len(pdf_bytes) > MAX_FILE_BYTES:
        return PDFResult(
            text="",
            page_count=0,
            extraction_method="empty",
            status="too_large",
            error=f"PDF exceeds maximum allowed size of {MAX_FILE_BYTES // 1_000_000} MB.",
        )

    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            # Check for encrypted / password protected PDF
            if getattr(doc, "needs_pass", False):
                logger.warning("PDF is password protected and cannot be decrypted.")
                return PDFResult(
                    text="",
                    page_count=len(doc),
                    extraction_method="empty",
                    status="encrypted",
                    error="This document is password protected.",
                )

            page_count = len(doc)
            if page_count == 0:
                return PDFResult(text="", page_count=0, extraction_method="empty", status="empty", error="PDF contains no pages.")

            extracted_chunks: list[str] = []
            has_native = False
            has_ocr = False
            active_reader = reader or get_ocr_reader()

            # Process up to MAX_PAGES_TO_PROCESS
            for page_idx in range(min(page_count, MAX_PAGES_TO_PROCESS)):
                page = doc[page_idx]
                page_text = page.get_text("text").strip()

                if len(page_text) >= MIN_TEXT_PER_PAGE:
                    extracted_chunks.append(page_text)
                    has_native = True
                elif active_reader is not None:
                    # Page is scanned or image-heavy -> run OCR on rendered pixmap
                    try:
                        pix = page.get_pixmap(dpi=150)
                        img_bytes = pix.tobytes("jpeg")
                        raw_results = active_reader.readtext(img_bytes, detail=1, paragraph=False)
                        lines = [text.strip() for (_bbox, text, conf) in raw_results if conf >= CONFIDENCE_THRESHOLD and text.strip()]
                        ocr_page_text = "\n".join(lines).strip()
                        if ocr_page_text:
                            extracted_chunks.append(ocr_page_text)
                            has_ocr = True
                    except Exception as ocr_err:
                        logger.warning("OCR failed on PDF page %d: %s", page_idx + 1, ocr_err)

                # Early stop if character ceiling reached
                if sum(len(c) for c in extracted_chunks) >= MAX_TEXT_CHARS:
                    break

            combined_text = "\n\n".join(extracted_chunks).strip()[:MAX_TEXT_CHARS]

            if not combined_text:
                return PDFResult(
                    text="",
                    page_count=page_count,
                    extraction_method="empty",
                    status="empty",
                    error="I couldn't extract any readable text from this PDF. Try a clearer document.",
                )

            if has_native and has_ocr:
                method = "hybrid"
            elif has_ocr:
                method = "ocr_fallback"
            else:
                method = "native"

            return PDFResult(
                text=combined_text,
                page_count=page_count,
                extraction_method=method,
                status="ok",
                error="",
            )

    except Exception as exc:
        logger.error("Failed to parse PDF bytes: %s", exc, exc_info=True)
        return PDFResult(text="", page_count=0, extraction_method="empty", status="error", error="Corrupt or invalid PDF document.")


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

