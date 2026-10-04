"""
Translation service translating Indic and Hinglish input into English for evidence retrieval.
Removes hardcoded phrase shortcuts (D7 fix) and supports M2M100 and Gemini translation paths.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

from app.core.config import settings

logger = logging.getLogger(__name__)

TRANSLATION_MODELS: Dict[str, str] = {
    "hi": "facebook/m2m100_418M",
    "mr": "facebook/m2m100_418M",
    "ta": "facebook/m2m100_418M",
    "te": "facebook/m2m100_418M",
    "bn": "facebook/m2m100_418M",
}

_translation_cache: Dict[str, Tuple[Any, Any]] = {}


def translate_hinglish_with_gemini(text: str) -> Optional[str]:
    """
    Translate Hinglish (Hindi written in Latin script) into English using Gemini.
    Returns translated English text or None on failure.
    """
    if not settings.gemini_api_key:
        return None

    try:
        from google import genai

        client = genai.Client(api_key=settings.gemini_api_key)
        prompt = (
            "Translate the following Hinglish (Hindi in Roman script) text accurately into standard English. "
            "Output ONLY the English translation, with no explanation or commentary:\n\n"
            f"{text}"
        )
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
        )
        if response and response.text:
            return response.text.strip()
    except Exception as exc:
        logger.warning("Gemini Hinglish translation failed: %s", exc)

    return None


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
    If translation model is unavailable or fails, returns original text with is_fallback=True.
    """
    cleaned = text.strip()
    if not cleaned or lang_code == "en":
        return cleaned, False

    # Handle Hinglish translation
    if lang_code == "hi-Latn":
        gemini_result = translate_hinglish_with_gemini(cleaned)
        if gemini_result:
            return gemini_result, False
        logger.info("Hinglish translation fallback to original text.")
        return cleaned, True

    # Check local M2M100 model availability
    model_name = TRANSLATION_MODELS.get(lang_code)
    if not model_name and not (tokenizer and model):
        logger.warning("No translation model mapping configured for '%s'.", lang_code)
        return cleaned, True

    try:
        active_tokenizer = tokenizer
        active_model = model

        if active_tokenizer is None or active_model is None:
            if model_name not in _translation_cache:
                from transformers import M2M100ForConditionalGeneration, M2M100Tokenizer

                tok = M2M100Tokenizer.from_pretrained(model_name)
                mod = M2M100ForConditionalGeneration.from_pretrained(model_name)
                mod.eval()
                _translation_cache[model_name] = (tok, mod)

            active_tokenizer, active_model = _translation_cache[model_name]

        import torch

        active_tokenizer.src_lang = lang_code
        inputs = active_tokenizer(cleaned, return_tensors="pt", truncation=True, max_length=512)

        with torch.no_grad():
            translated_tokens = active_model.generate(
                **inputs,
                forced_bos_token_id=active_tokenizer.get_lang_id("en"),
                max_length=256,
                num_beams=4,
            )

        decoded = active_tokenizer.decode(translated_tokens[0], skip_special_tokens=True)
        if isinstance(decoded, str) and decoded.strip():
            return decoded.strip(), False

        return cleaned, True

    except Exception as exc:
        logger.warning("Local translation for '%s' failed: %s. Using fallback.", lang_code, exc)
        return cleaned, True
