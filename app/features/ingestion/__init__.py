"""
Ingestion feature package for SatyaSetu.
Exposes the primary ingest() entrypoint and underlying extractors.
"""

from app.features.ingestion.asr import transcribe_audio
from app.features.ingestion.detect import detect_input_type
from app.features.ingestion.ocr import extract_text_from_bytes, extract_text_from_image
from app.features.ingestion.pdf import extract_text_from_pdf
from app.features.ingestion.sanitize import sanitize_text
from app.features.ingestion.service import ingest
from app.features.ingestion.url import extract_text_from_url

__all__ = [
    "detect_input_type",
    "extract_text_from_bytes",
    "extract_text_from_image",
    "extract_text_from_pdf",
    "extract_text_from_url",
    "ingest",
    "sanitize_text",
    "transcribe_audio",
]
