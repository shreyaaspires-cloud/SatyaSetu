"""
Root test fixtures and configuration.
"""

from __future__ import annotations

import pytest
import app.main as _app_main


@pytest.fixture(autouse=True)
def reset_ip_rate_limits():
    """Ensure IP rate store and memory cache do not accumulate hits between different tests."""
    from app.core.cache import _memory_cache
    with _app_main._ip_rate_lock:
        _app_main._ip_rate_store.clear()
    _memory_cache.clear()
    yield
    with _app_main._ip_rate_lock:
        _app_main._ip_rate_store.clear()
    _memory_cache.clear()


