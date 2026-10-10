"""
Claim result caching layer (BUG-08).

Supports in-memory TTLCache (always) and optional Upstash Redis (when configured).
Cache is keyed by SHA-256 of the normalized claim text.

LOOPHOLE-04: Uses cachetools.TTLCache with a 1000-entry max to prevent unbounded growth.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Optional

from cachetools import TTLCache

from app.core.config import settings

logger = logging.getLogger(__name__)

# LOOPHOLE-04: bounded TTL cache — max 1000 entries, 24h TTL
_memory_cache: TTLCache = TTLCache(maxsize=1000, ttl=86400)


def _make_key(claim_text: str) -> str:
    """SHA-256 keyed by normalized claim text."""
    normalized = claim_text.strip().lower()
    return "claim:" + hashlib.sha256(normalized.encode()).hexdigest()


def cache_get(text: str) -> Optional[dict]:
    """
    Return cached pipeline result for this claim text, or None on miss.
    Checks Redis first (if configured), then in-memory TTL cache.
    """
    key = _make_key(text)
    if settings.cache_backend == "redis" and settings.upstash_redis_url:
        try:
            from upstash_redis import Redis  # type: ignore
            r = Redis(url=settings.upstash_redis_url, token=settings.upstash_redis_token)
            val = r.get(key)
            if val:
                logger.debug("Redis cache HIT for key=%s", key[:20])
                return json.loads(val)
        except Exception as exc:
            logger.warning("Redis cache_get failed (falling through to memory): %s", exc)

    result = _memory_cache.get(key)
    if result is not None:
        logger.debug("Memory cache HIT for key=%s", key[:20])
    return result


def cache_set(text: str, value: dict, ttl: int = 86400) -> None:
    """
    Store a pipeline result for this claim text.
    Writes to Redis (if configured) and in-memory cache.
    """
    key = _make_key(text)
    if settings.cache_backend == "redis" and settings.upstash_redis_url:
        try:
            from upstash_redis import Redis  # type: ignore
            r = Redis(url=settings.upstash_redis_url, token=settings.upstash_redis_token)
            r.setex(key, ttl, json.dumps(value))
            logger.debug("Redis cache_set key=%s ttl=%ds", key[:20], ttl)
            return
        except Exception as exc:
            logger.warning("Redis cache_set failed (falling through to memory): %s", exc)

    _memory_cache[key] = value
    logger.debug("Memory cache_set key=%s", key[:20])


def _make_verdict_key(claim_text: str) -> str:
    """SHA-256 keyed by normalized extracted claim text."""
    normalized = claim_text.strip().lower()
    return "verdict:" + hashlib.sha256(normalized.encode()).hexdigest()


def claim_cache_get(claim_text: str) -> Optional[dict]:
    """Return cached ClaimResult dict for this extracted claim text, or None."""
    key = _make_verdict_key(claim_text)
    if settings.cache_backend == "redis" and settings.upstash_redis_url:
        try:
            from upstash_redis import Redis  # type: ignore
            r = Redis(url=settings.upstash_redis_url, token=settings.upstash_redis_token)
            val = r.get(key)
            if val:
                logger.debug("Redis claim_cache HIT for key=%s", key[:20])
                return json.loads(val)
        except Exception as exc:
            logger.warning("Redis claim_cache_get failed: %s", exc)

    return _memory_cache.get(key)


def claim_cache_set(claim_text: str, value: dict, ttl: int = 86400) -> None:
    """Store a ClaimResult dict for this extracted claim text."""
    key = _make_verdict_key(claim_text)
    if settings.cache_backend == "redis" and settings.upstash_redis_url:
        try:
            from upstash_redis import Redis  # type: ignore
            r = Redis(url=settings.upstash_redis_url, token=settings.upstash_redis_token)
            r.setex(key, ttl, json.dumps(value))
            return
        except Exception as exc:
            logger.warning("Redis claim_cache_set failed: %s", exc)

    _memory_cache[key] = value

