"""
API Check endpoint & Web demo interface.
Provides POST /api/check for direct programmatic testing
and GET /check / GET /demo for judge evaluations.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

from app.contracts.models import IngestedMessage, InputType
from app.pipeline import run_pipeline

logger = logging.getLogger(__name__)

router = APIRouter(tags=["check"])


class CheckRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    text: Optional[str] = None
    claim: Optional[str] = None
    language: Optional[str] = None


class CheckResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    verdict: str
    explanation: str
    formatted_reply: str
    claim_results: List[Any] = Field(default_factory=list)
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

    return CheckResponse(
        verdict=result.overall_verdict.value,
        explanation=result.explanation,
        formatted_reply=result.formatted_reply,
        claim_results=result.claim_results,
        flags=result.flags,
        timings_ms=result.timings_ms,
    )


@router.get("/demo", response_class=HTMLResponse, summary="Interactive Web Demo for Judges")
@router.get("/check", response_class=HTMLResponse, summary="Interactive Web Demo for Judges")
def demo_page() -> str:
    """HTML web page for judges to test claim verification without joining Twilio sandbox."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SatyaSetu — Claim Verification Engine Demo</title>
    <style>
        :root {
            --bg-primary: #0a0e17;
            --bg-card: #131b2e;
            --accent-cyan: #00f2fe;
            --accent-blue: #4facfe;
            --text-main: #f0f4f8;
            --text-muted: #94a3b8;
            --border: #1e293b;
            --success: #10b981;
            --danger: #ef4444;
            --warning: #f59e0b;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: var(--bg-primary);
            color: var(--text-main);
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            padding: 40px 20px;
        }
        .container {
            max-width: 760px;
            width: 100%;
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 32px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.4);
        }
        .header { text-align: center; margin-bottom: 24px; }
        .logo {
            font-size: 28px;
            font-weight: 800;
            background: linear-gradient(135deg, var(--accent-cyan), var(--accent-blue));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .subtitle { color: var(--text-muted); font-size: 14px; margin-top: 6px; }
        textarea {
            width: 100%;
            min-height: 120px;
            background: #0f172a;
            border: 1px solid var(--border);
            border-radius: 10px;
            padding: 14px;
            color: #fff;
            font-size: 15px;
            resize: vertical;
            outline: none;
            transition: border-color 0.2s;
        }
        textarea:focus { border-color: var(--accent-cyan); }
        .btn {
            background: linear-gradient(135deg, #00f2fe, #4facfe);
            color: #04111d;
            font-weight: 700;
            border: none;
            border-radius: 8px;
            padding: 12px 24px;
            font-size: 15px;
            cursor: pointer;
            width: 100%;
            margin-top: 14px;
            transition: opacity 0.2s;
        }
        .btn:hover { opacity: 0.9; }
        .btn:disabled { opacity: 0.5; cursor: not-allowed; }
        .result-box {
            margin-top: 24px;
            display: none;
            border-top: 1px solid var(--border);
            padding-top: 20px;
        }
        .verdict-badge {
            display: inline-block;
            padding: 6px 14px;
            border-radius: 20px;
            font-weight: 700;
            font-size: 14px;
            margin-bottom: 12px;
            letter-spacing: 0.5px;
        }
        .SUPPORTED { background: rgba(16, 185, 129, 0.2); color: #34d399; border: 1px solid #10b981; }
        .REFUTED { background: rgba(239, 68, 68, 0.2); color: #f87171; border: 1px solid #ef4444; }
        .PARTIALLY_SUPPORTED { background: rgba(245, 158, 11, 0.2); color: #fbbf24; border: 1px solid #f59e0b; }
        .OUTDATED { background: rgba(217, 119, 6, 0.2); color: #fcd34d; border: 1px solid #d97706; }
        .UNVERIFIABLE { background: rgba(148, 163, 184, 0.2); color: #cbd5e1; border: 1px solid #64748b; }
        .reply-preview {
            background: #090d16;
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 16px;
            white-space: pre-wrap;
            font-size: 14px;
            line-height: 1.5;
            color: #e2e8f0;
            margin-top: 12px;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="logo">SatyaSetu</div>
            <div class="subtitle">GenAI WhatsApp & Web Claim Verification Engine · Hack on Track Demo</div>
        </div>
        <textarea id="claimInput" placeholder="Paste a forwarded claim or news snippet here to verify..."></textarea>
        <button class="btn" id="verifyBtn" onclick="verifyClaim()">Verify Claim</button>
        <div class="result-box" id="resultBox">
            <span class="verdict-badge" id="verdictBadge"></span>
            <div style="font-size: 13px; color: var(--text-muted); margin-bottom: 8px;">WhatsApp Formatted Response Preview:</div>
            <div class="reply-preview" id="replyPreview"></div>
        </div>
    </div>
    <script>
        async function verifyClaim() {
            const input = document.getElementById("claimInput").value.trim();
            if (!input) return;
            const btn = document.getElementById("verifyBtn");
            const box = document.getElementById("resultBox");
            const badge = document.getElementById("verdictBadge");
            const preview = document.getElementById("replyPreview");

            btn.disabled = true;
            btn.innerText = "Verifying...";
            box.style.display = "none";

            try {
                const res = await fetch("/api/check", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ text: input })
                });
                const data = await res.json();
                badge.className = "verdict-badge " + data.verdict;
                badge.innerText = "VERDICT: " + data.verdict.replace(/_/g, " ");
                preview.innerText = data.formatted_reply || data.explanation;
                box.style.display = "block";
            } catch (err) {
                alert("Verification failed: " + err);
            } finally {
                btn.disabled = false;
                btn.innerText = "Verify Claim";
            }
        }
    </script>
</body>
</html>
"""
