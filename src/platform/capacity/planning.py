# =============================================================================
# Capacity Planning & Auto-Scaling
# Forecast por tenant vs límites del plan, soft/hard limits, profundidad de
# colas + auto-scaling, simulación de costos.
# =============================================================================
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session
from src.infrastructure.redis.cache import _get_redis

logger = get_logger(__name__)

SOFT_LIMIT_PCT = 80.0
HARD_LIMIT_PCT = 100.0
_SCALE_COOLDOWN_SECONDS = 600


async def _org_usage_and_limits(organization_id: UUID) -> dict | None:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT p.requests_per_month, p.tokens_per_month, "
                    "p.monthly_cost_limit, p.included_storage, "
                    "s.status AS sub_status FROM subscriptions s "
                    "JOIN plans p ON p.id = s.plan_id "
                    "WHERE s.organization_id = :oid "
                    "ORDER BY s.created_at DESC LIMIT 1"
                ),
                {"oid": organization_id},
            )
        ).fetchone()
        if row is None:
            return None
        usage = (
            await session.execute(
                text(
                    "SELECT COUNT(*)::int AS requests, "
                    "COALESCE(SUM(total_tokens), 0)::bigint AS tokens, "
                    "COALESCE(SUM(COALESCE(actual_cost, estimated_cost)), 0)::float AS cost "
                    "FROM usage_events WHERE organization_id = :oid "
                    "AND created_at > DATE_TRUNC('month', NOW())"
                ),
                {"oid": organization_id},
            )
        ).fetchone()
        daily = (
            await session.execute(
                text(
                    "SELECT COUNT(*)::int AS requests "
                    "FROM usage_events WHERE organization_id = :oid "
                    "AND created_at > NOW() - INTERVAL '7 days'"
                ),
                {"oid": organization_id},
            )
        ).scalar()
    finally:
        await session.close()
    return {
        "requests_per_month": int(row.requests_per_month or 0),
        "tokens_per_month": int(row.tokens_per_month or 0),
        "monthly_cost_limit": float(row.monthly_cost_limit or 0),
        "included_storage": int(row.included_storage or 0),
        "sub_status": row.sub_status,
        "used_requests": int(usage.requests or 0),
        "used_tokens": int(usage.tokens or 0),
        "used_cost": float(usage.cost or 0),
        "requests_last_7d": int(daily or 0),
    }


async def capacity_status(organization_id: UUID) -> dict:
    """Uso del mes vs límites + forecast lineal + días hasta el límite."""
    data = await _org_usage_and_limits(organization_id)
    if data is None:
        return {"organization_id": str(organization_id), "status": "no_subscription"}
    req_limit = data["requests_per_month"]
    tok_limit = data["tokens_per_month"]
    cost_limit = data["monthly_cost_limit"]
    used_requests = data["used_requests"]
    used_tokens = data["used_tokens"]
    used_cost = data["used_cost"]

    req_util = used_requests / req_limit * 100 if req_limit else 0.0
    tok_util = used_tokens / tok_limit * 100 if tok_limit else 0.0
    cost_util = used_cost / cost_limit * 100 if cost_limit else 0.0

    # Forecast: tasa diaria de los últimos 7d, proyectada 30 días.
    daily_rate = data["requests_last_7d"] / 7
    forecast_30d = used_requests + daily_rate * 30
    forecast_util = forecast_30d / req_limit * 100 if req_limit else 0.0

    days_until_limit = None
    projected_exceed_date = None
    if req_limit and used_requests < req_limit and daily_rate > 0:
        remaining = req_limit - used_requests
        days_until_limit = max(1, int(remaining / daily_rate))
        projected_exceed_date = (
            datetime.now(timezone.utc).date().isoformat()
        )
    elif req_limit and used_requests >= req_limit:
        days_until_limit = 0

    return {
        "organization_id": str(organization_id),
        "plan_limits": {
            "requests_per_month": req_limit,
            "tokens_per_month": tok_limit,
            "monthly_cost_limit": cost_limit,
            "included_storage": data["included_storage"],
        },
        "usage": {
            "used_requests": used_requests,
            "used_tokens": used_tokens,
            "used_cost": round(used_cost, 4),
        },
        "utilization_pct": {
            "requests": round(req_util, 1),
            "tokens": round(tok_util, 1),
            "cost": round(cost_util, 1),
        },
        "soft_limit_exceeded": req_util >= SOFT_LIMIT_PCT,
        "hard_limit_exceeded": req_util >= HARD_LIMIT_PCT,
        "forecast_30d": {
            "requests": int(forecast_30d),
            "utilization_pct": round(forecast_util, 1),
        },
        "days_until_limit": days_until_limit,
        "projected_exceed_date": projected_exceed_date,
    }


async def simulate_growth(
    organization_id: UUID, growth_pct: float, days: int = 30
) -> dict:
    """Simula el crecimiento y su impacto en costo/límites."""
    status = await capacity_status(organization_id)
    if "plan_limits" not in status:
        return status
    current_cost_per_request = (
        status["usage"]["used_cost"] / status["usage"]["used_requests"]
        if status["usage"]["used_requests"]
        else 0.0
    )
    current_requests = status["usage"]["used_requests"]
    projected_requests = int(current_requests * (1 + growth_pct / 100))
    projected_cost = projected_requests * current_cost_per_request
    req_limit = status["plan_limits"]["requests_per_month"]
    projected_util = projected_requests / req_limit * 100 if req_limit else 0.0
    cost_limit = status["plan_limits"]["monthly_cost_limit"]
    return {
        "organization_id": str(organization_id),
        "growth_pct": growth_pct,
        "days": days,
        "current_requests": current_requests,
        "projected_requests": projected_requests,
        "projected_cost": round(projected_cost, 4),
        "cost_per_request": round(current_cost_per_request, 6),
        "projected_utilization_pct": round(projected_util, 1),
        "exceeds_requests_limit": projected_util >= HARD_LIMIT_PCT,
        "exceeds_cost_limit": bool(cost_limit) and projected_cost >= cost_limit,
    }


