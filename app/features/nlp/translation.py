"""
app/features/nlp/translation.py
────────────────────────────────
Translation service translating Indic and Hinglish input into English for evidence retrieval.
Removes hardcoded phrase shortcuts (D7 fix) and supports M2M100 and Gemini translation paths.

Translation strategy
─────────────────────
Primary path  → Meta M2M100 (418M) loaded on-demand and cached per model name.
Secondary path → Google Gemini API used when: (a) M2M100 not loaded, (b) local
                 output is empty, or (c) lang_code maps to no local model entry.
Fallback       → Return original text unchanged with is_fallback=True so callers
                 can decide whether to abort or proceed with degraded accuracy.

Why two paths?
  M2M100 is deterministic and runs offline (no API cost / latency) but requires
  ~1.6 GB RAM.  Gemini is lighter in memory but adds network I/O.  The cascade
  prefers the local model and gracefully degrades to Gemini on resource-constrained
  deployments or cold-start scenarios.

Security notes
───────────────
* Text is PII-redacted (redact_for_external) before being sent to the Gemini API.
  This masks phone numbers, Aadhaar, and other PII from leaving the service boundary.
* max_length=512 input / 256 output prevents token-budget exhaustion on M2M100.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

from app.core.config import settings

logger = logging.getLogger(__name__)

# ── Model registry ────────────────────────────────────────────────────────────
# Maps ISO 639-1 language codes to their Hugging Face model identifiers.
# All entries currently use the same M2M100 checkpoint; extend this dict if
# language-specific fine-tuned models become available.
TRANSLATION_MODELS: Dict[str, str] = {
    "hi": "facebook/m2m100_418M",
    "mr": "facebook/m2m100_418M",
    "ta": "facebook/m2m100_418M",
    "te": "facebook/m2m100_418M",
    "bn": "facebook/m2m100_418M",
}

# In-process cache: model_name → (tokenizer, model).
# Avoids repeated deserialization (each M2M100 load takes ~5–10 s).
_translation_cache: Dict[str, Tuple[Any, Any]] = {}


def translate_with_gemini(text: str, lang_code: str = "") -> Optional[str]:
    """
    Translate Indic or Hinglish text into English using Gemini.
    Returns translated English text or None on failure.

    Security: text is run through redact_for_external() before dispatch so
    PII (phone numbers, Aadhaar, email addresses) never leave the service.
    The prompt instructs Gemini to output ONLY the translation to prevent
    prompt injection attacks from embedding instructions in user-supplied text.
    """
    if not settings.gemini_api_key:
        return None

    try:
        from google import genai
        from app.core.redaction import redact_for_external

        # Strip PII before the text exits the service boundary.
        redacted_text = redact_for_external(text)
        client = genai.Client(api_key=settings.gemini_api_key)
        lang_hint = f"from language code '{lang_code}' " if lang_code and lang_code != "und" else ""
        prompt = (
            f"Translate the following text {lang_hint}accurately into clear, natural English. "
            "Preserve any specific medical, factual, or cultural claims exactly. "
            "Output ONLY the English translation, with no explanation or commentary:\n\n"
            f"{redacted_text}"
        )
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
        )
        if response and response.text:
            cleaned = response.text.strip().strip('"').strip("'")
            if cleaned:
                return cleaned
    except Exception as exc:
        logger.warning("Gemini translation failed for '%s': %s", lang_code, exc)

    return None


def translate_hinglish_with_gemini(text: str) -> Optional[str]:
    """Backward compatibility wrapper for Hinglish translation."""
    return translate_with_gemini(text, "hi-Latn")


def translate_to_english(
    text: str,
    lang_code: str,
    tokenizer: Optional[Any] = None,
    model: Optional[Any] = None,
) -> Tuple[str, bool]:
    """
    Translate input text to English.
    Returns a tuple of (translated_text, is_fallback).

    If lang_code is 'en', returns original text with is_fallback=False.
    If translation model is unavailable or fails, tries Gemini translation before fallback.

    Parameters
    ──────────
    text      : Raw input text in source language.
    lang_code : ISO 639-1 language code (e.g. "hi", "ta", "hi-Latn").
    tokenizer : Optional injected M2M100Tokenizer (tests / custom deployments).
    model     : Optional injected M2M100ForConditionalGeneration.

    is_fallback flag
    ─────────────────
    True  → original text was returned unchanged; downstream should log a warning.
    False → translation succeeded (local or Gemini); use result with confidence.

    M2M100 hyper-parameters
    ────────────────────────
    max_length=512 (input)  — caps tokenization to prevent OOM on long claims.
    max_length=256 (output) — reasonable upper bound for English translation output.
    num_beams=4             — beam search gives better quality than greedy decode.
    """
    cleaned = text.strip()
    if not cleaned or lang_code == "en":
        return cleaned, False

    # Handle Hinglish translation directly via Gemini.
    # M2M100 has no explicit hi-Latn source language token.
    if lang_code == "hi-Latn":
        gemini_result = translate_with_gemini(cleaned, "hi-Latn")
        if gemini_result:
            return gemini_result, False
        logger.info("Hinglish translation fallback to original text.")
        return cleaned, True

    # Check local M2M100 model availability for this language code.
    model_name = TRANSLATION_MODELS.get(lang_code)
    if not model_name and not (tokenizer and model):
        logger.warning("No local translation model mapping configured for '%s'. Trying Gemini fallback.", lang_code)
        gemini_result = translate_with_gemini(cleaned, lang_code)
        if gemini_result:
            return gemini_result, False
        return cleaned, True

    try:
        active_tokenizer = tokenizer
        active_model = model

        # Lazy-load and cache the M2M100 model if not already in memory.
        if active_tokenizer is None or active_model is None:
            if model_name not in _translation_cache:
                from transformers import M2M100ForConditionalGeneration, M2M100Tokenizer

                tok = M2M100Tokenizer.from_pretrained(model_name)
                mod = M2M100ForConditionalGeneration.from_pretrained(model_name)
                mod.eval()  # Disable dropout; inference-only mode.
                _translation_cache[model_name] = (tok, mod)

            active_tokenizer, active_model = _translation_cache[model_name]

        import torch

        active_tokenizer.src_lang = lang_code
        inputs = active_tokenizer(cleaned, return_tensors="pt", truncation=True, max_length=512)

        with torch.no_grad():  # Disable gradient tracking to halve memory overhead.
            translated_tokens = active_model.generate(
                **inputs,
                forced_bos_token_id=active_tokenizer.get_lang_id("en"),
                max_length=256,
                num_beams=4,
            )

        decoded = active_tokenizer.decode(translated_tokens[0], skip_special_tokens=True)
        if isinstance(decoded, str) and decoded.strip():
            return decoded.strip(), False

        # Fallback to Gemini if local output was empty (degenerate beam search result).
        gemini_result = translate_with_gemini(cleaned, lang_code)
        if gemini_result:
            return gemini_result, False

        return cleaned, True

    except Exception as exc:
        logger.warning("Local translation for '%s' failed: %s. Trying Gemini fallback.", lang_code, exc)
        gemini_result = translate_with_gemini(cleaned, lang_code)
        if gemini_result:
            return gemini_result, False
        return cleaned, True
