"""
Redaction utility for stripping PII (phone numbers, email addresses, long digit runs)
from log records, queries, and error traces.
"""

import hashlib
import re

# Email pattern matching common email addresses
EMAIL_REGEX = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
)

# WhatsApp prefixed numbers e.g. whatsapp:+919876543210
WHATSAPP_PREFIX_REGEX = re.compile(
    r"whatsapp:\+?\d{7,15}",
    re.IGNORECASE,
)

# International phone numbers with + and optional spaces/dashes, 7 to 15 digits
E164_PHONE_REGEX = re.compile(
    r"\+\d{1,4}[-.\s]?\(?\d{1,4}?\)?[-.\s]?\d{1,4}[-.\s]?\d{1,9}"
)

# Indian mobile numbers e.g. 9876543210, optionally prefixed by +91 or 0
INDIAN_PHONE_REGEX = re.compile(
    r"(?:\+91[\-\s]?|0)?[6-9]\d{9}\b"
)

# Generic long digit sequences (10 or more digits, with optional separators)
LONG_DIGIT_REGEX = re.compile(
    r"\b\d[\d\s\-]{8,}\d\b"
)


def hash_identifier(value: str) -> str:
    """
    Hash an identifier (such as phone number) with SHA-256.
    Raw identifiers must never appear in logs or persisted storage.
    """
    if not value:
        return ""
    return hashlib.sha256(value.strip().encode("utf-8")).hexdigest()


def redact(text: str) -> str:
    """
    Redact PII from text including phone numbers, emails, and long digit runs.
    Guarantees no raw contact info is leaked.
    """
    if not text:
        return text

    # Redact emails first
    cleaned = EMAIL_REGEX.sub("[REDACTED_EMAIL]", text)

    # Redact WhatsApp prefixed phone numbers
    cleaned = WHATSAPP_PREFIX_REGEX.sub("[REDACTED_PHONE]", cleaned)

    # Redact E164 international numbers
    cleaned = E164_PHONE_REGEX.sub("[REDACTED_PHONE]", cleaned)

    # Redact Indian mobile numbers
    cleaned = INDIAN_PHONE_REGEX.sub("[REDACTED_PHONE]", cleaned)

    # Redact any remaining 10+ digit runs
    def _clean_digit_run(match: re.Match) -> str:
        digits_only = re.sub(r"\D", "", match.group(0))
        if len(digits_only) >= 10:
            return "[REDACTED_NUMBER]"
        return match.group(0)

    cleaned = LONG_DIGIT_REGEX.sub(_clean_digit_run, cleaned)

    return cleaned
