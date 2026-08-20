# =============================================================================
# Auth attempt rate limiting (Redis with in-memory fallback)
# =============================================================================
from __future__ import annotations

import threading
import time

from src.core.config import get_settings
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.redis.cache import _get_redis

logger = get_logger(__name__)

# Process-local fallback when Redis is unavailable (CI / outage).
_mem_lock = threading.Lock()
_mem_counters: dict[str, tuple[int, float]] = {}  # key -> (count, expires_at)


def _mem_get(key: str) -> int | None:
    now = time.monotonic()
    with _mem_lock:
        entry = _mem_counters.get(key)
        if entry is None:
            return None
        count, expires_at = entry
        if now >= expires_at:
            del _mem_counters[key]
            return None
        return count


def _mem_incr(key: str, window_seconds: int) -> int:
    now = time.monotonic()
    with _mem_lock:
        entry = _mem_counters.get(key)
        if entry is None or now >= entry[1]:
            _mem_counters[key] = (1, now + window_seconds)
            return 1
        count = entry[0] + 1
        _mem_counters[key] = (count, entry[1])
        return count


def _mem_clear(key: str) -> None:
    with _mem_lock:
        _mem_counters.pop(key, None)


def reset_memory_rate_limits() -> None:
    """Clear in-memory counters (tests)."""
    with _mem_lock:
        _mem_counters.clear()


async def is_auth_blocked(*keys: str) -> bool:
    """Return True if any key has exceeded max failed attempts."""
    settings = get_settings()
    max_attempts = settings.AUTH_LOGIN_MAX_ATTEMPTS
    try:
        client = await _get_redis()
        for key in keys:
            if not key:
                continue
            raw = await client.get(f"auth:fail:{key}")
            if raw is not None and int(raw) >= max_attempts:
                return True
        return False
    except Exception as exc:
        logger.warning(
            "auth rate-limit Redis unavailable; using in-memory fallback",
            error=str(exc),
        )
        for key in keys:
            if not key:
                continue
            count = _mem_get(key)
            if count is not None and count >= max_attempts:
                return True
        return False


async def record_auth_failure(*keys: str) -> None:
    settings = get_settings()
    window = settings.AUTH_LOGIN_WINDOW_SECONDS
    try:
        client = await _get_redis()
        for key in keys:
            if not key:
                continue
            redis_key = f"auth:fail:{key}"
            count = await client.incr(redis_key)
            if count == 1:
                await client.expire(redis_key, window)
    except Exception as exc:
        logger.warning(
            "auth rate-limit Redis unavailable; recording in-memory",
            error=str(exc),
        )
        for key in keys:
            if not key:
                continue
            _mem_incr(key, window)


async def clear_auth_failures(*keys: str) -> None:
    try:
        client = await _get_redis()
        for key in keys:
            if not key:
                continue
            await client.delete(f"auth:fail:{key}")
    except Exception as exc:
        logger.warning(
            "auth rate-limit Redis unavailable; clearing in-memory",
            error=str(exc),
        )
    for key in keys:
        if not key:
            continue
        _mem_clear(key)
