"""
main.py
───────
SatyaSetu Unified Production Entry Point.

This module exposes the modern FastAPI application (`app_main:app`) as the root
application entry point, ensuring seamless compatibility for:
  - `uvicorn main:app --reload`
  - `uvicorn app_main:app --reload`
  - Container runtimes and WSGI/ASGI runners
"""

from __future__ import annotations

import uvicorn
from app_main import app

__all__ = ["app"]


if __name__ == "__main__":
    from app.core.config import settings

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=settings.port,
        reload=settings.is_development,
    )
