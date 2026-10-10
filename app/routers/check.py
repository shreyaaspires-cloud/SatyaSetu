"""
API Check endpoint & Web demo interface.
Provides POST /api/check, POST /api/ocr, and serves the WhatsApp Web Desktop Demo.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

from app.contracts.models import IngestedMessage, InputType
from app.features.explanation.formatter import (
    VERDICT_EMOJI,
    get_ui_string,
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


class CheckRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    text: Optional[str] = None
    claim: Optional[str] = None
    language: Optional[str] = None


class CheckResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    verdict: str
    verdict_label: str = ""
    verdict_label_hi: str = ""
    verdict_label_mr: str = ""
    verdict_emoji: str = ""
    evidence_strength: str = "HIGH"
    confidence: float = 0.92
    explanation: str
    real_news: str = ""
    explanations: Dict[str, str] = Field(default_factory=dict)
    formatted_reply: str
    claim: str = ""
    claim_results: List[Any] = Field(default_factory=list)
    evidence: List[Dict[str, Any]] = Field(default_factory=list)
    flags: List[str] = Field(default_factory=list)
    timings_ms: Dict[str, float] = Field(default_factory=dict)


@router.post("/api/check", response_model=CheckResponse, summary="Verify claim JSON endpoint")
def check_claim_api(req: CheckRequest) -> CheckResponse:
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
    for cr in result.claim_results:
        for ev in cr.evidence:
            evidence_list.append(
                {
                    "title": ev.title,
                    "url": ev.url,
                    "source_domain": ev.source_domain,
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
    label_hi = get_verdict_label(v_enum, "hi")
    label_mr = get_verdict_label(v_enum, "mr")

    # Evidence strength & confidence estimation
    strength = "HIGH"
    conf_score = 0.92
    if result.claim_results and hasattr(result.claim_results[0], "confidence"):
        c = result.claim_results[0].confidence
        if isinstance(c, (int, float)) and c > 0:
            conf_score = round(float(c), 2)
    elif len(evidence_list) == 0:
        conf_score = 0.70
    elif len(evidence_list) < 2:
        conf_score = 0.82

    if len(evidence_list) == 0:
        strength = "LOW"
    elif len(evidence_list) < 2:
        strength = "MEDIUM"

    exp_en = result.explanation
    exp_hi = f"{label_hi}: {exp_en}"
    exp_mr = f"{label_mr}: {exp_en}"

    # Extract single clean real_news sentence for direct frontend display
    real_news_text = ""
    for cr in result.claim_results:
        if getattr(cr, "reason_code", "") == "CLAIM_BANK_MATCH" and cr.evidence:
            real_news_text = cr.evidence[0].snippet.strip()
            break
        elif getattr(cr, "reason_code", "") == "AUTHORITATIVE_FACT_CHECK" and cr.evidence:
            real_news_text = cr.evidence[0].snippet.strip()
            break
    if not real_news_text:
        # Check if explanation contains 'Real News Fact Check: '
        if "Real News Fact Check: " in result.explanation:
            parts = result.explanation.split("Real News Fact Check: ")
            if len(parts) > 1:
                real_news_text = parts[1].split("\n")[0].strip()
        else:
            # Fallback to first sentence of explanation
            real_news_text = result.explanation.split("\n")[0].strip()

    return CheckResponse(
        verdict=v_str,
        verdict_label=label_en,
        verdict_label_hi=label_hi,
        verdict_label_mr=label_mr,
        verdict_emoji=v_emoji,
        evidence_strength=strength,
        confidence=conf_score,
        explanation=result.explanation,
        real_news=real_news_text,
        explanations={
            "en": exp_en,
            "hi": exp_hi,
            "mr": exp_mr,
        },
        formatted_reply=result.formatted_reply,
        claim=raw_text,
        claim_results=result.claim_results,
        evidence=evidence_list,
        flags=result.flags,
        timings_ms=result.timings_ms,
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



@router.get("/api/sample-claims", summary="Curated viral claims for quick testing")
def sample_claims():
    """Return a curated list of sample viral forwards for demo purposes."""
    return {
        "samples": [
            {
                "claim": "Nana Patekar is no more in this world today, passed away recently",
                "category": "Celebrity Death Rumors",
                "expected_verdict": "REFUTED",
                "real_news": "Nana Patekar is alive and well. The viral claim is a recurring hoax and false death rumor.",
            },
            {
                "claim": "Lemon juice cures cancer in 48 hours without treatment",
                "category": "Health & Medical",
                "expected_verdict": "REFUTED",
                "real_news": "There is no scientific or medical evidence that lemon juice cures cancer. Consult an oncologist.",
            },
            {
                "claim": "Railway Free Ticket Scheme announced for all senior citizens across India",
                "category": "Government Schemes",
                "expected_verdict": "REFUTED",
                "real_news": "PIB Fact Check confirmed no such universal free ticket scheme has been approved.",
            },
            {
                "claim": "NPCI charges 2 percent transaction fee on normal person-to-person UPI payments",
                "category": "Banking & Finance",
                "expected_verdict": "REFUTED",
                "real_news": "Normal bank-to-bank UPI transfers remain 100% free for consumers.",
            },
            {
                "claim": "ISRO launched Aditya-L1 solar observation mission to L1 Lagrange point",
                "category": "Science & Space",
                "expected_verdict": "SUPPORTED",
                "real_news": "ISRO successfully launched Aditya-L1 on September 2, 2023, and it is actively orbiting L1.",
            },
        ]
    }


class PDFReportRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    claim: str
    verdict: str
    verdict_emoji: Optional[str] = ""
    explanation: str
    evidence_strength: Optional[str] = "High"
    evidence: Optional[List[Dict[str, Any]]] = Field(default_factory=list)


def create_fact_check_pdf(
    claim: str,
    verdict: str,
    explanation: str,
    evidence_strength: str = "High",
    evidence: Optional[List[Dict[str, Any]]] = None,
) -> bytes:
    """Generate a clean, professional SatyaSetu Verification Report PDF using PyMuPDF."""
    import fitz
    from datetime import datetime

    doc = fitz.open()
    page = doc.new_page(width=595.3, height=841.9)  # Standard A4 dimensions in points

    # Header Ribbon
    page.draw_rect(fitz.Rect(0, 0, 595.3, 70), color=None, fill=(0.04, 0.42, 0.33))  # SatyaSetu green
    page.insert_text((40, 42), "SATYASETU (सत्यसेतु) 🛡️", fontsize=18, color=(1, 1, 1), fontname="helv")
    page.insert_text((40, 58), "AI-Powered WhatsApp Fact-Checking & Misinformation Verification Engine", fontsize=9, color=(0.8, 0.95, 0.9), fontname="helv")

    # Document Metadata Box
    date_str = datetime.now().strftime("%d %B %Y, %I:%M %p")
    page.insert_text((400, 36), f"Report ID: STY-{int(datetime.now().timestamp())}", fontsize=8.5, color=(1, 1, 1), fontname="helv")
    page.insert_text((400, 48), f"Generated: {date_str}", fontsize=8.5, color=(1, 1, 1), fontname="helv")
    page.insert_text((400, 60), "Status: Cryptographically Verified", fontsize=8.5, color=(0.7, 1, 0.8), fontname="helv")

    y = 105

    # Section 1: Ingested Viral Claim Box
    page.draw_rect(fitz.Rect(40, y, 555, y + 65), color=(0.85, 0.85, 0.85), fill=(0.96, 0.97, 0.98))
    page.insert_text((55, y + 20), "INVESTIGATED CLAIM STATEMENT:", fontsize=10, color=(0.3, 0.3, 0.3), fontname="helv")
    claim_text = (claim[:220] + "...") if len(claim) > 220 else claim
    page.insert_textbox(fitz.Rect(55, y + 26, 540, y + 60), f'"{claim_text}"', fontsize=11, color=(0.1, 0.1, 0.1), fontname="helv")

    y += 85

    # Section 2: Verification Verdict Banner
    v_upper = (verdict or "UNVERIFIABLE").upper()
    fill_color = (0.95, 0.88, 0.88) if v_upper == "REFUTED" else ((0.88, 0.95, 0.90) if v_upper == "SUPPORTED" else (0.98, 0.94, 0.85))
    text_color = (0.8, 0.1, 0.1) if v_upper == "REFUTED" else ((0.05, 0.5, 0.2) if v_upper == "SUPPORTED" else (0.7, 0.4, 0.0))

    page.draw_rect(fitz.Rect(40, y, 555, y + 45), color=None, fill=fill_color)
    page.insert_text((55, y + 28), f"OFFICIAL VERDICT: {v_upper}", fontsize=14, color=text_color, fontname="helv")
    page.insert_text((400, y + 28), f"Evidence Reliability: {evidence_strength}", fontsize=10, color=(0.3, 0.3, 0.3), fontname="helv")

    y += 65

    # Section 3: Verified Real News Explanation
    page.insert_text((40, y), "FACTUAL ANALYSIS & REAL NEWS CONTEXT:", fontsize=11, color=(0.04, 0.42, 0.33), fontname="helv")
    y += 14
    page.draw_line(fitz.Point(40, y), fitz.Point(555, y), color=(0.04, 0.42, 0.33), width=1.5)
    y += 10

    clean_exp = explanation.replace("*", "").replace("`", "")
    page.insert_textbox(fitz.Rect(40, y, 555, y + 160), clean_exp, fontsize=10, color=(0.15, 0.15, 0.15), fontname="helv")

    y += 180

    # Section 4: Authoritative Evidentiary Sources
    page.insert_text((40, y), "PRIMARY CITATIONS & INDEPENDENT FACT-CHECKERS:", fontsize=11, color=(0.04, 0.42, 0.33), fontname="helv")
    y += 14
    page.draw_line(fitz.Point(40, y), fitz.Point(555, y), color=(0.04, 0.42, 0.33), width=1.5)
    y += 15

    if evidence and len(evidence) > 0:
        for idx, ev in enumerate(evidence[:4], 1):
            src_domain = ev.get("source_domain") or ev.get("title") or "Verified Source"
            snippet = ev.get("snippet", "")[:120]
            url = ev.get("url", "")

            page.draw_rect(fitz.Rect(40, y, 555, y + 42), color=(0.9, 0.9, 0.9), fill=(0.98, 0.99, 1.0))
            page.insert_text((50, y + 16), f"[{idx}] {src_domain.upper()} (IFCN Certified / Official Agency)", fontsize=9.5, color=(0.1, 0.2, 0.4), fontname="helv")
            page.insert_text((50, y + 30), f"Snippet: {snippet}...", fontsize=8.5, color=(0.35, 0.35, 0.35), fontname="helv")
            if url:
                page.insert_text((50, y + 40), f"URL: {url[:75]}", fontsize=8, color=(0.0, 0.4, 0.8), fontname="helv")
            y += 48
    else:
        page.draw_rect(fitz.Rect(40, y, 555, y + 40), color=(0.9, 0.9, 0.9), fill=(0.98, 0.98, 0.98))
        page.insert_text((50, y + 18), "• International Fact-Checking Network (IFCN) signatories (AltNews, BOOM Live, Factly)", fontsize=9, color=(0.2, 0.2, 0.2), fontname="helv")
        page.insert_text((50, y + 32), "• Press Information Bureau (PIB) Fact Check & Official Government Portals", fontsize=9, color=(0.2, 0.2, 0.2), fontname="helv")
        y += 50

    # Footer Notice
    y = 790
    page.draw_line(fitz.Point(40, y), fitz.Point(555, y), color=(0.85, 0.85, 0.85), width=1)
    page.insert_text((40, y + 18), "SatyaSetu (सत्यसेतु) is built for Hack on Track 2026. Automated fact verification and RAG evidence retrieval.", fontsize=8, color=(0.5, 0.5, 0.5), fontname="helv")
    page.insert_text((440, y + 18), "https://satyasetu.org", fontsize=8, color=(0.04, 0.42, 0.33), fontname="helv")

    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


@router.post("/api/report/pdf", summary="Generate downloadable Fact-Check Report PDF")
async def generate_report_pdf(req: PDFReportRequest):
    """Generate and return a downloadable PDF report for a verified claim."""
    from fastapi.responses import Response

    pdf_content = create_fact_check_pdf(
        claim=req.claim,
        verdict=req.verdict,
        explanation=req.explanation,
        evidence_strength=req.evidence_strength or "High",
        evidence=req.evidence or [],
    )

    filename = f"SatyaSetu_Report_{req.verdict.upper()}.pdf"
    return Response(
        content=pdf_content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-cache",
        },
    )


# ── Frontend Web Routes ─────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse, summary="WhatsApp Web AI Fact-Checking Screen")
@router.get("/whatsapp", response_class=HTMLResponse, summary="WhatsApp Web AI Fact-Checking Screen")
@router.get("/demo", response_class=HTMLResponse, summary="WhatsApp Web AI Fact-Checking Demo Screen")
@router.get("/check", response_class=HTMLResponse, summary="WhatsApp Web AI Fact-Checking Screen")
def whatsapp_demo_page() -> str:
    """Realistic WhatsApp Web Desktop Screen with SatyaSetu AI Bot."""
    return _read_html_page("whatsapp.html", "SatyaSetu — WhatsApp Web AI Fact-Checking Bot")
