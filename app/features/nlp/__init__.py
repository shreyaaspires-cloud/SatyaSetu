"""
NLP feature package for SatyaSetu.
Provides language detection, translation, keyphrase extraction,
claim extraction, forward pressure detection, and check-worthiness scoring.
"""

from app.features.nlp.claims import extract_claims, has_forward_pressure, split_sentences
from app.features.nlp.keywords import extract_keywords
from app.features.nlp.language import detect_language, detect_script, is_hinglish
from app.features.nlp.translation import translate_to_english
from app.features.nlp.worthiness import is_check_worthy, score_check_worthiness

__all__ = [
    "detect_language",
    "detect_script",
    "extract_claims",
    "extract_keywords",
    "has_forward_pressure",
    "is_check_worthy",
    "is_hinglish",
    "score_check_worthiness",
    "split_sentences",
    "translate_to_english",
]
