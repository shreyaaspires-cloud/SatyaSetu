"""
Input sanitization for extracted and raw text inputs.
Strips non-printable control characters and enforces hard length bounds.

Note on prompt injection defense:
LOOPHOLE-02 fix: Common injection markers are stripped here as a first line of
defense. True prompt injection defense is implemented structurally in the
explanation layer by treating user input as untrusted delimited data blocks
rather than instruction text.
"""


# LOOPHOLE-02: Known prompt injection markers to strip from user input
_INJECTION_MARKERS = [
    "IGNORE PREVIOUS",
    "IGNORE ALL PRIOR",
    "### SYSTEM",
    "#SYSTEM",
    "<|im_start|>",
    "<|im_end|>",
    "[INST]",
    "[/INST]",
    "NEW INSTRUCTIONS",
    "SYSTEM OVERRIDE",
    "DISREGARD PREVIOUS",
    "FORGET PREVIOUS",
]


def sanitize_text(text: str, max_chars: int = 10_000) -> str:
    """
    Sanitize text by:
    1. Removing null bytes and non-printable control characters (preserving \\n and \\t).
    2. Stripping common prompt-injection markers (LOOPHOLE-02).
    3. Truncating to max_chars.
    """
    if not text:
        return ""

    # Remove null bytes and non-printable control characters while preserving \\n and \\t
    cleaned = "".join(ch for ch in text if ch.isprintable() or ch in "\n\t")

    # Strip prompt injection markers (case-insensitive)
    cleaned_upper = cleaned.upper()
    for marker in _INJECTION_MARKERS:
        idx = cleaned_upper.find(marker)
        while idx != -1:
            cleaned = cleaned[:idx] + cleaned[idx + len(marker):]
            cleaned_upper = cleaned.upper()
            idx = cleaned_upper.find(marker)

    # Enforce hard length limit
    return cleaned[:max_chars].strip()
