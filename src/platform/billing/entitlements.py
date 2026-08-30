# =============================================================================
# Plan entitlements — feature/limit values keyed by plan (source of truth)
# =============================================================================
# plans.features JSON and plans.max_* columns remain for display/backfill.
# Enforcement goes through check_entitlement. NULL int = unlimited.
# =============================================================================
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

BOOL_KEYS = frozenset(
    {"api_access", "custom_models", "embed_widget", "eval_ui", "sso"}
)
INT_KEYS = frozenset(
    {
        "monthly_requests",
        "max_users",
        "max_agents",
        "max_knowledge_bases",
        "max_connectors",
        "max_documents",
    }
)
KNOWN_KEYS = BOOL_KEYS | INT_KEYS

_COUNT_SQL = {
    "max_agents": "SELECT COUNT(*) FROM agents WHERE organization_id = :org",
    "max_knowledge_bases": (
        "SELECT COUNT(*) FROM knowledge_bases WHERE organization_id = :org"
    ),
    "max_connectors": "SELECT COUNT(*) FROM connectors WHERE organization_id = :org",
    "max_users": "SELECT COUNT(*) FROM memberships WHERE organization_id = :org",
}

_COLUMN_FALLBACK_SQL = {
    "monthly_requests": (
        "SELECT p.requests_per_month AS limit_value FROM subscriptions s "
        "JOIN plans p ON s.plan_id = p.id "
        "WHERE s.organization_id = :org "
        "AND s.status IN ('trialing','active') "
        "ORDER BY s.created_at DESC LIMIT 1"
    ),
    "max_users": (
        "SELECT p.max_users_per_organization AS limit_value FROM subscriptions s "
        "JOIN plans p ON s.plan_id = p.id "
        "WHERE s.organization_id = :org "
        "AND s.status IN ('trialing','active') "
        "ORDER BY s.created_at DESC LIMIT 1"
    ),
    "max_agents": (
        "SELECT p.max_agents AS limit_value FROM subscriptions s "
        "JOIN plans p ON s.plan_id = p.id "
        "WHERE s.organization_id = :org "
        "AND s.status IN ('trialing','active') "
        "ORDER BY s.created_at DESC LIMIT 1"
    ),
    "max_knowledge_bases": (
        "SELECT p.max_knowledge_bases AS limit_value FROM subscriptions s "
        "JOIN plans p ON s.plan_id = p.id "
        "WHERE s.organization_id = :org "
        "AND s.status IN ('trialing','active') "
        "ORDER BY s.created_at DESC LIMIT 1"
    ),
    "max_connectors": (
        "SELECT p.max_connectors AS limit_value FROM subscriptions s "
        "JOIN plans p ON s.plan_id = p.id "
        "WHERE s.organization_id = :org "
        "AND s.status IN ('trialing','active') "
        "ORDER BY s.created_at DESC LIMIT 1"
    ),
}

_CACHE_PREFIX = "rag:plan-entitlements:"
_schema_ready = False


class EntitlementDenied(Exception):
    def __init__(
        self,
        key: str,
        limit: int | None,
        current: int | None = None,
    ) -> None:
        super().__init__(f"Entitlement denied for {key}")
        self.key = key
        self.limit = limit
        self.current = current


def _row_value(row: Any) -> bool | int | None:
    if row.value_type == "bool":
        return bool(row.value_bool)
    if row.value_int is None:
        return None
    return int(row.value_int)


def _cache_key(plan_id: UUID) -> str:
    return f"{_CACHE_PREFIX}{plan_id}"


async def _cache_get(plan_id: UUID) -> dict[str, bool | int | None] | None:
    try:
        from src.infrastructure.redis.cache import RedisCache

        raw = await RedisCache().get(_cache_key(plan_id))
        if not raw:
            return None
        import json

        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except Exception:
        return None
    return None


async def _cache_set(plan_id: UUID, values: dict[str, bool | int | None]) -> None:
    try:
        import json

        from src.infrastructure.redis.cache import RedisCache

        await RedisCache().set(_cache_key(plan_id), json.dumps(values), ttl_seconds=300)
    except Exception:
        return


async def invalidate_plan_entitlements_cache(plan_id: UUID) -> None:
    try:
        from src.infrastructure.redis.cache import RedisCache

        await RedisCache().delete(_cache_key(plan_id))
    except Exception:
        logger.warning(
            "Failed to invalidate entitlements cache",
            plan_id=str(plan_id),
        )


