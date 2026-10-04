"""
Ingestion orchestrator service.
Routes incoming WhatsApp payloads across OCR, ASR, PDF, URL, and Text extractors
and yields a validated IngestedMessage contract.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.contracts.models import IngestedMessage
from app.core.constants import InputType
from app.core.redaction import hash_identifier
from app.features.ingestion.asr import transcribe_audio
from app.features.ingestion.detect import detect_input_type
from app.features.ingestion.ocr import extract_text_from_image
from app.features.ingestion.pdf import extract_text_from_pdf
from app.features.ingestion.sanitize import sanitize_text
from app.features.ingestion.url import extract_text_from_url

logger = logging.getLogger(__name__)


def ingest(
    body: Optional[str] = None,
    media_url: Optional[str] = None,
    media_content_type: Optional[str] = None,
    from_number: str = "",
    ocr_reader: Optional[Any] = None,
    whisper_model: Optional[Any] = None,
    reply_to: Optional[str] = None,
) -> IngestedMessage:
    """
    Ingest an incoming message payload into a standardized IngestedMessage.
    Synchronous function (D2 fixed) designed for clean execution in worker threads.
    Never raises exceptions. On failure, returns empty raw_text.
    """
    hashed_from = hash_identifier(from_number) if from_number else "anonymous"
    input_type = detect_input_type(body, media_url, media_content_type)
    original_body = (body or "").strip()

    raw_text = ""
    ocr_confidence: Optional[float] = None
    audio_duration: Optional[float] = None
    source_url: Optional[str] = None
    metadata: dict[str, Any] = {}

    if reply_to:
        metadata["reply_to"] = reply_to

    try:
        if input_type == InputType.TEXT:
            raw_text = sanitize_text(original_body)

        elif input_type == InputType.SCREENSHOT:
            if media_url:
                ocr_result = extract_text_from_image(media_url, reader=ocr_reader)
                raw_text = sanitize_text(ocr_result["text"])
                ocr_confidence = ocr_result["confidence"]
                metadata["ocr_confidence"] = ocr_confidence

        elif input_type == InputType.VOICE:
            if media_url:
                asr_result = transcribe_audio(media_url, model=whisper_model)
                raw_text = sanitize_text(asr_result["text"])
                audio_duration = asr_result["duration_seconds"]
                metadata["asr_language"] = asr_result["language"]
                metadata["audio_duration_sec"] = audio_duration

        elif input_type == InputType.PDF:
            if media_url:
                pdf_result = extract_text_from_pdf(media_url, reader=ocr_reader)
                raw_text = sanitize_text(pdf_result["text"])
                metadata["pdf_pages"] = pdf_result["page_count"]
                metadata["pdf_method"] = pdf_result["extraction_method"]

        elif input_type == InputType.URL:
            target_url = original_body
            source_url = target_url
            url_result = extract_text_from_url(target_url)
            raw_text = sanitize_text(url_result["text"])
            metadata["url_title"] = url_result["title"]
            metadata["url_method"] = url_result["extraction_method"]

    except Exception as exc:
        logger.error("Ingestion failed unexpectedly for %s: %s", input_type, exc, exc_info=True)
        raw_text = ""

    return IngestedMessage(
        raw_text=raw_text,
        input_type=input_type,
        from_number=hashed_from,
        original_body=original_body,
        ocr_confidence=ocr_confidence,
        audio_duration_sec=audio_duration,
        source_url=source_url,
        metadata=metadata,
    )
