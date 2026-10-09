"""
API Check endpoint & Web demo interfaces for SatyaSetu.
Provides:
  - POST /api/check: programmatic claim verification with rich metadata
  - POST /api/ocr: screenshot image text extraction
  - GET /api/sample-claims: sample viral claims
  - GET /: SatyaSetu Main Portal Landing
  - GET /check: SatyaSetu Check Your Message screen
  - GET /processing: Live AI Pipeline Flow screen
  - GET /result: Comprehensive Fact-Check Result screen
  - GET /whatsapp & GET /demo: Realistic WhatsApp Web AI Fact-Checking Demo
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
    explanation: str
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

    # Evidence strength estimation
    strength = "HIGH"
    if len(evidence_list) == 0:
        strength = "LOW"
    elif len(evidence_list) < 2:
        strength = "MEDIUM"

    # Multilingual explanations
    exp_en = result.explanation
    exp_hi = f"{label_hi}: {exp_en}"
    exp_mr = f"{label_mr}: {exp_en}"

    return CheckResponse(
        verdict=v_str,
        verdict_label=label_en,
        verdict_label_hi=label_hi,
        verdict_label_mr=label_mr,
        verdict_emoji=v_emoji,
        evidence_strength=strength,
        explanation=result.explanation,
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

        from app.features.ingestion.ocr import (
            CONFIDENCE_THRESHOLD,
            get_ocr_reader,
            preprocess_image,
        )

        processed = preprocess_image(content)
        reader = get_ocr_reader()
        if reader is None:
            from app.features.ingestion.ocr import load_ocr_reader
            reader = load_ocr_reader()

        raw_results = reader.readtext(processed, detail=1)
        filtered_lines = [
            text
            for (_bbox, text, conf) in raw_results
            if conf >= CONFIDENCE_THRESHOLD and text.strip()
        ]
        extracted_text = " ".join(filtered_lines).strip()
        return {"success": True, "text": extracted_text}
    except Exception as exc:
        logger.warning("OCR processing error: %s", exc)
        return {"success": False, "error": str(exc), "text": ""}


@router.get("/api/sample-claims", summary="Curated viral claims for quick testing")
def sample_claims():
    """Return a curated list of sample viral forwards for demo purposes."""
    return {
        "samples": [
            {
                "claim": "Lemon juice cures cancer in 48 hours",
                "category": "Health & Medical",
                "expected_verdict": "REFUTED",
            },
            {
                "claim": "Railway Free Ticket Scheme 2025 announced for senior citizens",
                "category": "Government Schemes",
                "expected_verdict": "REFUTED",
            },
            {
                "claim": "UPI will charge 500 rupees transaction fee on transfers above 2000 rupees",
                "category": "Banking & Finance",
                "expected_verdict": "REFUTED",
            },
            {
                "claim": "CBSE Board Exam Date Sheet 2026 leaked on Telegram",
                "category": "Education",
                "expected_verdict": "REFUTED",
            },
            {
                "claim": "Government announced 5000 rupees direct bank transfer to all students this week",
                "category": "Viral Scams",
                "expected_verdict": "REFUTED",
            },
        ]
    }


# ── Frontend Web Screen Routes ──────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse, summary="SatyaSetu Main Portal")
def portal_home_page() -> str:
    """SatyaSetu Main AI Fact-Checking Portal Landing Screen."""
    return _read_html_page("index.html", "SatyaSetu — AI Fact-Checking Portal")


@router.get("/check", response_class=HTMLResponse, summary="SatyaSetu Web Submission Portal")
def check_page() -> str:
    """SatyaSetu Check Your Message Submission Screen."""
    return _read_html_page("check.html", "SatyaSetu — Check Your Message")


@router.get("/processing", response_class=HTMLResponse, summary="Live AI Verification Pipeline Flow")
def processing_page() -> str:
    """Live AI Verification Pipeline Flow Screen."""
    return _read_html_page("processing.html", "SatyaSetu — Verifying Claim")


@router.get("/result", response_class=HTMLResponse, summary="Comprehensive Result Report")
def result_page() -> str:
    """Comprehensive Fact-Check Result Report Screen."""
    return _read_html_page("result.html", "SatyaSetu — Fact-Check Result")


@router.get("/whatsapp", response_class=HTMLResponse, summary="WhatsApp Web AI Fact-Checking Demo")
@router.get("/demo", response_class=HTMLResponse, summary="WhatsApp Web AI Fact-Checking Demo")
def whatsapp_demo_page() -> str:
    """Realistic WhatsApp Web AI Fact-Checking Demo Screen."""
    return _read_html_page("whatsapp.html", "SatyaSetu — WhatsApp Web AI Fact-Checking Bot")
