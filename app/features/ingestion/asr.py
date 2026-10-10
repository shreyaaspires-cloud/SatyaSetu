"""
Whisper ASR voice note transcription (.ogg, .mp3, .wav to text).
Enforces file size limits, safe HTTP downloading, ffmpeg checks,
and clean temporary file cleanup.
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from typing import Any, Optional, TypedDict

from app.core.config import settings
from app.core.security import get_twilio_media_auth, safe_get

logger = logging.getLogger(__name__)

_whisper_model: Any = None
MAX_FILE_BYTES = 2 * 1024 * 1024  # 2 MB
MAX_AUDIO_DURATION_SEC = 120.0


class ASRResult(TypedDict):
    text: str
    language: str
    duration_seconds: float


def is_ffmpeg_installed() -> bool:
    """Check if ffmpeg is available on the system PATH."""
    return shutil.which("ffmpeg") is not None


def load_whisper_model(model_size: Optional[str] = None) -> Any:
    """
    Load Whisper model (size controlled by config or parameter).
    Called once from lifespan during application startup.
    """
    global _whisper_model
    if _whisper_model is None:
        import whisper

        size = model_size or settings.whisper_model_size
        logger.info("Loading Whisper model '%s'...", size)
        _whisper_model = whisper.load_model(size)
        logger.info("Whisper model '%s' loaded successfully.", size)
    return _whisper_model


def get_whisper_model() -> Any:
    """Return the cached Whisper model or None if not loaded."""
    return _whisper_model


def set_whisper_model(model: Any) -> None:
    """Set the whisper model manually (for testing / dependency injection)."""
    global _whisper_model
    _whisper_model = model


def download_audio(url: str) -> bytes:
    """
    Download audio with SSRF protection and isolated Twilio credentials.
    Enforces a strict 2 MB limit.
    """
    auth = get_twilio_media_auth(url)
    resp = safe_get(url, timeout=10, auth=auth)
    resp.raise_for_status()

    content = resp.content
    if len(content) > MAX_FILE_BYTES:
        raise ValueError(f"Audio file too large: {len(content)} bytes (max {MAX_FILE_BYTES})")
    return content


def transcribe_audio(url: str, model: Optional[Any] = None) -> ASRResult:
    """
    Download audio from url, write to temp file, transcribe with Whisper,
    and return the transcription result.
    Never raises exceptions. On failure, returns empty text with duration 0.0.
    """
    if not is_ffmpeg_installed():
        logger.error("ffmpeg is not installed or not in PATH. Cannot transcribe audio.")
        return ASRResult(text="", language="unknown", duration_seconds=0.0)

    active_model = model or get_whisper_model()
    if active_model is None:
        logger.warning("Whisper model not loaded. Returning empty result.")
        return ASRResult(text="", language="unknown", duration_seconds=0.0)

    tmp_path: Optional[str] = None
    try:
        audio_bytes = download_audio(url)

        # LOOPHOLE-05: Audio duration pre-check before heavy Whisper inference
        try:
            import io
            if audio_bytes.startswith(b"RIFF") and b"WAVE" in audio_bytes[:16]:
                import wave
                with wave.open(io.BytesIO(audio_bytes), "rb") as w:
                    frames = w.getnframes()
                    rate = w.getframerate()
                    dur = frames / float(rate) if rate else 0.0
                    if dur > MAX_AUDIO_DURATION_SEC:
                        logger.warning("Audio duration %.1fs exceeds max %0.1fs. Rejecting.", dur, MAX_AUDIO_DURATION_SEC)
                        return ASRResult(text="", language="unknown", duration_seconds=dur)
            else:
                try:
                    from pydub import AudioSegment  # type: ignore
                    seg = AudioSegment.from_file(io.BytesIO(audio_bytes))
                    dur = len(seg) / 1000.0
                    if dur > MAX_AUDIO_DURATION_SEC:
                        logger.warning("Audio duration %.1fs exceeds max %0.1fs. Rejecting.", dur, MAX_AUDIO_DURATION_SEC)
                        return ASRResult(text="", language="unknown", duration_seconds=dur)
                except Exception:
                    pass
        except Exception as probe_err:
            logger.debug("Audio duration pre-check skipped: %s", probe_err)

        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        result = active_model.transcribe(tmp_path)
        transcript = (result.get("text") or "").strip()
        detected_lang = result.get("language") or "unknown"

        segments = result.get("segments") or []
        duration = float(segments[-1].get("end", 0.0)) if segments else 0.0

        if duration > MAX_AUDIO_DURATION_SEC:
            logger.warning(
                "Audio duration (%.1fs) exceeds limit (%.1fs). Truncating.",
                duration,
                MAX_AUDIO_DURATION_SEC,
            )

        logger.info(
            "ASR transcription succeeded: %d chars, lang=%s, duration=%.1fs",
            len(transcript),
            detected_lang,
            duration,
        )
        return ASRResult(
            text=transcript,
            language=detected_lang,
            duration_seconds=round(duration, 2),
        )
    except Exception as exc:
        logger.error("Whisper transcription failed: %s", exc, exc_info=True)
        return ASRResult(text="", language="unknown", duration_seconds=0.0)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
