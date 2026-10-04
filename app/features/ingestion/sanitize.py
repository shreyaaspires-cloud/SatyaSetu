"""
Input sanitization for extracted and raw text inputs.
Strips non-printable control characters and enforces hard length bounds.

Note on prompt injection defense:
Defect D6 fix removes superficial string replacement markers (e.g. 'IGNORE PREVIOUS').
True prompt injection defense is implemented structurally in the explanation layer
by treating user input as untrusted delimited data blocks rather than instruction text.
"""


def sanitize_text(text: str, max_chars: int = 10_000) -> str:
    """
    Sanitize text by removing null bytes, non-printable control characters
    (preserving newlines and tabs), and truncating to max_chars.
    """
    if not text:
        return ""

    # Remove null bytes and non-printable control characters while preserving \n and \t
    cleaned = "".join(ch for ch in text if ch.isprintable() or ch in "\n\t")

    # Enforce hard length limit
    return cleaned[:max_chars].strip()
