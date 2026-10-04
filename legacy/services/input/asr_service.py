"""
services/input/asr_service.py
──────────────────────────────
OpenAI Whisper ASR — voice note (.ogg) → transcript text.

Rules enforced (from IMPLEMENTATION_PLAN.md §3 + TRD §2):
  - Whisper model loaded ONCE at startup (stored in app.state)
  - Whisper (openai-whisper) accepts .ogg natively via ffmpeg — NO pydub needed
  - Media downloaded with timeout=10 — never hangs
  - Rejects files over 2 MB
  - Temp file written to disk for Whisper, deleted after transcription
  - Returns empty string on any failure — never raises
  - Detected language passed forward to skip redundant LID step
"""

from __future__ import annotations

import logging
import os
import tempfile
from typing import TypedDict

import requests
import whisper

from lib.config import settings

logger = logging.getLogger(__name__)

# ── Module-level model handle (initialised once at startup) ───────────────────
_whisper_model: whisper.Whisper | None = None

MAX_FILE_BYTES = 2 * 1024 * 1024  # 2 MB


class ASRResult(TypedDict):
    text: str
    language: str          # ISO code detected by Whisper (e.g. "hi", "en")
    duration_seconds: float


def load_whisper_model() -> whisper.Whisper:
    """
    Load Whisper model (size controlled by WHISPER_MODEL_SIZE env var, default 'base').
    Called ONCE from lifespan() in main.py.
    Model is cached in module-level variable and in app.state.whisper.
    """
    global _whisper_model
    if _whisper_model is None:
        model_size = settings.whisper_model_size  # "base" by default
        logger.info("Loading Whisper model '%s'...", model_size)
        _whisper_model = whisper.load_model(model_size)
        logger.info("Whisper model '%s' loaded successfully.", model_size)
    return _whisper_model


def get_whisper_model() -> whisper.Whisper | None:
    """Return the cached Whisper model or None if not yet loaded."""
    return _whisper_model


def _download_audio(url: str) -> bytes:
    """
    Download audio from Twilio MediaUrl using Basic Auth.
    Enforces 2 MB limit.
    Raises requests.RequestException on network failure.
    Raises ValueError if file exceeds 2 MB.
    """
    response = requests.get(
        url,
        auth=(settings.twilio_account_sid, settings.twilio_auth_token),
        timeout=10,
        stream=True,
    )
    response.raise_for_status()

    content_length = response.headers.get("Content-Length")
    if content_length and int(content_length) > MAX_FILE_BYTES:
        raise ValueError(f"Audio file too large: {content_length} bytes (max {MAX_FILE_BYTES})")

    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_content(chunk_size=8192):
        total += len(chunk)
        if total > MAX_FILE_BYTES:
            raise ValueError("Audio file exceeds 2 MB limit during download")
        chunks.append(chunk)

    return b"".join(chunks)


def transcribe_audio(url: str) -> ASRResult:
    """
    Download audio from `url` → write to temp file → Whisper transcription.

    Whisper (openai-whisper) supports .ogg natively via ffmpeg.
    No pydub conversion required (per IMPLEMENTATION_PLAN.md §3, line 88).

    Returns:
        ASRResult with 'text' (str), 'language' (ISO code), 'duration_seconds' (float)

    On ANY failure, returns ASRResult with empty text.
    Never raises — the pipeline must continue even if ASR fails.
    """
    model = get_whisper_model()
    if model is None:
        logger.error("Whisper model not loaded — was load_whisper_model() called in lifespan?")
        return ASRResult(text="", language="unknown", duration_seconds=0.0)

    try:
        audio_bytes = _download_audio(url)
    except ValueError as exc:
        logger.warning("Audio rejected: %s", exc)
        return ASRResult(text="", language="unknown", duration_seconds=0.0)
    except requests.RequestException as exc:
        logger.warning("Failed to download audio from %s: %s", url, exc)
        return ASRResult(text="", language="unknown", duration_seconds=0.0)

    # Write to a named temp file — Whisper requires a file path, not bytes
    tmp_path: str | None = None
    try:
        # Use .ogg extension so ffmpeg decodes correctly
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        logger.info("Transcribing audio (%d bytes) with Whisper...", len(audio_bytes))
        result = model.transcribe(
            tmp_path,
            fp16=False,     # CPU inference — fp16 not supported on CPU
            verbose=False,
        )

        transcript = result.get("text", "").strip()
        detected_lang = result.get("language", "unknown")
        duration = result.get("duration", 0.0)  # type: ignore[arg-type]

        logger.info(
            "Whisper transcribed %d chars, language='%s', duration=%.1fs",
            len(transcript),
            detected_lang,
            duration,
        )
        return ASRResult(
            text=transcript,
            language=detected_lang,
            duration_seconds=float(duration),
        )

    except Exception as exc:
        logger.error("Whisper transcription failed: %s", exc, exc_info=True)
        return ASRResult(text="", language="unknown", duration_seconds=0.0)

    finally:
        # Always clean up the temp file — even on exception
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass  # Best-effort cleanup
