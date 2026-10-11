"""
main.py — compatibility shim.

The canonical application factory lives in app/main.py.
This file re-exports `app` so that `uvicorn main:app` keeps working.
"""

from app.main import app  # noqa: F401

__all__ = ["app"]

if __name__ == "__main__":
    import uvicorn
    from app.core.config import settings

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.port,
        reload=settings.env == "development",
    )
