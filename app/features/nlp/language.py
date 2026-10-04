"""
Language and script identification for Indic and English text inputs.
Includes fastText LID wrapper, Unicode script inspection, and Hinglish heuristics.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional, Tuple

logger = logging.getLogger(__name__)

# Common Romanized Hindi markers for Hinglish detection
HINGLISH_VOCABULARY = {
    "yeh", "ye", "woh", "wo", "karo", "kare", "karna", "hoga", "hogi", "honge",
    "hai", "hain", "ho", "nahi", "mat", "bhi", "aur", "ko", "ka", "ki", "ke",
    "apne", "sabko", "bhejo", "milega", "milegi", "milenge", "kripya", "dekho",
    "dekhlo", "suno", "kisi", "kya", "kyun", "kab", "kahan", "kaise", "batao",
    "paise", "paisa", "rupaye", "rupayee", "khabar", "suchna", "sarkari",
}

# Unicode ranges for primary Indic scripts
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
    """
    cleaned = text.replace("\n", " ").strip()
    if not cleaned:
        return "en", 1.0

    # 1. Check for Hinglish (Latin script + Romanized Hindi vocabulary)
    if is_hinglish(cleaned):
        logger.info("Detected Hinglish via vocabulary heuristic.")
        return "hi-Latn", 0.90

    # 2. Use fastText LID model if provided
    if ft_model is not None:
        try:
            predictions = ft_model.predict(cleaned, k=3)
            labels = predictions[0]
            scores = predictions[1]
            if labels and len(labels) > 0:
                top_label = labels[0].replace("__label__", "")
                confidence = float(scores[0]) if len(scores) > 0 else 0.5
                return top_label, round(confidence, 3)
        except Exception as exc:
            logger.warning("fastText prediction failed: %s. Falling back to script.", exc)

    # 3. Fallback based on predominant script
    script = detect_script(cleaned)
    if script == "Devanagari":
        return "hi", 0.75
    elif script == "Bengali":
        return "bn", 0.85
    elif script == "Tamil":
        return "ta", 0.85
    elif script == "Telugu":
        return "te", 0.85

    return "en", 0.80
