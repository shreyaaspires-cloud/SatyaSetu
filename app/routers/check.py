"""
API Check endpoint & Web demo interface.
Provides POST /api/check, POST /api/ocr, POST /api/pdf, GET /api/demo/config,
and serves the WhatsApp Web Desktop Demo.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.contracts.api import CheckAPIResponse, CheckRequest
from app.contracts.models import IngestedMessage
from app.core.constants import InputType
from app.core.messages import DEMO_CONFIG
from app.features.explanation.formatter import (
    VERDICT_EMOJI,
    compute_evidence_strength,
    get_verdict_label,
)
from app.pipeline import run_pipeline

logger = logging.getLogger(__name__)

router = APIRouter(tags=["check"])

# Locate static folder at workspace root
STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "static"



def _read_html_page(filename: str, fallback_title: str) -> str:
    path = STATIC_DIR / filename
    if path.exists():
        try:
            return path.read_text(encoding="utf-8")
        except Exception as exc:
            logger.error("Failed to read static/%s: %s", filename, exc)
    return f"<!DOCTYPE html><html><head><title>{fallback_title}</title></head><body><h1>{fallback_title}</h1><p>Static file {filename} is loading...</p></body></html>"


@router.post("/api/check", response_model=CheckAPIResponse, summary="Verify claim JSON endpoint")
def check_claim_api(req: CheckRequest) -> CheckAPIResponse:
    """Verify a forwarded claim or text snippet and return structured verdict and explanation."""
    raw_text = (req.text or req.claim or "").strip()
    if not raw_text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Field 'text' or 'claim' must be provided.",
        )

    ingested = IngestedMessage(
        raw_text=raw_text,
        input_type=InputType.TEXT,
        from_number="web_api_user",
        original_body=raw_text,
    )
    result = run_pipeline(ingested)

    # Flatten evidence list for easy frontend rendering
    evidence_list: List[Dict[str, Any]] = []
    all_raw_evidence: List[Any] = []
    for cr in result.claim_results:
        for ev in cr.evidence:
            all_raw_evidence.append(ev)
            evidence_list.append(
                {
                    "title": ev.title,
                    "url": ev.url,
                    "domain": ev.source_domain,
                    "snippet": ev.snippet,
                    "tier": ev.tier.value if hasattr(ev.tier, "value") else str(ev.tier),
                    "rating": ev.rating.value if hasattr(ev.rating, "value") else str(ev.rating),
                    "score": ev.score,
                }
            )

    # Localized verdict labels & emojis
    v_enum = result.overall_verdict
    v_str = v_enum.value if hasattr(v_enum, "value") else str(v_enum)
    v_emoji = VERDICT_EMOJI.get(v_enum, "❓")
    label_en = get_verdict_label(v_enum, "en")

    # Authentic evidence strength computed strictly from tiers and evidence count
    strength_label, strength_detail = compute_evidence_strength(all_raw_evidence)

    return CheckAPIResponse(
        verdict=v_str,
        verdict_label=label_en,
        verdict_emoji=v_emoji,
        evidence_strength=strength_label,
        evidence_strength_detail=strength_detail,
        explanation=result.explanation,
        formatted_reply=result.formatted_reply,
        claim=raw_text,
        claim_results=result.claim_results,
        evidence=evidence_list,
        flags=result.flags,
        timings_ms=result.timings_ms,
        language=result.language or "en",
    )


@router.post("/api/ocr", summary="Extract text from screenshot")
async def ocr_endpoint(file: UploadFile = File(...)):
    """Extract text from uploaded screenshot or image using EasyOCR."""
    try:
        content = await file.read()
        if not content:
            return {"success": False, "error": "Empty file uploaded.", "text": ""}

        from app.features.ingestion.ocr import extract_text_from_bytes
        ocr_result = extract_text_from_bytes(content)
        return {"success": bool(ocr_result.get("text")), "text": ocr_result.get("text", "")}
    except Exception as exc:
        logger.warning("OCR processing error: %s", exc)
        return {"success": False, "error": str(exc), "text": ""}


@router.post("/api/voice", summary="Transcribe uploaded voice note or audio file")
async def voice_endpoint(file: UploadFile = File(...)):
    """Transcribe uploaded audio file into text for verification."""
    import tempfile
    import os
    import io
    import wave
    import numpy as np

    try:
        content = await file.read()
        if not content:
            return {"success": False, "error": "Empty audio file uploaded.", "text": ""}

        from app.features.ingestion.asr import get_whisper_model, load_whisper_model
        model = get_whisper_model() or load_whisper_model()

        # 1. Try pure in-memory WAV decoding if content is WAV (requires no ffmpeg!)
        if content.startswith(b"RIFF") and b"WAVE" in content[:16]:
            try:
                bio = io.BytesIO(content)
                with wave.open(bio, "rb") as w:
                    channels = w.getnchannels()
                    sampwidth = w.getsampwidth()
                    framerate = w.getframerate()
                    frames = w.readframes(w.getnframes())

                if sampwidth == 2:  # 16-bit PCM
                    audio_np = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
                    if channels > 1:
                        audio_np = audio_np.reshape(-1, channels).mean(axis=1)

                    # Resample to 16000Hz if needed
                    if framerate != 16000 and len(audio_np) > 0:
                        target_len = int(len(audio_np) * 16000 / framerate)
                        indices = np.linspace(0, len(audio_np) - 1, target_len)
                        audio_np = np.interp(indices, np.arange(len(audio_np)), audio_np)

                    if model is not None and len(audio_np) > 0:
                        res = model.transcribe(audio_np, fp16=False)
                        transcript = (res.get("text") or "").strip()
                        return {"success": bool(transcript), "text": transcript, "language": res.get("language", "auto")}
            except Exception as wav_err:
                logger.warning("WAV in-memory decode warning: %s", wav_err)

        # 2. Disk file decode with whisper (works when ffmpeg or codecs are installed)
        suffix = os.path.splitext(file.filename or "")[1].lower() or ".ogg"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            if model:
                res = model.transcribe(tmp_path, fp16=False)
                transcript = (res.get("text") or "").strip()
                return {"success": bool(transcript), "text": transcript, "language": res.get("language", "auto")}
        except Exception as whisper_err:
            logger.warning("Whisper file transcription warning: %s", whisper_err)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

        return {"success": False, "error": "Could not decode audio. Please use the microphone button or submit text.", "text": ""}
    except Exception as exc:
        logger.warning("Voice endpoint error: %s", exc)
        return {"success": False, "error": str(exc), "text": ""}


@router.post("/api/pdf", summary="Extract text from uploaded PDF document")
async def pdf_endpoint(file: UploadFile = File(...)):
    """Extract text from uploaded PDF document for verification."""
    try:
        content = await file.read()
        if not content:
            return {"success": False, "error": "Empty PDF file uploaded.", "text": ""}

        from app.features.ingestion.pdf import extract_text_from_pdf_bytes
        from app.features.ingestion.ocr import get_ocr_reader
        reader = get_ocr_reader()
        result = extract_text_from_pdf_bytes(content, reader=reader)
        extracted = (result.get("text") or "").strip()

        return {
            "success": bool(extracted),
            "text": extracted,
            "page_count": result.get("page_count", 0),
            "extraction_method": result.get("extraction_method", "empty"),
        }
    except Exception as exc:
        logger.warning("PDF endpoint error: %s", exc)
        return {"success": False, "error": str(exc), "text": ""}






# ── Frontend Web Routes ─────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse, summary="WhatsApp Web AI Fact-Checking Screen")
@router.get("/whatsapp", response_class=HTMLResponse, summary="WhatsApp Web AI Fact-Checking Screen")
@router.get("/demo", response_class=HTMLResponse, summary="WhatsApp Web AI Fact-Checking Demo Screen")
def whatsapp_portal_page() -> str:
    """Realistic WhatsApp Web Desktop Screen with SatyaSetu AI Bot."""
    return _read_html_page("whatsapp.html", "SatyaSetu — WhatsApp Web AI Fact-Checking Bot")


@router.get("/api/demo/config", summary="Demo configuration & bot message strings")
def demo_config() -> JSONResponse:
    """
    Return bot message strings, supported languages, and verdict labels for the
    web demo UI. Used by the frontend to keep copy in sync with the backend.
    No secret values are exposed.
    """
    return JSONResponse(content=DEMO_CONFIG)
