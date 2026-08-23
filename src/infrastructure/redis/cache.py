# =============================================================================
# Redis Cache Adapter — Caché de embeddings y respuestas frecuentes
# =============================================================================
# Reduce latencia y costes de LLM cacheando resultados de consultas
# idénticas. TTL configurable. Las claves incluyen organization_id para
# mantener el aislamiento multi-organization.
# =============================================================================
from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable
from typing import Any

import redis.asyncio as aioredis

from src.core.config import get_settings
from src.core.ports import CacheProvider
from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)

# -----------------------------------------------------------------------------
# Conexión Singleton, per-event-loop
# -----------------------------------------------------------------------------
_redis: aioredis.Redis | None = None
_redis_loop: asyncio.AbstractEventLoop | None = None


async def _aclose_quietly(client: Any) -> None:
    """Cierra el cliente sin reventar si el event loop ya murió (pytest)."""
    if client is None:
        return
    close = getattr(client, "aclose", None) or getattr(client, "close", None)
    if close is None:
        return
    try:
        result = close()
        if isinstance(result, Awaitable):
            await result
    except RuntimeError:
        pass
    except Exception:
        pass


async def _get_redis() -> aioredis.Redis:
    """Retorna el singleton del cliente Redis asíncrono.

    Re-crea si el event loop cambia o está cerrado (tests con ASGITransport).
    No retiene el cliente si ping() falla: si no, el siguiente test hereda
    un pool atado a un loop muerto → RuntimeError: Event loop is closed.
    """
    global _redis, _redis_loop
    loop = asyncio.get_running_loop()
    stale = (
        _redis is None
        or _redis_loop is None
        or _redis_loop.is_closed()
        or _redis_loop is not loop
    )
    if stale:
        await _aclose_quietly(_redis)
        _redis = None
        _redis_loop = None
        settings = get_settings()
        client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            max_connections=20,
            socket_timeout=5.0,
            socket_connect_timeout=5.0,
            retry_on_timeout=True,
        )
        try:
            await client.ping()
        except Exception:
            await _aclose_quietly(client)
            raise
        _redis = client
        _redis_loop = loop
        logger.info("Redis connection established")
    return _redis


async def close_redis_connection() -> None:
    """Cierra la conexión con Redis."""
    global _redis, _redis_loop
    await _aclose_quietly(_redis)
    _redis = None
    _redis_loop = None


class RedisCache(CacheProvider):
    """Implementación de CacheProvider usando Redis."""

    @staticmethod
    def _build_key(prefix: str, *parts: str) -> str:
        """Construye una clave de caché con organization_id embebido."""
        raw = ":".join(parts)
        return f"rag:{prefix}:{raw}"

    @staticmethod
    def _hash_query(organization_id: str, query: str, model: str, role: str = "") -> str:
        """Genera un hash determinista para la query (caché de respuestas).

        Incluye el rol: una respuesta admin (agregados, chunks no públicos)
        no debe servirse a un customer y viceversa.
        """
        raw = f"{organization_id}:{query}:{model}:{role}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    async def get(self, key: str) -> str | None:
        client = await _get_redis()
        try:
            return await client.get(key)
        except Exception as exc:
            logger.warning("Redis GET failed", key=key, error=str(exc))
            return None

    async def set(self, key: str, value: str, ttl_seconds: int = 300) -> None:
        client = await _get_redis()
        try:
            await client.setex(key, ttl_seconds, value)
        except Exception as exc:
            logger.warning("Redis SET failed", key=key, error=str(exc))

    async def delete(self, key: str) -> None:
        client = await _get_redis()
        try:
            await client.delete(key)
        except Exception as exc:
            logger.warning("Redis DELETE failed", key=key, error=str(exc))

    async def exists(self, key: str) -> bool:
        client = await _get_redis()
        try:
            return bool(await client.exists(key))
        except Exception as exc:
            logger.warning("Redis EXISTS failed", key=key, error=str(exc))
            return False

    async def append_to_list(
        self, key: str, value: str, ttl_seconds: int = 3600
    ) -> None:
        client = await _get_redis()
        try:
            async with client.pipeline() as pipe:
                pipe.rpush(key, value)
                pipe.expire(key, ttl_seconds)
                await pipe.execute()
        except Exception as exc:
            logger.warning("Redis RPUSH failed", key=key, error=str(exc))

    async def get_list(self, key: str) -> list[str]:
        client = await _get_redis()
        try:
            items = await client.lrange(key, 0, -1)
            return list(items) if items else []
        except Exception as exc:
            logger.warning("Redis LRANGE failed", key=key, error=str(exc))
            return []

    async def trim_list(self, key: str, max_items: int) -> None:
        client = await _get_redis()
        try:
            await client.ltrim(key, -max_items, -1)
        except Exception as exc:
            logger.warning("Redis LTRIM failed", key=key, error=str(exc))

    async def incr(self, key: str, ttl_seconds: int | None = None, by: int = 1) -> int:
        client = await _get_redis()
        try:
            if by == 1:
                count = await client.incr(key)
            else:
                count = await client.incrby(key, by)
            if ttl_seconds is not None and (count == by or by != 1):
                await client.expire(key, ttl_seconds)
            return int(count)
        except Exception as exc:
            logger.warning("Redis INCR failed", key=key, error=str(exc))
            raise