_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS plan_entitlements (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        plan_id UUID NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
        key VARCHAR(80) NOT NULL,
        value_type VARCHAR(20) NOT NULL
            CHECK (value_type IN ('bool', 'int', 'bigint')),
        value_bool BOOLEAN,
        value_int BIGINT,
        UNIQUE (plan_id, key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS subscription_events (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        subscription_id UUID NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
        organization_id UUID NOT NULL,
        event_type VARCHAR(40) NOT NULL CHECK (
            event_type IN (
                'created', 'plan_changed', 'paused', 'suspended',
                'canceled', 'usage_reset'
            )
        ),
        from_plan_id UUID,
        to_plan_id UUID,
        actor_user_id UUID,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_plan_entitlements_plan ON plan_entitlements(plan_id)",
    """
    CREATE INDEX IF NOT EXISTS idx_subscription_events_org
        ON subscription_events(organization_id, created_at DESC)
    """,
)

_BACKFILL = (
    """
    INSERT INTO plan_entitlements (plan_id, key, value_type, value_int)
    SELECT id, 'monthly_requests', 'int', requests_per_month FROM plans
    ON CONFLICT (plan_id, key) DO NOTHING
    """,
    """
    INSERT INTO plan_entitlements (plan_id, key, value_type, value_int)
    SELECT id, 'max_users', 'int', max_users_per_organization FROM plans
    ON CONFLICT (plan_id, key) DO NOTHING
    """,
    """
    INSERT INTO plan_entitlements (plan_id, key, value_type, value_int)
    SELECT id, 'max_agents', 'int', max_agents FROM plans
    ON CONFLICT (plan_id, key) DO NOTHING
    """,
    """
    INSERT INTO plan_entitlements (plan_id, key, value_type, value_int)
    SELECT id, 'max_knowledge_bases', 'int', max_knowledge_bases FROM plans
    ON CONFLICT (plan_id, key) DO NOTHING
    """,
    """
    INSERT INTO plan_entitlements (plan_id, key, value_type, value_int)
    SELECT id, 'max_connectors', 'int', max_connectors FROM plans
    ON CONFLICT (plan_id, key) DO NOTHING
    """,
    """
    INSERT INTO plan_entitlements (plan_id, key, value_type, value_bool)
    SELECT id, 'api_access', 'bool', true FROM plans
    ON CONFLICT (plan_id, key) DO NOTHING
    """,
    """
    INSERT INTO plan_entitlements (plan_id, key, value_type, value_bool)
    SELECT id, 'custom_models', 'bool', (name = 'enterprise') FROM plans
    ON CONFLICT (plan_id, key) DO NOTHING
    """,
    """
    INSERT INTO plan_entitlements (plan_id, key, value_type, value_bool)
    SELECT id, 'embed_widget', 'bool', (name IN ('pro', 'enterprise')) FROM plans
    ON CONFLICT (plan_id, key) DO NOTHING
    """,
    """
    INSERT INTO plan_entitlements (plan_id, key, value_type, value_bool)
    SELECT id, 'eval_ui', 'bool', (name IN ('pro', 'enterprise')) FROM plans
    ON CONFLICT (plan_id, key) DO NOTHING
    """,
    """
    INSERT INTO plan_entitlements (plan_id, key, value_type, value_bool)
    SELECT id, 'sso', 'bool', false FROM plans
    ON CONFLICT (plan_id, key) DO NOTHING
    """,
)


async def ensure_entitlements_schema() -> None:
    global _schema_ready
    if _schema_ready:
        return
    session = await get_async_session()
    try:
        for sql in _SCHEMA_STATEMENTS:
            await session.execute(text(sql))
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()

    from src.platform.billing.invoices import ensure_billing_tables

    await ensure_billing_tables()

    session = await get_async_session()
    try:
        for sql in _BACKFILL:
            await session.execute(text(sql))
        await session.commit()
        _schema_ready = True
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def get_plan_entitlements(plan_id: UUID) -> dict[str, bool | int | None]:
    await ensure_entitlements_schema()
    cached = await _cache_get(plan_id)
    if cached is not None:
        return cached
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT key, value_type, value_bool, value_int "
                    "FROM plan_entitlements WHERE plan_id = :pid"
                ),
                {"pid": plan_id},
            )
        ).fetchall()
    finally:
        await session.close()
    values: dict[str, bool | int | None] = {row.key: _row_value(row) for row in rows}
    await _cache_set(plan_id, values)
    return values


async def get_entitlements_for_plans(
    plan_ids: list[UUID],
) -> dict[UUID, dict[str, bool | int | None]]:
    await ensure_entitlements_schema()
    if not plan_ids:
        return {}
    out: dict[UUID, dict[str, bool | int | None]] = {pid: {} for pid in plan_ids}
    session = await get_async_session()
    try:
        stmt = text(
            "SELECT plan_id, key, value_type, value_bool, value_int "
            "FROM plan_entitlements WHERE plan_id IN :ids"
        ).bindparams(bindparam("ids", expanding=True))
        rows = (await session.execute(stmt, {"ids": tuple(plan_ids)})).fetchall()
    finally:
        await session.close()
    for row in rows:
        out.setdefault(row.plan_id, {})[row.key] = _row_value(row)
    return out


async def get_org_entitlements(organization_id: UUID) -> dict[str, object]:
    await ensure_entitlements_schema()
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT s.plan_id, p.name AS plan_name "
                    "FROM subscriptions s JOIN plans p ON p.id = s.plan_id "
                    "WHERE s.organization_id = :org "
                    "AND s.status IN ('trialing','active') "
                    "ORDER BY s.created_at DESC LIMIT 1"
                ),
                {"org": organization_id},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        return {"plan_name": None, "plan_id": None, "entitlements": {}}
    entitlements = await get_plan_entitlements(row.plan_id)
    return {
        "plan_name": row.plan_name,
        "plan_id": str(row.plan_id),
        "entitlements": entitlements,
    }


