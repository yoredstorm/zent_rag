# =============================================================================
# Usage Metering v2 — contadores en tiempo real (Redis), rate limits por plan
# con burst y throttling dinámico (fair-use).
# =============================================================================
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session
from src.infrastructure.redis.cache import _get_redis

logger = get_logger(__name__)

THROTTLE_SOFT_PCT = 80.0


def _day() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def _minute_bucket() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M")


def _today_key(org: UUID) -> str:
    return f"rag:meter:{org}:{_day()}"


def _model_key(org: UUID) -> str:
    return f"rag:meter:model:{org}:{_day()}"


def _minute_key(org: UUID) -> str:
    return f"rag:meter:min:{org}:{_minute_bucket()}"


async def record(
    organization_id: UUID,
    *,
    tokens: int = 0,
    cost: float = 0.0,
    model: str | None = None,
    status: str = "completed",
) -> None:
    """Incrementa contadores en tiempo real (fail-soft)."""
    try:
        client = await _get_redis()
        pipe = client.pipeline()
        today = _today_key(organization_id)
        pipe.hincrby(today, "requests", 1)
        pipe.hincrby(today, "tokens", int(tokens))
        pipe.hincrbyfloat(today, "cost", round(float(cost), 6))
        if status in ("error", "failed"):
            pipe.hincrby(today, "errors", 1)
        pipe.expire(today, 86400 * 2)
        if model:
            pipe.hincrby(_model_key(organization_id), model, 1)
            pipe.expire(_model_key(organization_id), 86400 * 2)
        mkey = _minute_key(organization_id)
        pipe.incr(mkey)
        pipe.expire(mkey, 600)
        await pipe.execute()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Metering record failed", error=str(exc)[:150])


async def _bucket_counts(org: UUID, minutes: int = 5) -> int:
    client = await _get_redis()
    pipe = client.pipeline()
    base = datetime.now(timezone.utc)
    keys = []
    for i in range(minutes):
        b = base.replace(second=0, microsecond=0)
        from datetime import timedelta

        key = f"rag:meter:min:{org}:{(b - timedelta(minutes=i)).strftime('%Y%m%d%H%M')}"
        keys.append(key)
        pipe.get(key)
    values = await pipe.execute()
    return sum(int(v or 0) for v in values)


async def realtime(organization_id: UUID | None = None) -> dict:
    session = await get_async_session()
    try:
        sql = (
            "SELECT id FROM organizations WHERE status <> 'deleted' "
            "AND (CAST(:oid AS uuid) IS NULL OR id = :oid)"
        )
        orgs = (await session.execute(text(sql), {"oid": organization_id})).fetchall()
    finally:
        await session.close()

    client = await _get_redis()
    out: list[dict] = []
    totals = {"requests": 0, "tokens": 0, "cost": 0.0, "errors": 0, "burst_5min": 0}
    for row in orgs:
        org = row.id
        today = await client.hgetall(_today_key(org))
        models = await client.hgetall(_model_key(org))
        burst = await _bucket_counts(org, 5)
        entry = {
            "organization_id": str(org),
            "requests": int(today.get(b"requests", today.get("requests", 0))),
            "tokens": int(today.get(b"tokens", today.get("tokens", 0))),
            "cost": round(float(today.get(b"cost", today.get("cost", 0.0))), 4),
            "errors": int(today.get(b"errors", today.get("errors", 0))),
            "burst_5min": int(burst),
            "by_model": {k.decode() if isinstance(k, bytes) else k: int(v) for k, v in models.items()},
        }
        out.append(entry)
        totals["requests"] += entry["requests"]
        totals["tokens"] += entry["tokens"]
        totals["cost"] += entry["cost"]
        totals["errors"] += entry["errors"]
        totals["burst_5min"] += entry["burst_5min"]

    return {
        "window": "today + rolling 5min",
        "totals": totals,
        "organizations": out,
    }


async def throttle_factor(organization_id: UUID) -> dict:
    """Fair-use: si el uso del día supera el 80% del budget diario del plan,
    el factor reduce el burst (floor 0.2)."""
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT p.requests_per_month FROM subscriptions s "
                    "JOIN plans p ON p.id = s.plan_id "
                    "WHERE s.organization_id = :oid "
                    "AND s.status IN ('trialing', 'active') "
                    "ORDER BY s.created_at DESC LIMIT 1"
                ),
                {"oid": organization_id},
            )
        ).fetchone()
    finally:
        await session.close()
    monthly = int(row.requests_per_month) if row else 0
    daily_budget = max(monthly / 30, 1)
    client = await _get_redis()
    today = await client.hgetall(_today_key(organization_id))
    used = int(today.get(b"requests", today.get("requests", 0)))
    usage_pct = used / daily_budget * 100 if daily_budget else 0.0
    if usage_pct <= THROTTLE_SOFT_PCT:
        factor = 1.0
        throttled = False
    else:
        over = (usage_pct - THROTTLE_SOFT_PCT) / (100 - THROTTLE_SOFT_PCT)
        factor = round(max(0.2, 1 - over), 2)
        throttled = True
    return {
        "organization_id": str(organization_id),
        "daily_budget": int(daily_budget),
        "used_today": used,
        "usage_pct": round(usage_pct, 1),
        "throttle_factor": factor,
        "throttled": throttled,
        "note": "factor aplicado al burst del rate limit por plan",
    }


