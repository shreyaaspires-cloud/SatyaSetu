"""
Unit tests for claim extraction, sentence splitting, forward pressure detection,
and keyphrase extraction.
"""

from unittest.mock import MagicMock

from app.features.nlp.claims import (
    extract_claims,
    has_forward_pressure,
    split_sentences,
)
from app.features.nlp.keywords import extract_keywords


def test_has_forward_pressure():
    assert has_forward_pressure("Forward this message to all your contacts immediately") is True
    assert has_forward_pressure("यह मैसेज फॉरवर्ड करो सबको मिलेगा पैसा") is True
    assert has_forward_pressure("Yeh message sabhi WhatsApp group me share karo") is True
    assert has_forward_pressure("Please send to 10 people to win a lottery") is True

    # Factual claim without pressure
    assert has_forward_pressure("Drinking lemon water cures cancer according to medical reports") is False
    assert has_forward_pressure("WHO declared emergency in several states") is False


def test_split_sentences():
    text = "First claim about water. Second claim about food! Third claim with Hindi purna viram। Fourth claim?"
    sentences = split_sentences(text)
    assert len(sentences) == 4
    assert "First claim about water" in sentences[0]
    assert "Fourth claim" in sentences[3]


def test_extract_claims_filtering_and_capping():
    text = (
        "Please forward to all your friends!\n"
        "Drinking lemon water cures cancer instantly.\n"
        "Petrol prices will drop by 30 rupees tomorrow.\n"
        "Government is giving free laptops to all students.\n"
        "Another extra claim that should exceed the cap."
    )

    claims = extract_claims(text, max_claims=3)
    assert len(claims) == 3
    # The first sentence was pure forward pressure and should be skipped
    assert "Drinking lemon water" in claims[0]
    assert "Petrol prices" in claims[1]
    assert "Government is giving free laptops" in claims[2]


def test_extract_keywords_with_mock():
    mock_kw = MagicMock()
    mock_kw.extract_keywords.return_value = [("lemon water", 0.8), ("cancer", 0.75)]

    keywords = extract_keywords("Drinking lemon water cures cancer", model=mock_kw, top_n=2)
    assert keywords == ["lemon water", "cancer"]

    # Empty text returns empty list without calling model
    assert extract_keywords("", model=mock_kw) == []
