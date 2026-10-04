"""
Explanation feature package.
Exports the main public API: generate_explanation and format_whatsapp_reply.
"""

from app.features.explanation.generator import generate_explanation
from app.features.explanation.formatter import format_whatsapp_reply

__all__ = ["generate_explanation", "format_whatsapp_reply"]
