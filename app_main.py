"""
app_main.py — compatibility shim.

The canonical application factory now lives in app/main.py.
This file re-exports `app` so that existing references to
`uvicorn app_main:app` keep working during the transition.
"""

from app.main import (  # noqa: F401
    app,
    _ip_rate_store,
    _ip_rate_lock,
    IP_RATE_LIMIT_PER_MINUTE,
    IP_RATE_LIMIT_PER_WINDOW,
)

__all__ = [
    "app",
    "_ip_rate_store",
    "_ip_rate_lock",
    "IP_RATE_LIMIT_PER_MINUTE",
    "IP_RATE_LIMIT_PER_WINDOW",
]