async def capacity_summary(limit: int = 30) -> dict:
    """Resumen global: orgs cerca del límite + colas + eventos de escalado."""
    session = await get_async_session()
    try:
        orgs = (
            await session.execute(
                text(
                    "SELECT id FROM organizations WHERE status <> 'deleted' "
                    "ORDER BY created_at LIMIT :limit"
                ),
                {"limit": min(limit, 200)},
            )
        ).fetchall()
    finally:
        await session.close()
    statuses = []
    for r in orgs:
        try:
            s = await capacity_status(r.id)
            if "plan_limits" in s:
                statuses.append(s)
        except Exception as exc:  # noqa: BLE001, S112
            logger.warning("Capacity status failed", org=str(r.id), error=str(exc)[:100])
            continue
    near_limit = [
        s
        for s in statuses
        if s["soft_limit_exceeded"]
        or (s["forecast_30d"]["utilization_pct"] >= SOFT_LIMIT_PCT)
        or (s["days_until_limit"] is not None and s["days_until_limit"] <= 15)
    ]
    queues = await queue_depths()
    events = await list_scaling_events(limit=20)
    return {
        "organizations_scanned": len(statuses),
        "near_limit_count": len(near_limit),
        "near_limit": near_limit[:10],
        "queues": queues,
        "scaling_events": events,
    }


# ---------------------------------------------------------------------------
# Colas + auto-scaling
# ---------------------------------------------------------------------------
async def queue_depths() -> list[dict]:
    """Profundidad de las colas: knowledge (Redis) y ingestion_jobs (SQL)."""
    from src.knowledge.queue import knowledge_queue_key

    out: list[dict] = []
    try:
        client = await _get_redis()
        depth = await client.llen(knowledge_queue_key())
        out.append({"queue": "knowledge", "depth": int(depth or 0), "backend": "redis"})
    except Exception as exc:  # noqa: BLE001
        out.append({"queue": "knowledge", "depth": -1, "backend": "redis", "error": str(exc)[:100]})
    session = await get_async_session()
    try:
        for status in ("pending", "running", "failed"):
            count = int(
                (
                    await session.execute(
                        text(
                            "SELECT COUNT(*) FROM ingestion_jobs WHERE status = :status"
                        ),
                        {"status": status},
                    )
                ).scalar()
                or 0
            )
            out.append({"queue": f"ingestion_{status}", "depth": count, "backend": "sql"})
    finally:
        await session.close()
    return out


async def record_scaling_event(
    queue: str, action: str, depth: int, target: int | None, reason: str
) -> None:
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO scaling_events (id, queue, action, worker_count_target, "
                "depth, reason) VALUES (gen_random_uuid(), :queue, :action, :target, "
                ":depth, :reason)"
            ),
            {
                "queue": queue,
                "action": action,
                "target": target,
                "depth": depth,
                "reason": reason[:300],
            },
        )
        await session.commit()
    finally:
        await session.close()


async def list_scaling_events(limit: int = 50) -> list[dict]:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id, queue, action, worker_count_target, depth, reason, "
                    "created_at FROM scaling_events ORDER BY created_at DESC LIMIT :limit"
                ),
                {"limit": limit},
            )
        ).fetchall()
    finally:
        await session.close()
    return [
        {
            "id": str(r.id),
            "queue": r.queue,
            "action": r.action,
            "worker_count_target": r.worker_count_target,
            "depth": r.depth,
            "reason": r.reason,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


SCALE_UP_DEPTH = 50
SCALE_DOWN_DEPTH = 5
MAX_WORKERS = 8
MIN_WORKERS = 1

_auto_scale_enabled = False
_last_scale: dict[str, datetime] = {}


def set_auto_scale(enabled: bool) -> None:
    global _auto_scale_enabled
    _auto_scale_enabled = enabled


def auto_scale_enabled() -> bool:
    return _auto_scale_enabled


async def _scale_if_needed(queue: str, depth: int, current_workers: int) -> None:
    now = datetime.now(timezone.utc)
    last = _last_scale.get(queue)
    if last and (now - last).total_seconds() < _SCALE_COOLDOWN_SECONDS:
        return
    action = None
    target = current_workers
    if depth >= SCALE_UP_DEPTH and current_workers < MAX_WORKERS:
        action, target = "scale_up", min(current_workers + 2, MAX_WORKERS)
    elif depth <= SCALE_DOWN_DEPTH and current_workers > MIN_WORKERS:
        action, target = "scale_down", max(current_workers - 1, MIN_WORKERS)
    if action:
        _last_scale[queue] = now
        await record_scaling_event(
            queue, action, depth, target, f"depth {depth} (umbral {SCALE_UP_DEPTH})"
        )
        logger.info("Auto-scale", queue=queue, action=action, target=target, depth=depth)


async def capacity_controller_loop() -> None:
    """Evalúa colas y registra eventos de escalado (detección + recomendación)."""
    while True:
        try:
            if not auto_scale_enabled():
                await asyncio.sleep(30)
                continue
            depths = await queue_depths()
            # Worker actual: 1 por defecto (docker compose single worker).
            for item in depths:
                if item["depth"] >= 0:
                    await _scale_if_needed(item["queue"], item["depth"], current_workers=1)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Capacity controller iteration failed", error=str(exc)[:200])
        await asyncio.sleep(60)
