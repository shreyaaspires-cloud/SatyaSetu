"""
NLP feature package for SatyaSetu.

Provides a composable pipeline of language processing capabilities:
- Language Detection: Script + ISO-639 code identification with Hinglish awareness.
- Translation: M2M100 local model with Gemini fallback for 12+ Indic languages.
- Claim Extraction: Sentence segmentation + spaCy/Gemini-backed factual claim detection.
- Keyword Extraction: KeyBERT / TF-IDF keyphrases for retrieval query formulation.
- Check-Worthiness Scoring: Routing gate that rejects conversational and non-verifiable inputs.
- Forward Pressure Detection: Identifies viral forwarding signals (e.g., "share this").
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
