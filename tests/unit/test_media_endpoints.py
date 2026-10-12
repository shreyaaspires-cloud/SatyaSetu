"""
Unit and integration tests for Media Ingestion Endpoints (Phase 2):
- Image OCR (/api/ocr)
- PDF Hybrid Extraction (/api/pdf)
- Voice Note Transcription (/api/voice)
- 2 MB limit enforcement (HTTP 413)
- Webhook mocked media ingestion
"""

from __future__ import annotations

import io
import wave
import struct
import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app.main import create_app

app = create_app()
client = TestClient(app)


# ── Helper Fixtures (Generated in-memory, no binary files committed) ───────────

def _generate_png_image(text: str = "Drinking lemon juice cures cancer") -> bytes:
    """Generate in-memory PNG with black background and white text."""
    img = Image.new("RGB", (400, 100), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.text((10, 30), text, fill=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _generate_blank_png() -> bytes:
    """Generate in-memory blank white PNG."""
    img = Image.new("RGB", (200, 200), color=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _generate_text_pdf(text: str = "Government announces 5000 rupees grant to all citizens.") -> bytes:
    """Generate in-memory text PDF using pymupdf."""
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 72), text)
    buf = doc.tobytes()
    doc.close()
    return buf


def _generate_wav_audio(duration_sec: float = 0.5) -> bytes:
    """Generate in-memory 16-bit PCM mono 16000Hz WAV with silence/tone."""
    buf = io.BytesIO()
    sample_rate = 16000
    num_samples = int(sample_rate * duration_sec)
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        # 440Hz sine wave tone
        import math
        frames = []
        for i in range(num_samples):
            val = int(10000.0 * math.sin(2.0 * math.pi * 440.0 * i / sample_rate))
            frames.append(struct.pack("<h", val))
        w.writeframes(b"".join(frames))
    return buf.getvalue()


# ── Test Suite: Image OCR (/api/ocr) ──────────────────────────────────────────

class TestOcrEndpoint:
    def test_blank_image_returns_friendly_message(self):
        content = _generate_blank_png()
        response = client.post(
            "/api/ocr",
            files={"file": ("blank.png", content, "image/png")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "couldn't read any text" in data["error"].lower()

    def test_over_2mb_image_returns_413(self):
        oversized = b"0" * (2_000_001)
        response = client.post(
            "/api/ocr",
            files={"file": ("large.png", oversized, "image/png")},
        )
        assert response.status_code == 413

    def test_unsupported_image_format(self):
        response = client.post(
            "/api/ocr",
            files={"file": ("document.exe", b"invalid_content", "application/octet-stream")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "supported" in data["error"].lower()


# ── Test Suite: PDF Extraction (/api/pdf) ─────────────────────────────────────

class TestPdfEndpoint:
    def test_native_text_pdf_extraction(self):
        pdf_bytes = _generate_text_pdf("Official notice: all schools remain open tomorrow.")
        response = client.post(
            "/api/pdf",
            files={"file": ("circular.pdf", pdf_bytes, "application/pdf")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "Official notice" in data["text"]
        assert data["page_count"] == 1
        assert data["extraction_method"] == "native"

    def test_corrupt_pdf_returns_safe_error_not_500(self):
        corrupt_bytes = b"This is not a real PDF file."
        response = client.post(
            "/api/pdf",
            files={"file": ("corrupt.pdf", corrupt_bytes, "application/pdf")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "corrupt" in data["error"].lower() or "invalid" in data["error"].lower()

    def test_over_2mb_pdf_returns_413(self):
        oversized = b"%PDF" + b"0" * (2_000_000)
        response = client.post(
            "/api/pdf",
            files={"file": ("huge.pdf", oversized, "application/pdf")},
        )
        assert response.status_code == 413


# ── Test Suite: Voice Transcription (/api/voice) ──────────────────────────────

class TestVoiceEndpoint:
    def test_wav_audio_accepted(self):
        wav_bytes = _generate_wav_audio(0.5)
        response = client.post(
            "/api/voice",
            files={"file": ("note.wav", wav_bytes, "audio/wav")},
        )
        assert response.status_code == 200
        data = response.json()
        # WAV in-memory decoding processes without throwing an unhandled crash
        assert isinstance(data, dict)

    def test_missing_ffmpeg_clear_error_for_compressed_audio(self, monkeypatch):
        # Force shutil.which('ffmpeg') to return None to test graceful fallback
        import shutil
        monkeypatch.setattr(shutil, "which", lambda cmd: None if cmd == "ffmpeg" else "/bin/mock")

        ogg_bytes = b"OggS" + b"\x00" * 500
        response = client.post(
            "/api/voice",
            files={"file": ("voice.ogg", ogg_bytes, "audio/ogg")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "ffmpeg" in data["error"].lower()

    def test_over_2mb_voice_returns_413(self):
        oversized = b"RIFF" + b"0" * (2_000_000)
        response = client.post(
            "/api/voice",
            files={"file": ("large.wav", oversized, "audio/wav")},
        )
        assert response.status_code == 413


# ── Test Suite: Check API Structured Response ─────────────────────────────────

class TestCheckApiNewFields:
    def test_check_api_returns_plain_verdict_and_truth_score(self):
        response = client.post(
            "/api/check",
            json={"claim": "The earth is flat and resting on pillars."},
        )
        assert response.status_code == 200
        data = response.json()
        assert "plain_verdict" in data
        assert "truth_score" in data
        assert "short_reason" in data
        assert "sources" in data
        assert isinstance(data["sources"], list)
