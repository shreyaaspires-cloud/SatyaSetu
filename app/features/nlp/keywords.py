"""
app/features/nlp/keywords.py
────────────────────────────
Keyphrase extraction using KeyBERT.
Provides key terms to focus retrieval and evidence ranking.

Design notes
─────────────
* Singleton pattern: _keybert_model is loaded once at startup via lifespan,
  reducing per-request overhead of loading a ~400 MB sentence-transformer.
* Graceful degradation: all public callsites wrap this in try/except so a
  missing or crashed KeyBERT never breaks the overall pipeline.
* n-gram window (1-3) captures unigrams, bigrams, and trigrams that give
  retrieval engines enough surface area to find relevant documents.
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

# Module-level singleton: avoids repeated model deserialization across requests.
# Injected via set_keybert_model() in tests and during lifespan startup.
_keybert_model: Any = None


def load_keybert_model() -> Any:
    """
    Load KeyBERT model. Called once during lifespan initialization.

    KeyBERT wraps a sentence-transformer (all-MiniLM-L6-v2 by default)
    and is intentionally loaded lazily so the import penalty is paid
    only once and not on cold module import.
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

    Parameters
    ──────────
    text   : Raw input text to mine for keyphrases.
    model  : Override the module singleton (useful in unit tests).
    top_n  : Maximum number of keyphrases to return.

    Implementation notes
    ─────────────────────
    * keyphrase_ngram_range=(1, 3) covers single words through 3-word phrases,
      which is sufficient for claim-centric retrieval queries.
    * stop_words="english" removes noise terms that inflate similarity scores.
    * All exceptions are caught and logged; callers receive an empty list,
      which upstream stages treat as a no-keyword signal (no abort).
    """
    if not text or not text.strip():
        return []

    # Prefer injected model argument; fall back to module singleton.
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
        # KeyBERT returns [(phrase, score), ...]; we discard scores here because
        # downstream ranking uses separate TF-IDF / BM25 signals.
        return [kw[0] for kw in keywords if isinstance(kw, (tuple, list)) and len(kw) > 0]
    except Exception as exc:
        logger.warning("Keyword extraction failed: %s", exc)
        return []
