# =============================================================================
# API Key hardening — IP allowlist + rate limit por key
# =============================================================================
from __future__ import annotations

import ipaddress
import time
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)


async def get_key_limits(key_id: UUID) -> tuple[list[str], int | None]:
    """(ip_allowlist, rate_limit_per_minute) de una API key."""
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT ip_allowlist, rate_limit_per_minute "
                    "FROM api_keys WHERE id = :kid"
                ),
                {"kid": key_id},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        return [], None
    allowlist = row.ip_allowlist if isinstance(row.ip_allowlist, list) else []
    return [str(x) for x in allowlist], (
        int(row.rate_limit_per_minute) if row.rate_limit_per_minute else None
    )


def check_key_ip_allowed(allowlist: list[str], client_ip: str) -> bool:
    """¿La IP del cliente está dentro de alguna entrada (IP o CIDR)?"""
    if not client_ip:
        return False
    try:
        ip = ipaddress.ip_address(client_ip)
    except ValueError:
        return False
    for entry in allowlist:
        entry = entry.strip()
        if not entry:
            continue
        try:
            if "/" in entry:
                if ip in ipaddress.ip_network(entry, strict=False):
                    return True
            elif entry == client_ip:
                return True
        except ValueError:
            continue
    return False


async def check_key_rate_limit(key_id: UUID, limit_per_minute: int) -> bool:
    """Ventana de 1 minuto por key (Redis INCR + EXPIRE). Fail-open sin Redis."""
    try:
        from src.infrastructure.redis.cache import _get_redis

        redis = await _get_redis()
        bucket = int(time.time()) // 60
        key = f"rag:key:rl:{key_id.hex}:{bucket}"
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, 90)
        return int(count) <= int(limit_per_minute)
    except Exception as exc:
        logger.warning("Key rate limit check failed, fail-open", error=str(exc))
        return True
