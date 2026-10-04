"""
Keyphrase extraction using KeyBERT.
Provides key terms to focus retrieval and evidence ranking.
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

_keybert_model: Any = None


def load_keybert_model() -> Any:
    """
    Load KeyBERT model. Called once during lifespan initialization.
    """
    global _keybert_model
    if _keybert_model is None:
        from keybert import KeyBERT

        logger.info("Loading KeyBERT model...")
        _keybert_model = KeyBERT()
        logger.info("KeyBERT model loaded successfully.")
    return _keybert_model


def get_keybert_model() -> Any:
    """Return the cached KeyBERT model or None if not loaded."""
    return _keybert_model


def set_keybert_model(model: Any) -> None:
    """Set the KeyBERT model manually (for tests or injection)."""
    global _keybert_model
    _keybert_model = model


def extract_keywords(
    text: str,
    model: Optional[Any] = None,
    top_n: int = 3,
) -> List[str]:
    """
    Extract top keyphrases from English text using KeyBERT.
    Returns a list of keyword strings. Never raises exceptions.
    """
    if not text or not text.strip():
        return []

    active_model = model or get_keybert_model()
    if active_model is None:
        logger.warning("KeyBERT model not loaded. Skipping keyword extraction.")
        return []

    try:
        keywords = active_model.extract_keywords(
            text.strip(),
            keyphrase_ngram_range=(1, 3),
            stop_words="english",
            top_n=top_n,
        )
        return [kw[0] for kw in keywords if isinstance(kw, (tuple, list)) and len(kw) > 0]
    except Exception as exc:
        logger.warning("Keyword extraction failed: %s", exc)
        return []
