"""
Input sanitization for extracted and raw text inputs.
Strips non-printable control characters and enforces hard length bounds.

Note on prompt injection defense:
LOOPHOLE-02 fix: Common injection markers are stripped here as a first line of
defense. True prompt injection defense is implemented structurally in the
explanation layer by treating user input as untrusted delimited data blocks
rather than instruction text.
"""


import unicodedata

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
    1. NFC normalizing unicode text (canonical composition).
    2. Removing null bytes and non-printable control characters while
       strictly preserving newlines, tabs, and Indic ligatures (ZWNJ \\u200C, ZWJ \\u200D).
    3. Stripping common prompt-injection markers on a casefolded copy without index drift.
    4. Truncating to max_chars to prevent memory/regex DOS attacks.
    """
    if not text:
        return ""

    # 1. NFC normalization
    normalized = unicodedata.normalize("NFC", text)

    # 2. Preserve printable chars + whitespace + Indic joiners (U+200C ZWNJ, U+200D ZWJ)
    indic_joiners = {"\u200C", "\u200D", "\n", "\t"}
    cleaned = "".join(ch for ch in normalized if ch.isprintable() or ch in indic_joiners)

    # 3. Strip prompt injection markers safely without index drift
    for marker in _INJECTION_MARKERS:
        marker_len = len(marker)
        while True:
            idx = cleaned.upper().find(marker)
            if idx == -1:
                break
            cleaned = cleaned[:idx] + cleaned[idx + marker_len:]

    # 4. Enforce hard length limit
    return cleaned[:max_chars].strip()
