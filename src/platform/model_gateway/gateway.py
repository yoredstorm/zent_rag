# =============================================================================
# Model Gateway — routing por condiciones, A/B (traffic_pct), fallback chain,
# presupuestos por modelo con bloqueo, analytics.
# =============================================================================
from __future__ import annotations

import json
import random
from uuid import UUID

from sqlalchemy import text

from src.core.config import get_settings
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

CONDITION_TYPES = ("default", "cost", "latency", "quality")


# ---------------------------------------------------------------------------
# Routes CRUD
# ---------------------------------------------------------------------------
async def create_route(
    organization_id: UUID,
    name: str,
    condition_type: str,
    condition_value: float | None,
    model: str,
    traffic_pct: int,
    priority: int,
) -> dict:
    if condition_type not in CONDITION_TYPES:
        raise ValueError(f"condition_type inválido: {condition_type}")
    if traffic_pct < 1 or traffic_pct > 100:
        raise ValueError("traffic_pct debe ser 1-100")
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO model_routes (id, organization_id, name, condition_type, "
                    "condition_value, model, traffic_pct, priority) "
                    "VALUES (gen_random_uuid(), :oid, :name, :ctype, :cval, :model, "
                    ":traffic, :priority) RETURNING id, name, model, traffic_pct"
                ),
                {
                    "oid": organization_id,
                    "name": name,
                    "ctype": condition_type,
                    "cval": condition_value,
                    "model": model,
                    "traffic": traffic_pct,
                    "priority": priority,
                },
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    return {"id": str(row.id), "name": row.name, "model": row.model, "traffic_pct": int(row.traffic_pct)}


async def list_routes(organization_id: UUID | None) -> list[dict]:
    session = await get_async_session()
    try:
        sql = (
            "SELECT id, organization_id, name, condition_type, condition_value, model, "
            "traffic_pct, priority, active, created_at FROM model_routes WHERE 1=1 "
        )
        params: dict = {}
        if organization_id is not None:
            sql += " AND organization_id = :oid "
            params["oid"] = organization_id
        sql += " ORDER BY priority, created_at"
        rows = (await session.execute(text(sql), params)).fetchall()
    finally:
        await session.close()
    return [
        {
            "id": str(r.id),
            "organization_id": str(r.organization_id),
            "name": r.name,
            "condition_type": r.condition_type,
            "condition_value": r.condition_value,
            "model": r.model,
            "traffic_pct": int(r.traffic_pct),
            "priority": int(r.priority),
            "active": bool(r.active),
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


async def update_route(organization_id: UUID, route_id: UUID, **fields) -> bool:
    allowed = {"name", "condition_type", "condition_value", "model", "traffic_pct", "priority", "active"}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    session = await get_async_session()
    try:
        sets: list[str] = []
        params: dict = {"rid": route_id, "oid": organization_id}
        for key, value in updates.items():
            sets.append(f"{key} = :{key}")
            params[key] = value
        if not sets:
            return False
        result = await session.execute(
            text(
                f"UPDATE model_routes SET {', '.join(sets)} "  # noqa: S608 (keys whitelisted)
                "WHERE id = :rid AND organization_id = :oid"
            ),
            params,
        )
        await session.commit()
        return result.rowcount > 0
    finally:
        await session.close()


async def delete_route(organization_id: UUID, route_id: UUID) -> bool:
    session = await get_async_session()
    try:
        result = await session.execute(
            text("DELETE FROM model_routes WHERE id = :rid AND organization_id = :oid"),
            {"rid": route_id, "oid": organization_id},
        )
        await session.commit()
        return result.rowcount > 0
    finally:
        await session.close()


# ---------------------------------------------------------------------------
# Presupuestos por modelo
# ---------------------------------------------------------------------------
async def create_budget(organization_id: UUID, model: str, monthly_budget_cents: int) -> dict:
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO model_budgets (id, organization_id, model, monthly_budget_cents) "
                "VALUES (gen_random_uuid(), :oid, :model, :cents) "
                "ON CONFLICT (organization_id, model) DO UPDATE SET "
                "monthly_budget_cents = EXCLUDED.monthly_budget_cents, updated_at = NOW()"
            ),
            {"oid": organization_id, "model": model, "cents": monthly_budget_cents},
        )
        await session.commit()
    finally:
        await session.close()
    return {"status": "saved", "model": model, "monthly_budget_cents": monthly_budget_cents}


async def list_budgets(organization_id: UUID | None) -> list[dict]:
    session = await get_async_session()
    try:
        sql = (
            "SELECT b.id, b.organization_id, b.model, b.monthly_budget_cents, "
            "COALESCE(SUM(COALESCE(ue.actual_cost, ue.estimated_cost)), 0)::float AS spent "
            "FROM model_budgets b "
            "LEFT JOIN usage_events ue ON ue.organization_id = b.organization_id "
            "AND lower(ue.model) = lower(b.model) "
            "AND ue.created_at > DATE_TRUNC('month', NOW()) "
            "WHERE 1=1 "
        )
        params: dict = {}
        if organization_id is not None:
            sql += " AND b.organization_id = :oid "
            params["oid"] = organization_id
        sql += " GROUP BY b.id, b.organization_id, b.model, b.monthly_budget_cents"
        rows = (await session.execute(text(sql), params)).fetchall()
    finally:
        await session.close()
    return [
        {
            "id": str(r.id),
            "organization_id": str(r.organization_id),
            "model": r.model,
            "monthly_budget_cents": int(r.monthly_budget_cents),
            "spent_cents": round(float(r.spent or 0) * 100, 2),
            "blocked": float(r.spent or 0) * 100 >= int(r.monthly_budget_cents),
            "usage_pct": round(float(r.spent or 0) * 100 / int(r.monthly_budget_cents) * 100, 1)
            if int(r.monthly_budget_cents)
            else 0.0,
        }
        for r in rows
    ]


