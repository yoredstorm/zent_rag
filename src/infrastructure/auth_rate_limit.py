# =============================================================================
# Auth attempt rate limiting (Redis)
# =============================================================================
from __future__ import annotations

from src.config import get_settings
from src.infrastructure.cache import _get_redis
from src.infrastructure.logging_config import get_logger

logger = get_logger(__name__)


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
    except Exception as exc:
        logger.warning("auth rate-limit check failed; allowing request", error=str(exc))
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
        logger.warning("auth rate-limit record failed", error=str(exc))


async def clear_auth_failures(*keys: str) -> None:
    try:
        client = await _get_redis()
        for key in keys:
            if not key:
                continue
            await client.delete(f"auth:fail:{key}")
    except Exception as exc:
        logger.warning("auth rate-limit clear failed", error=str(exc))
