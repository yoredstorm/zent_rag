# =============================================================================
# Redis Cache Adapter — Caché de embeddings y respuestas frecuentes
# =============================================================================
# Reduce latencia y costes de LLM cacheando resultados de consultas
# idénticas. TTL configurable. Las claves incluyen organization_id para
# mantener el aislamiento multi-organization.
#
# Política de fallos (F11):
#   - Lecturas/escrituras de caché son fail-SOFT: sin Redis el run sigue
#     (get → None, listas → [], escrituras no-op).
#   - `incr` es fail-CLOSED: un contador de rate limit nunca falla abierto.
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
    except Exception:  # noqa: BLE001 — cierre best-effort del cliente
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
            max_connections=64,
            socket_timeout=5.0,
            socket_connect_timeout=5.0,
            retry_on_timeout=True,
        )
        try:
            await client.ping()
        except Exception:  # noqa: BLE001 — ping falla: no se retiene el cliente
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


#: Versión de la política semántica/grounding: invalida respuestas cacheadas
#: del contrato viejo («no aparece en el documento»).
_RESPONSE_SEMANTICS_POLICY_VERSION = "grounding-contract-2"
#: Versión del contrato de decisión determinista (DecisionEnvelope + guard).
_RESPONSE_DECISION_VERSION = "decision-envelope-1"


class RedisCache(CacheProvider):
    """Implementación de CacheProvider usando Redis."""

    @staticmethod
    def _build_key(prefix: str, *parts: str) -> str:
        """Construye una clave de caché con organization_id embebido."""
        raw = ":".join(parts)
        return f"rag:{prefix}:{raw}"

    @staticmethod
    def _hash_query(
        organization_id: str,
        query: str,
        model: str,
        role: str = "",
        *,
        knowledge_fingerprint: str = "",
        conversation_id: str = "",
    ) -> str:
        """Genera un hash determinista para la query (caché de respuestas).

        Incluye el rol: una respuesta admin (agregados, chunks no públicos)
        no debe servirse a un customer y viceversa.

        Incluye:
          - scope de conversación (tenant + conversación): una respuesta
            cacheada en una conversación NO se sirve en otra del mismo tenant;
          - versión de la política de grounding/semántica;
          - versión del contrato de decisión (DecisionEnvelope/guard);
          - fingerprint del conocimiento (reglas canónicas + documentos): una
            respuesta creada antes de una modificación de regla NO se reutiliza.

        Sin fingerprint de conocimiento el caller NO debe usar caché (fail-closed
        documentado en el orquestador).
        """
        raw = (
            f"{organization_id}:{conversation_id}:{query}:{model}:{role}:"
            f"{_RESPONSE_SEMANTICS_POLICY_VERSION}:"
            f"{_RESPONSE_DECISION_VERSION}:{knowledge_fingerprint}"
        )
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    async def get(self, key: str) -> str | None:
        try:
            client = await _get_redis()
            return await client.get(key)
        except Exception as exc:  # noqa: BLE001 — política del módulo
            logger.warning("Redis GET failed", key=key, error=str(exc))
            return None

    async def set(self, key: str, value: str, ttl_seconds: int = 300) -> None:
        try:
            client = await _get_redis()
            await client.set(key, value, ex=ttl_seconds)
        except Exception as exc:  # noqa: BLE001 — política del módulo
            logger.warning("Redis SET failed", key=key, error=str(exc))

    async def delete(self, key: str) -> None:
        try:
            client = await _get_redis()
            await client.delete(key)
        except Exception as exc:  # noqa: BLE001 — política del módulo
            logger.warning("Redis DELETE failed", key=key, error=str(exc))

    async def exists(self, key: str) -> bool:
        try:
            client = await _get_redis()
            return bool(await client.exists(key))
        except Exception as exc:  # noqa: BLE001 — política del módulo
            logger.warning("Redis EXISTS failed", key=key, error=str(exc))
            return False

    async def append_to_list(
        self, key: str, value: str, ttl_seconds: int = 3600
    ) -> None:
        try:
            client = await _get_redis()
            async with client.pipeline() as pipe:
                pipe.rpush(key, value)
                pipe.expire(key, ttl_seconds)
                await pipe.execute()
        except Exception as exc:  # noqa: BLE001 — política del módulo
            logger.warning("Redis RPUSH failed", key=key, error=str(exc))

    async def get_list(self, key: str) -> list[str]:
        try:
            client = await _get_redis()
            items = await client.lrange(key, 0, -1)
            return list(items) if items else []
        except Exception as exc:  # noqa: BLE001 — política del módulo
            logger.warning("Redis LRANGE failed", key=key, error=str(exc))
            return []

    async def trim_list(self, key: str, max_items: int) -> None:
        try:
            client = await _get_redis()
            await client.ltrim(key, -max_items, -1)
        except Exception as exc:  # noqa: BLE001 — política del módulo
            logger.warning("Redis LTRIM failed", key=key, error=str(exc))

    async def incr(self, key: str, ttl_seconds: int | None = None, by: int = 1) -> int:
        """INCR es fail-CLOSED: un contador de rate limit no puede fallar abierto."""
        try:
            client = await _get_redis()
            if by == 1:
                count = await client.incr(key)
            else:
                count = await client.incrby(key, by)
            if ttl_seconds is not None and (count == by or by != 1):
                await client.expire(key, ttl_seconds)
            return int(count)
        except Exception as exc:  # noqa: BLE001 — política del módulo
            logger.warning("Redis INCR failed", key=key, error=str(exc))
            raise