async def delete_budget(organization_id: UUID, budget_id: UUID) -> bool:
    session = await get_async_session()
    try:
        result = await session.execute(
            text("DELETE FROM model_budgets WHERE id = :bid AND organization_id = :oid"),
            {"bid": budget_id, "oid": organization_id},
        )
        await session.commit()
        return result.rowcount > 0
    finally:
        await session.close()


async def _blocked_models(organization_id: UUID) -> set[str]:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT b.model FROM model_budgets b "
                    "WHERE b.organization_id = :oid AND "
                    "(SELECT COALESCE(SUM(COALESCE(ue.actual_cost, ue.estimated_cost)), 0) "
                    "FROM usage_events ue WHERE ue.organization_id = b.organization_id "
                    "AND lower(ue.model) = lower(b.model) "
                    "AND ue.created_at > DATE_TRUNC('month', NOW())) * 100 "
                    ">= b.monthly_budget_cents"
                ),
                {"oid": organization_id},
            )
        ).fetchall()
    finally:
        await session.close()
    return {r.model.lower() for r in rows}


# ---------------------------------------------------------------------------
# Resolución de modelos (A/B por traffic_pct + condiciones + bloqueos)
# ---------------------------------------------------------------------------
def _pick_weighted(models: list[dict]) -> str:
    total = sum(int(m["traffic_pct"]) for m in models)
    roll = random.randint(1, max(total, 1))  # noqa: S311 (A/B de tráfico, no crypto)
    acc = 0
    for m in models:
        acc += int(m["traffic_pct"])
        if roll <= acc:
            return m["model"]
    return models[0]["model"]


async def resolve_models(organization_id: UUID) -> list[str]:
    """Devuelve la cadena de modelos para zent-routed: [primario, fallbacks...].
    Excluye modelos bloqueados por presupuesto y elige primario por traffic_pct."""
    settings = get_settings()
    routes = await list_routes(organization_id)
    active = [r for r in routes if r["active"]]
    if not active:
        return [settings.LITELLM_DEFAULT_MODEL]

    blocked = await _blocked_models(organization_id)
    available = [r for r in active if r["model"].lower() not in blocked]
    if not available:
        return [settings.LITELLM_DEFAULT_MODEL]

    # Primario: pesos (A/B). Fallbacks: resto de modelos únicos (prioridad).
    primary = _pick_weighted(available)
    candidates = [primary]
    for r in sorted(available, key=lambda x: -x["priority"]):
        if r["model"] not in candidates:
            candidates.append(r["model"])
    # Último recurso: default configurado.
    if settings.LITELLM_DEFAULT_MODEL not in candidates:
        candidates.append(settings.LITELLM_DEFAULT_MODEL)
    return candidates


async def gateway_analytics(organization_id: UUID | None) -> dict:
    session = await get_async_session()
    try:
        sql = (
            "SELECT COALESCE(model, 'unknown') AS model, "
            "COUNT(*)::int AS requests, "
            "COUNT(*) FILTER (WHERE status IN ('error','failed'))::int AS errors, "
            "COALESCE(percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms), 0)::float AS p50, "
            "COALESCE(percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms), 0)::float AS p95, "
            "COALESCE(SUM(total_tokens), 0)::bigint AS tokens, "
            "COALESCE(SUM(COALESCE(actual_cost, estimated_cost)), 0)::float AS cost, "
            "COUNT(*) FILTER (WHERE routing IS NOT NULL AND "
            "routing->>'attempts' IS NOT NULL AND "
            "jsonb_array_length(routing->'attempts') > 1)::int AS fallbacks "
            "FROM usage_events WHERE created_at > NOW() - INTERVAL '30 days' "
        )
        params: dict = {}
        if organization_id is not None:
            sql += " AND organization_id = :oid "
            params["oid"] = organization_id
        sql += " GROUP BY 1 ORDER BY cost DESC"
        rows = (await session.execute(text(sql), params)).fetchall()
    finally:
        await session.close()
    return {
        "models": [
            {
                "model": r.model,
                "requests": int(r.requests),
                "error_rate_pct": round(float(r.errors) / max(int(r.requests), 1) * 100, 2),
                "p50_ms": round(float(r.p50), 1),
                "p95_ms": round(float(r.p95), 1),
                "tokens": int(r.tokens),
                "cost": round(float(r.cost), 4),
                "fallbacks": int(r.fallbacks),
            }
            for r in rows
        ]
    }


async def record_routing_metadata(run_id: str, routing: dict) -> None:
    """Registra el routing del run en el usage_events (mejor esfuerzo)."""
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE usage_events SET routing = :routing "
                "WHERE request_id = :rid AND routing IS NULL LIMIT 1"
            ),
            {"routing": json.dumps(routing), "rid": UUID(run_id)},
        )
        await session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Routing metadata write failed", error=str(exc)[:150])
    finally:
        await session.close()
