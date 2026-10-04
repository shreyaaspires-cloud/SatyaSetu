"""
pipelines/verify_pipeline.py
─────────────────────────────
Member 1's master preprocessor — detects input type and routes to the
correct extraction service, then returns a clean dict to Member 2.

Output contract (exactly what Member 2 / Shreya expects):
    {
        "raw_text":      str,   # clean extracted text
        "input_type":    str,   # "text" | "screenshot" | "voice" | "pdf" | "url"
        "from_number":   str,   # hashed WhatsApp number (SHA-256, never raw)
        "original_body": str,   # original WhatsApp message Body field
    }

Input type detection (per strict rules §14 in prompt):
    image/jpeg or image/png  → screenshot → ocr_service
    audio/ogg                → voice      → asr_service
    application/pdf          → pdf        → pdf_service
    body starts with http    → url        → url_service
    None / empty             → text       → use Body directly
"""

from __future__ import annotations

import hashlib
import logging
from typing import TypedDict

from services.input.asr_service import transcribe_audio
from services.input.ocr_service import extract_text_from_image
from services.input.pdf_service import extract_text_from_pdf
from services.input.url_service import extract_text_from_url

logger = logging.getLogger(__name__)


# ── Output type returned to Member 2 ─────────────────────────────────────────

class PreprocessingResult(TypedDict):
    raw_text: str
    input_type: str
    from_number: str        # SHA-256 hashed — NEVER the raw phone number
    original_body: str


# ── Internal helpers ──────────────────────────────────────────────────────────

def _hash_phone(phone: str) -> str:
    """
    Hash phone number with SHA-256 before any logging or storage.
    Raw phone numbers must NEVER appear in logs or return values.
    """
    return hashlib.sha256(phone.encode("utf-8")).hexdigest()


def _detect_input_type(
    body: str | None,
    media_url: str | None,
    media_content_type: str | None,
) -> str:
    """
    Determine which extraction path to take based on Twilio fields.

    Priority order:
      1. media_content_type for image/audio/pdf (explicit type from Twilio)
      2. body starts with http/https → URL scraping
      3. Fallback → plain text from body
    """
    if media_content_type:
        ct = media_content_type.lower().strip()
        if ct in ("image/jpeg", "image/png", "image/jpg", "image/webp"):
            return "screenshot"
        if ct in ("audio/ogg", "audio/ogg; codecs=opus", "audio/mpeg", "audio/mp4"):
            return "voice"
        if ct == "application/pdf":
            return "pdf"

    # No media — check if body is a URL
    cleaned_body = (body or "").strip()
    if cleaned_body.lower().startswith(("http://", "https://")):
        return "url"

    # Default: plain text
    return "text"


def _sanitize_text(text: str, max_chars: int = 10_000) -> str:
    """
    Strip control characters, limit length, prevent prompt injection.
    (Per TRD §3.4 Input Sanitization)
    """
    # Remove null bytes and non-printable control characters (keep \n and \t)
    text = "".join(ch for ch in text if ch.isprintable() or ch in "\n\t")
    # Truncate
    text = text[:max_chars]
    # Remove common prompt injection markers
    for marker in ["IGNORE PREVIOUS", "### SYSTEM", "<|im_start|>", "[INST]"]:
        text = text.replace(marker, "")
    return text.strip()


# ── Main entry point ──────────────────────────────────────────────────────────

def run_preprocessing(
    body: str | None,
    media_url: str | None,
    media_content_type: str | None,
    from_number: str,
) -> PreprocessingResult:
    """
    Route the incoming Twilio message to the correct extractor service
    and return a clean PreprocessingResult dict for Member 2.

    This function NEVER raises. On any failure, raw_text is "" and
    Member 2 / the pipeline is responsible for handling the empty case.

    Args:
        body:               Twilio 'Body' field (text of the WhatsApp message)
        media_url:          Twilio 'MediaUrl0' field (URL to attached media)
        media_content_type: Twilio 'MediaContentType0' field (MIME type of media)
        from_number:        Twilio 'From' field (e.g. "whatsapp:+91xxxxxxxxxx")

    Returns:
        PreprocessingResult dict with exactly 4 keys.
    """
    # Hash phone number immediately — raw number must not persist past this point
    hashed_number = _hash_phone(from_number)
    logger.info("Processing message from hashed_number=%s", hashed_number[:8] + "...")

    input_type = _detect_input_type(body, media_url, media_content_type)
    logger.info("Detected input_type='%s'", input_type)

    raw_text = ""

    try:
        if input_type == "text":
            # Plain text — use Body directly
            raw_text = _sanitize_text(body or "")
            logger.info("Text input: %d chars", len(raw_text))

        elif input_type == "screenshot":
            if not media_url:
                logger.warning("screenshot type but media_url is None")
            else:
                ocr_result = extract_text_from_image(media_url)
                raw_text = _sanitize_text(ocr_result["text"])
                logger.info(
                    "OCR result: %d chars, confidence=%.2f",
                    len(raw_text),
                    ocr_result["confidence"],
                )

        elif input_type == "voice":
            if not media_url:
                logger.warning("voice type but media_url is None")
            else:
                asr_result = transcribe_audio(media_url)
                raw_text = _sanitize_text(asr_result["text"])
                logger.info(
                    "ASR result: %d chars, language='%s', duration=%.1fs",
                    len(raw_text),
                    asr_result["language"],
                    asr_result["duration_seconds"],
                )

        elif input_type == "pdf":
            if not media_url:
                logger.warning("pdf type but media_url is None")
            else:
                pdf_result = extract_text_from_pdf(media_url)
                raw_text = _sanitize_text(pdf_result["text"])
                logger.info(
                    "PDF result: %d chars, method='%s', pages=%d",
                    len(raw_text),
                    pdf_result["extraction_method"],
                    pdf_result["page_count"],
                )

        elif input_type == "url":
            url_to_scrape = (body or "").strip()
            url_result = extract_text_from_url(url_to_scrape)
            raw_text = _sanitize_text(url_result["text"])
            logger.info(
                "URL result: %d chars, method='%s'",
                len(raw_text),
                url_result["extraction_method"],
            )

    except Exception as exc:
        # Belt-and-suspenders: individual services should not raise,
        # but catch here as final safety net
        logger.error(
            "Unexpected error in run_preprocessing for input_type='%s': %s",
            input_type,
            exc,
            exc_info=True,
        )
        raw_text = ""

    result: PreprocessingResult = {
        "raw_text": raw_text,
        "input_type": input_type,
        "from_number": hashed_number,   # SHA-256 hash, not raw number
        "original_body": (body or "").strip(),
    }

    logger.info(
        "Preprocessing complete: input_type='%s', raw_text_len=%d",
        input_type,
        len(raw_text),
    )
    return result
