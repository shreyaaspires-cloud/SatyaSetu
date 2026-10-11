"""
Explanation feature package.

Generates human-readable WhatsApp replies from structured ClaimResult objects:
- `generate_explanation`: Constructs natural-language summaries using Gemini/templates.
- `format_whatsapp_reply`: Applies emoji badges, verdict labels, evidence citations,
  and language-specific formatting to produce the final user-facing message.
"""

from app.features.explanation.generator import generate_explanation
from app.features.explanation.formatter import format_whatsapp_reply

__all__ = ["generate_explanation", "format_whatsapp_reply"]
