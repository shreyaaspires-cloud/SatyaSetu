"""
app/features/nlp/language.py
─────────────────────────────
Language and script identification for Indic and English text inputs.
Includes fastText LID wrapper, Unicode script inspection, and Hinglish heuristics.

Architecture
─────────────
Detection priority (highest to lowest confidence):

  1. Hinglish heuristic  — vocabulary-overlap check for Romanized Hindi
  2. fastText LID model  — compact multilingual lid.176.bin (~900 KB) loaded at
                           startup; predicts ISO 639-1 codes with confidence.
  3. Unicode script scan — character codepoint range matching as last resort.

The tiered approach ensures we never fail hard on language detection: even if
the fastText model is absent (models/lid.176.bin not found) the script-based
fallback still correctly routes Devanagari, Bengali, Tamil, and Telugu inputs.

Indic-first design:  Hindi, Marathi, Bengali, Tamil, and Telugu are first-class
citizens because SatyaSetu's primary user base communicates in these languages.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional, Tuple

logger = logging.getLogger(__name__)

# Module-level singleton for the fastText LID model.
# Injected by app.main lifespan and overrideable in tests via set_ft_model().
_ft_model: Any = None


def get_ft_model() -> Any:
    """Return the module-level fastText LID singleton (may be None)."""
    return _ft_model


def set_ft_model(model: Any) -> None:
    """Inject a fastText model instance; used by lifespan and unit tests."""
    global _ft_model
    _ft_model = model


# ── Hinglish vocabulary ───────────────────────────────────────────────────────
# Common Romanized Hindi markers for Hinglish detection.
# Threshold: ≥2 distinct matches in the token set triggers hi-Latn classification.
HINGLISH_VOCABULARY = {
    "yeh", "ye", "woh", "wo", "karo", "kare", "karna", "hoga", "hogi", "honge",
    "hai", "hain", "ho", "nahi", "mat", "bhi", "aur", "ko", "ka", "ki", "ke",
    "apne", "sabko", "bhejo", "milega", "milegi", "milenge", "kripya", "dekho",
    "dekhlo", "suno", "kisi", "kya", "kyun", "kab", "kahan", "kaise", "batao",
    "paise", "paisa", "rupaye", "rupayee", "khabar", "suchna", "sarkari",
}

# ── Script Unicode ranges ─────────────────────────────────────────────────────
# Unicode ranges for primary Indic scripts + Latin baseline.
# Derived from Unicode Character Database block boundaries.
SCRIPT_RANGES = {
    "Devanagari": (0x0900, 0x097F),
    "Bengali": (0x0980, 0x09FF),
    "Tamil": (0x0B80, 0x0BFF),
    "Telugu": (0x0C00, 0x0C7F),
    "Latin": (0x0041, 0x007A),  # Includes uppercase/lowercase basic Latin
}


def detect_script(text: str) -> str:
    """
    Detect the predominant writing system based on Unicode character codepoints.

    Returns the SCRIPT_RANGES key with the highest character frequency.
    Falls back to 'Latin' when no script registers any codepoint hits.
    """
    counts = {script: 0 for script in SCRIPT_RANGES}
    for ch in text:
        cp = ord(ch)
        for script, (start, end) in SCRIPT_RANGES.items():
            if start <= cp <= end:
                counts[script] += 1
                break

    sorted_scripts = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    top_script, top_count = sorted_scripts[0]
    if top_count > 0:
        return top_script
    return "Latin"


def is_hinglish(text: str) -> bool:
    """
    Heuristic check for Hindi written in Latin script (Hinglish).
    Checks if Latin script dominates and contains 2 or more distinct Hinglish tokens.

    Returns True only when both conditions hold:
      • The dominant script is Latin (no Devanagari codepoints dominate).
      • At least 2 distinct vocabulary tokens from HINGLISH_VOCABULARY appear in the text.
    """
    script = detect_script(text)
    if script != "Latin":
        return False

    tokens = re.findall(r"\b[a-zA-Z]+\b", text.lower())
    if not tokens:
        return False

    matching_tokens = set(tokens).intersection(HINGLISH_VOCABULARY)
    return len(matching_tokens) >= 2


def detect_language(text: str, ft_model: Optional[Any] = None) -> Tuple[str, float]:
    """
    Detect the language of the input text.
    Returns (lang_code, confidence).

    Detection cascade
    ──────────────────
    1. Hinglish vocabulary heuristic → "hi-Latn", 0.90
    2. fastText LID (lid.176.bin, k=3 labels) → top ISO code, raw score
    3. Unicode script fallback:
       - Devanagari → try Marathi markers first, then Hindi
       - Bengali / Tamil / Telugu → language code with 0.85 confidence
       - Latin default → "en", 0.80

    Marathi vs. Hindi disambiguation:
    Both use Devanagari; we use a curated set of grammatical Marathi markers
    that are statistically absent in standard Hindi to break the tie.
    """
    cleaned = text.replace("\n", " ").strip()
    if not cleaned:
        return "en", 1.0

    # 1. Check for Hinglish (Latin script + Romanized Hindi vocabulary)
    if is_hinglish(cleaned):
        logger.info("Detected Hinglish via vocabulary heuristic.")
        return "hi-Latn", 0.90

    # 2. Use fastText LID model if provided or loaded
    active_ft = ft_model if ft_model is not None else get_ft_model()
    if active_ft is not None:
        try:
            predictions = active_ft.predict(cleaned, k=3)
            labels = predictions[0]
            scores = predictions[1]
            if labels and len(labels) > 0:
                top_label = labels[0].replace("__label__", "")
                confidence = float(scores[0]) if len(scores) > 0 else 0.5
                return top_label, round(confidence, 3)
        except Exception as exc:
            logger.warning("fastText prediction failed: %s. Falling back to script.", exc)

    # Marathi-specific character/word markers that don't appear in Hindi.
    # These are common Marathi grammatical endings and words using Devanagari.
    MARATHI_MARKERS = {
        "आहे", "आहेत", "केली", "केले", "आहेस", "आपण", "म्हणजे", "म्हणून",
        "परंतु", "तरी", "मात्र", "असे", "असलेले", "असताना", "त्यांनी",
        "येथे", "तेव्हा", "नाही", "नव्हते", "होते", "होती", "झाले", "झाली",
        "होतो", "होती", "झाला", "झाल्या", "असतो", "असते", "कारण", "म्हटले",
    }

    # 3. Fallback based on predominant script
    script = detect_script(cleaned)
    if script == "Devanagari":
        # Try to distinguish Marathi from Hindi via unique markers.
        # Two or more marker hits is strong evidence of Marathi prose.
        marathi_hits = sum(1 for marker in MARATHI_MARKERS if marker in cleaned)
        if marathi_hits >= 2:
            logger.info("Detected Marathi via Devanagari script + %d Marathi markers.", marathi_hits)
            return "mr", 0.82
        return "hi", 0.75
    elif script == "Bengali":
        return "bn", 0.85
    elif script == "Tamil":
        return "ta", 0.85
    elif script == "Telugu":
        return "te", 0.85

    return "en", 0.80
