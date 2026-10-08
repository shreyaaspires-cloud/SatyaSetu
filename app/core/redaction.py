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


# ── T10 External Redaction Patterns ───────────────────────────────────────────

EXTERNAL_UPI_REGEX = re.compile(
    r"\b[A-Za-z0-9._\-]{2,}@(upi|okaxis|paytm|ybl|icici|oksbi|okhdfcbank|barodampay|axisbank|apl|postbank|idfcbank|kotak|axl|ibl|airtel)\b",
    re.IGNORECASE,
)

EXTERNAL_PAN_REGEX = re.compile(
    r"\b[A-Za-z]{5}[0-9]{4}[A-Za-z]\b"
)

EXTERNAL_CARD_REGEX = re.compile(
    r"(?<!\w)(?:(?:\d{4}[-\s]){3}\d{4}|\d{16})(?!\w)"
)

EXTERNAL_AADHAAR_REGEX = re.compile(
    r"(?<![+\w:])(?:(?:\d{4}[-\s]){2}\d{4}|\d{12})(?!\w)"
)

EXTERNAL_PHONE_REGEX = re.compile(
    r"(?<!\w)(?:whatsapp:\s*\+?\d{7,15}|(?:\+91[\-\s]?|0)?[6-9]\d{9})(?!\w)",
    re.IGNORECASE,
)

EXTERNAL_LONG_DIGIT_REGEX = re.compile(
    r"(?<!\w)\d{11,}(?!\w)"
)


def redact_for_external(text: str) -> str:
    """
    Redact PII before data is transmitted outside the server to external services
    (Google Fact Check, Brave, Tavily, Wikipedia, Gemini).

    Tokens:
      - Phone numbers: [PHONE]
      - Email addresses: [EMAIL]
      - Aadhaar-style 12-digit numbers: [ID_NUMBER]
      - PAN-style codes: [PAN]
      - Card-like 16-digit runs: [CARD_NUMBER]
      - UPI IDs: [UPI_ID]
      - Long digit strings >10 digits: [NUMBER]

    Meaningful figures (Rs 500, 2 percent, 1 lakh, years) survive untouched.
    """
    if not text:
        return text

    # 1. UPI IDs (must precede email regex to avoid matching as email)
    result = EXTERNAL_UPI_REGEX.sub("[UPI_ID]", text)

    # 2. Email addresses
    result = EMAIL_REGEX.sub("[EMAIL]", result)

    # 3. PAN codes (5 letters + 4 digits + 1 letter)
    result = EXTERNAL_PAN_REGEX.sub("[PAN]", result)

    # 4. Card-like 16-digit runs
    def _card_repl(m: re.Match) -> str:
        digits = re.sub(r"\D", "", m.group(0))
        if len(digits) == 16:
            return "[CARD_NUMBER]"
        return m.group(0)

    result = EXTERNAL_CARD_REGEX.sub(_card_repl, result)

    # 5. Aadhaar-style 12-digit runs
    def _aadhaar_repl(m: re.Match) -> str:
        digits = re.sub(r"\D", "", m.group(0))
        if len(digits) == 12:
            return "[ID_NUMBER]"
        return m.group(0)

    result = EXTERNAL_AADHAAR_REGEX.sub(_aadhaar_repl, result)

    # 6. Phone numbers (10-digit Indian mobile, +91, whatsapp prefix)
    result = EXTERNAL_PHONE_REGEX.sub("[PHONE]", result)

    # 7. Long digit strings (>10 digits) not matching card/aadhaar
    result = EXTERNAL_LONG_DIGIT_REGEX.sub("[NUMBER]", result)

    return result
