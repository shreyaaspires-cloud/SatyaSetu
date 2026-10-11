"""
Ingestion feature package for SatyaSetu.

Exposes a unified `ingest()` entrypoint that dispatches to modality-specific extractors:
- `transcribe_audio`: OpenAI Whisper ASR for voice notes.
- `detect_input_type`: MIME-type and heuristic payload classifier.
- `extract_text_from_image` / `extract_text_from_bytes`: EasyOCR for screenshots.
- `extract_text_from_pdf`: pdfplumber + OCR fallback for scanned PDFs.
- `extract_text_from_url`: newspaper3k + Open Graph meta fallback.
- `sanitize_text`: Unicode normalisation, injection stripping, and length capping.
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
