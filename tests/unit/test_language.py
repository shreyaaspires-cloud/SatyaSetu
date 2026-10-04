"""
Unit tests for language detection, script analysis, Hinglish heuristics,
and translation service.
"""

from unittest.mock import MagicMock

from app.features.nlp.language import (
    detect_language,
    detect_script,
    is_hinglish,
)
from app.features.nlp.translation import translate_to_english


def test_detect_script():
    assert detect_script("नमस्ते भारत") == "Devanagari"
    assert detect_script("হ্যালো বাংলাদেশ") == "Bengali"
    assert detect_script("வணக்கம் தமிழ்நாடு") == "Tamil"
    assert detect_script("నమస్కారం ఆంధ్రప్రదేశ్") == "Telugu"
    assert detect_script("Hello world") == "Latin"


def test_is_hinglish():
    hinglish_text = "Yeh message sabhi WhatsApp groups me share karo, Modi ji free recharge de rahe hain"
    assert is_hinglish(hinglish_text) is True

    pure_english = "Drinking lemon water cures cancer instantly according to research"
    assert is_hinglish(pure_english) is False

    hindi_devanagari = "यह संदेश सभी ग्रुप में शेयर करें"
    assert is_hinglish(hindi_devanagari) is False


def test_detect_language_fasttext_mock():
    mock_ft = MagicMock()
    mock_ft.predict.return_value = (("__label__hi", "__label__mr", "__label__en"), [0.95, 0.03, 0.02])

    lang, conf = detect_language("नमस्ते आप कैसे हैं", ft_model=mock_ft)
    assert lang == "hi"
    assert conf == 0.95


def test_detect_language_hinglish():
    text = "Yeh message forward karo sabko"
    lang, conf = detect_language(text)
    assert lang == "hi-Latn"
    assert conf >= 0.85


def test_detect_language_script_fallback():
    # Without fastText model, script fallback should work
    lang, conf = detect_language("வணக்கம்")
    assert lang == "ta"
    assert conf > 0.7


def test_translation_english_pass_through():
    text = "This is already in English"
    translated, is_fallback = translate_to_english(text, "en")
    assert translated == text
    assert is_fallback is False


def test_translation_d7_hack_removed():
    # Defect D7 test: the hardcoded PM KISAN phrase shortcut must NOT exist
    pm_kisan_hi = "यह मैसेज फॉरवर्ड करो, PM Kisan का पैसा मिलेगा"

    translated, is_fallback = translate_to_english(pm_kisan_hi, "hi")
    # Must NOT return the hardcoded English demo hack
    assert translated != "Forward this message and you will receive money under PM-KISAN."
    # If no model is loaded (or mocked decoder returns non-string), it safely falls back
    assert is_fallback is True
    assert translated == pm_kisan_hi