async def _fallback_column(
    organization_id: UUID, key: str
) -> int | None:
    sql = _COLUMN_FALLBACK_SQL.get(key)
    if sql is None:
        return None
    session = await get_async_session()
    try:
        row = (
            await session.execute(text(sql), {"org": organization_id})
        ).fetchone()
    finally:
        await session.close()
    if row is None or row.limit_value is None:
        return None
    return int(row.limit_value)


async def _active_plan_id(organization_id: UUID) -> UUID | None:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT plan_id FROM subscriptions "
                    "WHERE organization_id = :org "
                    "AND status IN ('trialing','active') "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"org": organization_id},
            )
        ).fetchone()
    finally:
        await session.close()
    return row.plan_id if row else None


async def check_entitlement(
    organization_id: UUID, key: str, *, increment: int = 0
) -> None:
    """Bool false → EntitlementDenied. Int: same semantics as PlanLimitError."""
    if key not in KNOWN_KEYS:
        raise EntitlementDenied(key, None)
    plan_id = await _active_plan_id(organization_id)
    values: dict[str, bool | int | None] = {}
    if plan_id is not None:
        values = await get_plan_entitlements(plan_id)

    if key in BOOL_KEYS:
        allowed = values.get(key)
        if allowed is None:
            allowed = False
        if not allowed:
            raise EntitlementDenied(key, 0, 0)
        return

    limit: int | None
    if key in values:
        raw = values[key]
        limit = None if raw is None else int(raw)
    else:
        limit = await _fallback_column(organization_id, key)

    if limit is None:
        return

    current = 0
    count_sql = _COUNT_SQL.get(key)
    if count_sql is not None:
        session = await get_async_session()
        try:
            current = int(
                (await session.execute(text(count_sql), {"org": organization_id})).scalar()
                or 0
            )
        finally:
            await session.close()
        current = current + increment
        if current >= limit:
            raise EntitlementDenied(key, limit, current)
        return

    # monthly_requests is enforced by quota middleware, not here.
    if increment:
        logger.debug("increment ignored for non-counted entitlement", key=key)
    return


async def upsert_plan_entitlements(
    plan_id: UUID, items: list[dict[str, Any]]
) -> dict[str, bool | int | None]:
    await ensure_entitlements_schema()
    session = await get_async_session()
    try:
        exists = (
            await session.execute(
                text("SELECT id FROM plans WHERE id = :pid"),
                {"pid": plan_id},
            )
        ).fetchone()
        if exists is None:
            raise ValueError("Plan not found")
        for item in items:
            key = item["key"]
            if key not in KNOWN_KEYS:
                raise ValueError(f"Unknown entitlement key: {key}")
            value_type = item["value_type"]
            if key in BOOL_KEYS and value_type != "bool":
                raise ValueError(f"Key {key} requires value_type bool")
            if key in INT_KEYS and value_type not in ("int", "bigint"):
                raise ValueError(f"Key {key} requires value_type int")
            await session.execute(
                text(
                    """
                    INSERT INTO plan_entitlements
                        (plan_id, key, value_type, value_bool, value_int)
                    VALUES (:pid, :key, :vtype, :vbool, :vint)
                    ON CONFLICT (plan_id, key) DO UPDATE SET
                        value_type = EXCLUDED.value_type,
                        value_bool = EXCLUDED.value_bool,
                        value_int = EXCLUDED.value_int
                    """
                ),
                {
                    "pid": plan_id,
                    "key": key,
                    "vtype": value_type,
                    "vbool": item.get("value_bool"),
                    "vint": item.get("value_int"),
                },
            )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
    await invalidate_plan_entitlements_cache(plan_id)
    return await get_plan_entitlements(plan_id)


async def record_subscription_event(
    *,
    subscription_id: UUID,
    organization_id: UUID,
    event_type: str,
    from_plan_id: UUID | None = None,
    to_plan_id: UUID | None = None,
    actor_user_id: UUID | None = None,
) -> None:
    await ensure_entitlements_schema()
    session = await get_async_session()
    try:
        await session.execute(
            text(
                """
                INSERT INTO subscription_events (
                    subscription_id, organization_id, event_type,
                    from_plan_id, to_plan_id, actor_user_id
                ) VALUES (
                    :sid, :oid, :etype, :from_pid, :to_pid, :actor
                )
                """
            ),
            {
                "sid": subscription_id,
                "oid": organization_id,
                "etype": event_type,
                "from_pid": from_plan_id,
                "to_pid": to_plan_id,
                "actor": actor_user_id,
            },
        )
        await session.commit()
    except Exception:
        await session.rollback()
        logger.exception("Failed to write subscription_event", event_type=event_type)
        raise
    finally:
        await session.close()
