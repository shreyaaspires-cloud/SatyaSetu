"""
Input type detection based on incoming message metadata and media headers.
"""

from typing import Optional

from app.core.constants import InputType


def detect_input_type(
    body: Optional[str],
    media_url: Optional[str],
    media_content_type: Optional[str],
) -> InputType:
    """
    Determine which extraction pipeline to route the message to.

    Priority order:
      1. media_content_type for image, audio, or pdf attachments
      2. body starting with http/https indicates a URL to scrape
      3. Fallback to plain text from body
    """
    if media_content_type:
        ct = media_content_type.lower().strip()
        if ct in ("image/jpeg", "image/png", "image/jpg", "image/webp"):
            return InputType.SCREENSHOT
        if ct in ("audio/ogg", "audio/ogg; codecs=opus", "audio/mpeg", "audio/mp4"):
            return InputType.VOICE
        if ct == "application/pdf":
            return InputType.PDF

    cleaned_body = (body or "").strip()
    if cleaned_body.lower().startswith(("http://", "https://")):
        return InputType.URL

    return InputType.TEXT
