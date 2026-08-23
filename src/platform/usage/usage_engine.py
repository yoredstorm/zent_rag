# =============================================================================
# Usage Engine — eventos de uso idempotentes + contadores Redis
# =============================================================================
# Cada request registra UN UsageEvent. Idempotencia dura:
#   - DB: UNIQUE(request_id, event_type) + ON CONFLICT DO NOTHING
#   - Redis: SADD del request_id en la ventana; solo el primer add cuenta.
# Un retry con el mismo request_id NUNCA duplica consumo.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import text

from src.core.config import get_settings
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS usage_events (
    id BIGSERIAL PRIMARY KEY,
    request_id UUID NOT NULL,
    event_type VARCHAR(30) NOT NULL DEFAULT 'rag_query',
    organization_id UUID NOT NULL,
    user_id UUID,
    project_id UUID,
    agent_id UUID,
    api_key_id UUID,
    model VARCHAR(120),
    provider VARCHAR(60),
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    embedding_tokens INTEGER NOT NULL DEFAULT 0,
    retrieval_count INTEGER NOT NULL DEFAULT 0,
    reranking_count INTEGER NOT NULL DEFAULT 0,
    tool_calls INTEGER NOT NULL DEFAULT 0,
    latency_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
    status VARCHAR(30) NOT NULL DEFAULT 'completed',
    estimated_cost DOUBLE PRECISION NOT NULL DEFAULT 0,
    actual_cost DOUBLE PRECISION,
    currency VARCHAR(3) NOT NULL DEFAULT 'USD',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (request_id, event_type)
)
"""

_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_usage_events_org_time "
    "ON usage_events(organization_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_usage_events_org_agent "
    "ON usage_events(organization_id, agent_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_usage_events_org_key "
    "ON usage_events(organization_id, api_key_id, created_at DESC)",
)


@dataclass(kw_only=True)
class UsageEvent:
    request_id: UUID
    organization_id: UUID
    event_type: str = "rag_query"
    user_id: UUID | None = None
    project_id: UUID | None = None
    agent_id: UUID | None = None
    api_key_id: UUID | None = None
    model: str | None = None
    provider: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    embedding_tokens: int = 0
    retrieval_count: int = 0
    reranking_count: int = 0
    tool_calls: int = 0
    latency_ms: float = 0.0
    status: str = "completed"
    estimated_cost: float = 0.0
    actual_cost: float | None = None
    currency: str = field(default_factory=lambda: get_settings().USAGE_COST_CURRENCY)
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


async def ensure_usage_table() -> None:
    session = await get_async_session()
    try:
        try:
            await session.execute(text(_TABLE_SQL))
            await session.commit()
        except Exception:
            await session.rollback()
        for index_sql in _INDEXES:
            try:
                await session.execute(text(index_sql))
                await session.commit()
            except Exception:
                await session.rollback()
    finally:
        await session.close()


async def record_event(event: UsageEvent) -> bool:
    """Registra un evento. Retorna True si se insertó (nuevo), False si
    ya existía (retry). Fail-silent: nunca rompe el flujo principal."""
    settings = get_settings()
    if not settings.USAGE_ENGINE_ENABLED:
        return False
    try:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "INSERT INTO usage_events "
                    "(request_id, event_type, organization_id, user_id, "
                    "project_id, agent_id, api_key_id, model, provider, "
                    "prompt_tokens, completion_tokens, total_tokens, "
                    "embedding_tokens, retrieval_count, reranking_count, "
                    "tool_calls, latency_ms, status, estimated_cost, "
                    "actual_cost, currency, created_at) "
                    "VALUES (:rid, :etype, :org, :uid, :pid, :aid, :kid, "
                    ":model, :provider, :ptok, :ctok, :ttok, :etok, :rc, "
                    ":rrc, :tc, :lat, :status, :cost, :acost, :cur, :created) "
                    "ON CONFLICT (request_id, event_type) DO NOTHING "
                    "RETURNING id"
                ),
                {
                    "rid": event.request_id,
                    "etype": event.event_type,
                    "org": event.organization_id,
                    "uid": event.user_id,
                    "pid": event.project_id,
                    "aid": event.agent_id,
                    "kid": event.api_key_id,
                    "model": (event.model or "")[:120],
                    "provider": (event.provider or "")[:60],
                    "ptok": event.prompt_tokens,
                    "ctok": event.completion_tokens,
                    "ttok": event.total_tokens,
                    "etok": event.embedding_tokens,
                    "rc": event.retrieval_count,
                    "rrc": event.reranking_count,
                    "tc": event.tool_calls,
                    "lat": round(event.latency_ms, 2),
                    "status": event.status[:30],
                    "cost": round(event.estimated_cost, 8),
                    "acost": (
                        round(event.actual_cost, 8)
                        if event.actual_cost is not None
                        else None
                    ),
                    "cur": event.currency[:3],
                    "created": event.created_at,
                },
            )
            await session.commit()
            return result.fetchone() is not None
        except Exception as exc:
            await session.rollback()
            logger.warning("Usage event write failed", error=str(exc))
            return False
        finally:
            await session.close()
    except Exception:
        return False


# -----------------------------------------------------------------------------
# Redis counters — dedupe por request_id dentro de la ventana
# -----------------------------------------------------------------------------
_WINDOW_TTL_DAILY = 60 * 60 * 26
_WINDOW_TTL_MONTHLY = 60 * 60 * 24 * 33


def _daily_window(created_at: datetime) -> str:
    return f"d{created_at.strftime('%Y-%m-%d')}"


def _monthly_window(created_at: datetime) -> str:
    return f"m{created_at.strftime('%Y-%m')}"


class UsageCounters:
    """Contadores por tenant/ventana con dedupe idempotente por request_id."""

    def __init__(self) -> None:
        self._redis = None
        self._redis_ready = False

    async def _ensure_redis(self):
        if self._redis_ready:
            return self._redis
        self._redis_ready = True
        try:
            from src.infrastructure.redis.cache import _get_redis

            self._redis = await _get_redis()
        except Exception:
            self._redis = None
        return self._redis

    async def _dedupe(self, tenant_id: UUID, window: str, request_id: UUID) -> bool:
        """True si es la PRIMERA vez que se ve este request_id en la ventana."""
        redis = await self._ensure_redis()
        if redis is None:
            return True
        key = f"rag:usage:seen:{tenant_id.hex}:{window}"
        added = await redis.sadd(key, str(request_id))
        if added:
            ttl = (
                _WINDOW_TTL_DAILY
                if window.startswith("d")
                else _WINDOW_TTL_MONTHLY
            )
            await redis.expire(key, ttl)
        return bool(added)

    async def _incr(self, key: str, amount: float, ttl: int) -> None:
        redis = await self._ensure_redis()
        if redis is None:
            return
        pipe = redis.pipeline()
        pipe.incrbyfloat(key, amount)
        pipe.expire(key, ttl)
        try:
            await pipe.execute()
        except Exception:
            pass

    async def _get(self, key: str) -> float:
        redis = await self._ensure_redis()
        if redis is None:
            return 0.0
        try:
            raw = await redis.get(key)
            return float(raw or 0.0)
        except Exception:
            return 0.0

    async def record(
        self,
        tenant_id: UUID,
        request_id: UUID,
        tokens: int,
        cost: float,
        created_at: datetime | None = None,
    ) -> bool:
        """Registra consumo en ventanas diaria/mensual. False si ya contado."""
        created = created_at or datetime.now(timezone.utc)
        if not await self._dedupe(tenant_id, _daily_window(created), request_id):
            return False
        for window, ttl in (
            (_daily_window(created), _WINDOW_TTL_DAILY),
            (_monthly_window(created), _WINDOW_TTL_MONTHLY),
        ):
            base = f"rag:usage:{tenant_id.hex}:{window}"
            await self._incr(f"{base}:tokens", tokens, ttl)
            await self._incr(f"{base}:cost", cost, ttl)
            await self._incr(f"{base}:requests", 1, ttl)
        return True

    async def window_usage(
        self, tenant_id: UUID, created_at: datetime | None = None
    ) -> dict[str, dict[str, float]]:
        """Uso acumulado diario/mensual (claves fijas: daily, monthly)."""
        created = created_at or datetime.now(timezone.utc)
        result: dict[str, dict[str, float]] = {}
        for label, window in (
            ("daily", _daily_window(created)),
            ("monthly", _monthly_window(created)),
        ):
            base = f"rag:usage:{tenant_id.hex}:{window}"
            result[label] = {
                "tokens": await self._get(f"{base}:tokens"),
                "cost": await self._get(f"{base}:cost"),
                "requests": await self._get(f"{base}:requests"),
            }
        return result


def get_usage_counters() -> UsageCounters:
    """Instancia única (composition root)."""
    global _counters
    if _counters is None:
        _counters = UsageCounters()
    return _counters


_counters: UsageCounters | None = None
