# =============================================================================
# Lazy ingestion trigger rate limiting (Redis with in-memory fallback)
# =============================================================================
# Limita la frecuencia de triggers de lazy ingestion por organization para evitar
# abuso de costo (muchas preguntas raras disparan embeddings y carga de
# Postgres repetidamente). Mismo patrón que auth_rate_limit.py.
#
# El fallo de este módulo nunca debe romper la respuesta RAG: si Redis no
# está disponible, se usa un contador en memoria por proceso; si incluso eso
# falla, se permite el trigger (fail-open).
# =============================================================================
from __future__ import annotations

import threading
import time
from uuid import UUID

from src.core.config import get_settings
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.redis.cache import _get_redis

logger = get_logger(__name__)

_mem_lock = threading.Lock()
_mem_counters: dict[str, tuple[int, float]] = {}  # key -> (count, expires_at)


def _rate_key(organization_id: UUID) -> str:
    return f"rag:lazy_rl:{organization_id.hex}"


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


def _mem_get(key: str) -> int:
    now = time.monotonic()
    with _mem_lock:
        entry = _mem_counters.get(key)
        if entry is None:
            return 0
        count, expires_at = entry
        if now >= expires_at:
            del _mem_counters[key]
            return 0
        return count


def reset_memory_lazy_rate_limits() -> None:
    """Limpia los contadores en memoria (tests)."""
    with _mem_lock:
        _mem_counters.clear()


async def lazy_trigger_allowed(organization_id: UUID) -> bool:
    """True si el organization aún puede disparar lazy ingestion esta hora."""
    settings = get_settings()
    max_triggers = settings.RAG_LAZY_INGEST_MAX_TRIGGERS_PER_HOUR
    try:
        client = await _get_redis()
        raw = await client.get(_rate_key(organization_id))
        if raw is not None and int(raw) >= max_triggers:
            return False
        return True
    except Exception as exc:
        logger.warning(
            "lazy rate-limit Redis unavailable; using in-memory fallback",
            error=str(exc),
        )
        return _mem_get(_rate_key(organization_id)) < max_triggers


async def record_lazy_trigger(organization_id: UUID) -> int:
    """Registra un trigger y devuelve el conteo acumulado de la ventana."""
    settings = get_settings()
    window = 3600
    try:
        client = await _get_redis()
        key = _rate_key(organization_id)
        count = await client.incr(key)
        if count == 1:
            await client.expire(key, window)
        return int(count)
    except Exception as exc:
        logger.warning(
            "lazy rate-limit Redis unavailable; recording in-memory",
            error=str(exc),
        )
        return _mem_incr(_rate_key(organization_id), window)


async def lazy_trigger_limited(organization_id: UUID) -> bool:
    """True si el organization está actualmente sobre el límite (para UI/API)."""
    settings = get_settings()
    max_triggers = settings.RAG_LAZY_INGEST_MAX_TRIGGERS_PER_HOUR
    try:
        client = await _get_redis()
        raw = await client.get(_rate_key(organization_id))
        return raw is not None and int(raw) >= max_triggers
    except Exception:
        return _mem_get(_rate_key(organization_id)) >= max_triggers