# ---------------------------------------------------------------------------
# Rate limits por plan con burst
# ---------------------------------------------------------------------------
async def list_rules() -> list[dict]:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id, plan_name, endpoint_prefix, limit_per_minute, burst, "
                    "enabled, priority FROM rate_limit_rules "
                    "ORDER BY priority DESC, plan_name NULLS LAST"
                )
            )
        ).fetchall()
    finally:
        await session.close()
    return [
        {
            "id": str(r.id),
            "plan_name": r.plan_name,
            "endpoint_prefix": r.endpoint_prefix,
            "limit_per_minute": int(r.limit_per_minute),
            "burst": int(r.burst),
            "enabled": bool(r.enabled),
            "priority": int(r.priority),
        }
        for r in rows
    ]


async def create_rule(
    plan_name: str | None,
    endpoint_prefix: str,
    limit_per_minute: int,
    burst: int,
    priority: int = 0,
) -> dict:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO rate_limit_rules (id, plan_name, endpoint_prefix, "
                    "limit_per_minute, burst, priority) "
                    "VALUES (gen_random_uuid(), :plan, :prefix, :limit, :burst, :prio) "
                    "RETURNING id, plan_name, endpoint_prefix, limit_per_minute, burst"
                ),
                {
                    "plan": plan_name,
                    "prefix": endpoint_prefix,
                    "limit": limit_per_minute,
                    "burst": burst,
                    "prio": priority,
                },
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    return {
        "id": str(row.id),
        "plan_name": row.plan_name,
        "endpoint_prefix": row.endpoint_prefix,
        "limit_per_minute": int(row.limit_per_minute),
        "burst": int(row.burst),
    }


async def update_rule(rule_id: UUID, **fields) -> bool:
    allowed = {"plan_name", "endpoint_prefix", "limit_per_minute", "burst", "enabled", "priority"}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    session = await get_async_session()
    try:
        sets: list[str] = []
        params: dict = {"rid": rule_id}
        for key, value in updates.items():
            sets.append(f"{key} = :{key}")
            params[key] = value
        if not sets:
            return False
        result = await session.execute(
            text(
                f"UPDATE rate_limit_rules SET {', '.join(sets)} WHERE id = :rid"  # noqa: S608 (keys whitelisted)
            ),
            params,
        )
        await session.commit()
        return result.rowcount > 0
    finally:
        await session.close()


async def delete_rule(rule_id: UUID) -> bool:
    session = await get_async_session()
    try:
        result = await session.execute(
            text("DELETE FROM rate_limit_rules WHERE id = :rid"),
            {"rid": rule_id},
        )
        await session.commit()
        return result.rowcount > 0
    finally:
        await session.close()


async def _org_plan_name(organization_id: UUID) -> str | None:
    session = await get_async_session()
    try:
        return (
            await session.execute(
                text(
                    "SELECT p.name FROM subscriptions s JOIN plans p ON p.id = s.plan_id "
                    "WHERE s.organization_id = :oid "
                    "AND s.status IN ('trialing', 'active') "
                    "ORDER BY s.created_at DESC LIMIT 1"
                ),
                {"oid": organization_id},
            )
        ).scalar()
    finally:
        await session.close()


async def effective_limits(organization_id: UUID, path: str) -> dict:
    """Regla aplicable (plan o global) con el prefijo más específico + throttle."""
    rules = await list_rules()
    plan = await _org_plan_name(organization_id)
    candidates = [
        r
        for r in rules
        if r["enabled"] and (r["plan_name"] == plan or r["plan_name"] is None)
        and path.startswith(r["endpoint_prefix"])
    ]
    if not candidates:
        return {"organization_id": str(organization_id), "rule": None, "path": path}
    rule = max(
        candidates,
        key=lambda r: (
            len(r["endpoint_prefix"]),
            r["plan_name"] == plan,
            r["priority"],
        ),
    )
    throttle = await throttle_factor(organization_id)
    factor = throttle["throttle_factor"]
    return {
        "organization_id": str(organization_id),
        "plan_name": plan,
        "path": path,
        "rule": {
            "id": rule["id"],
            "endpoint_prefix": rule["endpoint_prefix"],
            "limit_per_minute": rule["limit_per_minute"],
            "burst": int(rule["burst"] * factor),
            "base_burst": rule["burst"],
        },
        "throttle_factor": factor,
        "throttled": throttle["throttled"],
    }


async def enforce_plan_rate_limit(organization_id: UUID, path: str) -> bool:
    """True si está DENTRO del límite; False → el caller responde 429."""
    effective = await effective_limits(organization_id, path)
    rule = effective.get("rule")
    if rule is None:
        return True
    client = await _get_redis()
    key = f"rag:rl:{organization_id}:{rule['id']}"
    count = await client.incr(key)
    if count == 1:
        await client.expire(key, 60)
    allowed = int(rule["limit_per_minute"]) + int(rule["burst"])
    return count <= allowed
