"""
Custom domain exceptions for SatyaSetu.
"""


class SatyaSetuError(Exception):
    """Base exception for all SatyaSetu domain errors."""
    pass


class SSRFSecurityError(SatyaSetuError):
    """Raised when an outbound URL points to private or restricted network addresses."""
    pass


class IngestionError(SatyaSetuError):
    """Raised when media extraction or OCR/ASR fails."""
    pass


class LanguageDetectionError(SatyaSetuError):
    """Raised when language detection fails or confidence is too low."""
    pass


class TranslationError(SatyaSetuError):
    """Raised when machine translation fails."""
    pass


class RetrievalError(SatyaSetuError):
    """Raised when evidence search or fact-check API fails."""
    pass


class RetrievalBudgetExceeded(RetrievalError):
    """Raised when the retrieval stage exhausts its allocated time budget."""
    pass


class VerificationError(SatyaSetuError):
    """Raised when verification rule engine fails."""
    pass


class ExplanationError(SatyaSetuError):
    """Raised when response generation or JSON schema validation fails."""
    pass


class RateLimitExceededError(SatyaSetuError):
    """Raised when user exceeds allowed requests per minute."""
    pass
