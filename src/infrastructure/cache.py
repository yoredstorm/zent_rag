# =============================================================================
# Redis Cache Adapter — Caché de embeddings y respuestas frecuentes
# =============================================================================
# Reduce latencia y costes de LLM cacheando resultados de consultas
# idénticas. TTL configurable. Las claves incluyen tenant_id para
# mantener el aislamiento multi-tenant.
# =============================================================================
from __future__ import annotations

import hashlib

import redis.asyncio as aioredis

from src.config import get_settings
from src.domain.ports import CacheProvider
from src.infrastructure.logging_config import get_logger

logger = get_logger(__name__)

# -----------------------------------------------------------------------------
# Conexión Singleton, per-event-loop
# -----------------------------------------------------------------------------
_redis: aioredis.Redis | None = None
_redis_loop_id: int | None = None


async def _get_redis() -> aioredis.Redis:
    """Retorna el singleton del cliente Redis asíncrono.

    Re-crea si el event loop cambia (tests con ASGITransport).
    """
    global _redis, _redis_loop_id
    import asyncio as _asyncio
    current_loop_id = id(_asyncio.get_running_loop())
    if _redis is None or _redis_loop_id != current_loop_id:
        if _redis is not None:
            try:
                await _redis.close()
            except Exception:
                pass
        settings = get_settings()
        _redis = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            max_connections=20,
            socket_timeout=5.0,
            socket_connect_timeout=5.0,
            retry_on_timeout=True,
        )
        await _redis.ping()
        _redis_loop_id = current_loop_id
        logger.info("Redis connection established")
    return _redis


async def close_redis_connection() -> None:
    """Cierra la conexión con Redis."""
    global _redis, _redis_loop_id
    if _redis:
        await _redis.close()
        _redis = None
        _redis_loop_id = None


class RedisCache(CacheProvider):
    """Implementación de CacheProvider usando Redis."""

    @staticmethod
    def _build_key(prefix: str, *parts: str) -> str:
        """Construye una clave de caché con tenant_id embebido."""
        raw = ":".join(parts)
        return f"rag:{prefix}:{raw}"

    @staticmethod
    def _hash_query(tenant_id: str, query: str, model: str) -> str:
        """Genera un hash determinista para la query (caché de respuestas)."""
        raw = f"{tenant_id}:{query}:{model}"
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
