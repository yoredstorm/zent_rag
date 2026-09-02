# =============================================================================
# Cost Governance & FinOps v2 — costos por tag/unidad de negocio, alertas con
# umbrales adaptativos (baseline semanal), showback/chargeback por equipo y
# forecast de costos por modelo/plan.
# =============================================================================
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

BASELINE_DAYS = 7


# ---------------------------------------------------------------------------
# Tags de costo (unidad de negocio)
# ---------------------------------------------------------------------------
async def list_tags(organization_id: UUID | None = None) -> dict:
    session = await get_async_session()
    try:
        params: dict = {}
        where = ""
        if organization_id:
            where = " WHERE organization_id = :oid"
            params["oid"] = organization_id
        rows = (
            await session.execute(
                text(
                    "SELECT id, organization_id, key, value, created_at "
                    f"FROM cost_tags{where} ORDER BY key, value"
                ),
                params,
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "tags": [
            {
                "id": str(r.id),
                "organization_id": str(r.organization_id),
                "key": r.key,
                "value": r.value,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
    }


async def create_tag(organization_id: UUID, key: str, value: str) -> dict:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO cost_tags (id, organization_id, key, value) "
                    "VALUES (gen_random_uuid(), :oid, :key, :value) "
                    "ON CONFLICT (organization_id, key, value) DO NOTHING "
                    "RETURNING id, key, value"
                ),
                {"oid": organization_id, "key": key[:60], "value": value[:120]},
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    if row is None:
        return {"status": "exists"}
    return {"id": str(row.id), "key": row.key, "value": row.value}


async def delete_tag(tag_id: UUID) -> bool:
    session = await get_async_session()
    try:
        result = await session.execute(
            text("DELETE FROM cost_tags WHERE id = :tid"),
            {"tid": tag_id},
        )
        await session.commit()
        return result.rowcount > 0
    finally:
        await session.close()


# ---------------------------------------------------------------------------
# Costos por tag
# ---------------------------------------------------------------------------
async def costs_by_tag(
    organization_id: UUID | None,
    key: str,
    days: int = 30,
) -> dict:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    session = await get_async_session()
    try:
        params: dict = {"key": key, "since": since}
        where = ""
        if organization_id:
            where = " AND organization_id = :oid"
            params["oid"] = organization_id
        rows = (
            await session.execute(
                text(
                    "SELECT cost_tags->>:key AS tag_value, "
                    "COUNT(*) AS requests, "
                    "SUM(COALESCE(actual_cost, estimated_cost)) AS cost, "
                    "SUM(total_tokens) AS tokens "
                    "FROM usage_events "
                    f"WHERE created_at >= :since AND cost_tags ? :key{where} "
                    "GROUP BY tag_value ORDER BY cost DESC"
                ),
                params,
            )
        ).fetchall()
    finally:
        await session.close()
    breakdown = [
        {
            "tag_value": r.tag_value,
            "requests": int(r.requests),
            "cost": round(float(r.cost), 4),
            "tokens": int(r.tokens),
        }
        for r in rows
    ]
    total = round(sum(item["cost"] for item in breakdown), 4)
    return {
        "key": key,
        "days": days,
        "total": total,
        "breakdown": breakdown,
        "count": len(breakdown),
    }


# ---------------------------------------------------------------------------
# Showback / chargeback por equipo
# ---------------------------------------------------------------------------
async def showback(organization_id: UUID | None = None, days: int = 30) -> dict:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    session = await get_async_session()
    try:
        params: dict = {"since": since}
        where = ""
        if organization_id:
            where = " AND o.id = :oid"
            params["oid"] = organization_id
        rows = (
            await session.execute(
                text(
                    "SELECT COALESCE(o.cost_team, COALESCE(u.cost_tags->>'team', 'sin-equipo')) AS team, "
                    "string_agg(DISTINCT o.id::text, ',') AS org_ids, "
                    "SUM(COALESCE(u.actual_cost, u.estimated_cost)) AS cost, "
                    "COUNT(*) AS requests "
                    "FROM usage_events u JOIN organizations o ON o.id = u.organization_id "
                    f"WHERE u.created_at >= :since{where} "
                    "GROUP BY team ORDER BY cost DESC"
                ),
                params,
            )
        ).fetchall()
    finally:
        await session.close()
    items = [
        {
            "team": r.team,
            "organizations": (r.org_ids or "").split(",") if r.org_ids else [],
            "cost": round(float(r.cost), 4),
            "requests": int(r.requests),
        }
        for r in rows
    ]
    total = sum(item["cost"] for item in items) or 0.0
    for item in items:
        item["share_pct"] = round(item["cost"] / total * 100, 1) if total else 0.0
    return {
        "window_days": days,
        "total_cost": round(total, 4),
        "teams": items,
        "count": len(items),
    }


# ---------------------------------------------------------------------------
# Alertas con umbrales adaptativos (baseline semanal)
# ---------------------------------------------------------------------------
async def _daily_cost_series(organization_id: UUID, days: int = BASELINE_DAYS) -> list[float]:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT date_trunc('day', created_at) AS day, "
                    "SUM(COALESCE(actual_cost, estimated_cost)) AS cost "
                    "FROM usage_events WHERE organization_id = :oid "
                    "AND created_at >= NOW() - make_interval(days => :days) "
                    "GROUP BY day ORDER BY day"
                ),
                {"oid": organization_id, "days": days},
            )
        ).fetchall()
    finally:
        await session.close()
    return [float(r.cost) for r in rows]


async def adaptive_baseline(organization_id: UUID) -> dict:
    """Baseline = costo diario medio de la última semana (excluyendo hoy)."""
    series = await _daily_cost_series(organization_id, BASELINE_DAYS)
    today = series[-1] if series else 0.0
    baseline = (sum(series[:-1]) / max(len(series) - 1, 1)) if len(series) > 1 else 0.0
    return {
        "baseline_daily_cents": round(baseline * 100, 2),
        "today_cents": round(today * 100, 2),
        "days": len(series),
    }


async def list_alert_rules(organization_id: UUID | None = None) -> dict:
    session = await get_async_session()
    try:
        params: dict = {}
        where = ""
        if organization_id:
            where = " WHERE organization_id = :oid"
            params["oid"] = organization_id
        rows = (
            await session.execute(
                text(
                    "SELECT id, organization_id, category, dimension, threshold_pct, "
                    "adaptive, enabled, created_at "
                    f"FROM cost_alert_rules{where} ORDER BY created_at"
                ),
                params,
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "rules": [
            {
                "id": str(r.id),
                "organization_id": str(r.organization_id),
                "category": r.category,
                "dimension": r.dimension,
                "threshold_pct": float(r.threshold_pct),
                "adaptive": bool(r.adaptive),
                "enabled": bool(r.enabled),
            }
            for r in rows
        ]
    }


async def create_alert_rule(
    organization_id: UUID,
    category: str = "total",
    dimension: str | None = None,
    threshold_pct: float = 20.0,
    adaptive: bool = True,
) -> dict:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO cost_alert_rules (id, organization_id, category, "
                    "dimension, threshold_pct, adaptive) "
                    "VALUES (gen_random_uuid(), :oid, :cat, :dim, :pct, :ad) "
                    "RETURNING id, category, dimension, threshold_pct, adaptive"
                ),
                {
                    "oid": organization_id,
                    "cat": category[:40],
                    "dim": dimension[:120] if dimension else None,
                    "pct": threshold_pct,
                    "ad": adaptive,
                },
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    return {
        "id": str(row.id),
        "category": row.category,
        "dimension": row.dimension,
        "threshold_pct": float(row.threshold_pct),
        "adaptive": bool(row.adaptive),
    }


async def delete_alert_rule(rule_id: UUID) -> bool:
    session = await get_async_session()
    try:
        result = await session.execute(
            text("DELETE FROM cost_alert_rules WHERE id = :rid"),
            {"rid": rule_id},
        )
        await session.commit()
        return result.rowcount > 0
    finally:
        await session.close()


async def run_cost_alerts(organization_id: UUID | None = None) -> dict:
    """Evalúa las reglas: alerta si el costo de hoy supera el umbral adaptativo
    (baseline semanal × (1 + pct)) o el pct sobre el máximo de la semana.
    Dedupe 24 h por regla."""
    rules = (await list_alert_rules(organization_id))["rules"]
    fired: list[dict] = []
    for rule in rules:
        if not rule["enabled"]:
            continue
        oid = UUID(rule["organization_id"])
        baseline = await adaptive_baseline(oid)
        today = baseline["today_cents"] / 100
        base = baseline["baseline_daily_cents"] / 100
        if rule["adaptive"]:
            threshold = base * (1 + rule["threshold_pct"] / 100) if base > 0 else 0.0
        else:
            threshold = max(base, today * (1 - rule["threshold_pct"] / 200))
        if threshold > 0 and today > threshold:
            session = await get_async_session()
            try:
                recent = (
                    await session.execute(
                        text(
                            "SELECT 1 FROM cost_alerts WHERE rule_id = :rid "
                            "AND triggered_at > NOW() - interval '24 hours' LIMIT 1"
                        ),
                        {"rid": UUID(rule["id"])},
                    )
                ).fetchone()
                if recent is None:
                    inserted = (
                        await session.execute(
                            text(
                                "INSERT INTO cost_alerts (id, organization_id, rule_id, "
                                "category, dimension, baseline_daily_cents, today_cents, "
                                "threshold_pct) "
                                "VALUES (gen_random_uuid(), :oid, :rid, :cat, :dim, "
                                ":base, :today, :pct) "
                                "RETURNING id"
                            ),
                            {
                                "oid": oid,
                                "rid": UUID(rule["id"]),
                                "cat": rule["category"],
                                "dim": rule["dimension"],
                                "base": baseline["baseline_daily_cents"],
                                "today": baseline["today_cents"],
                                "pct": rule["threshold_pct"],
                            },
                        )
                    ).fetchone()
                    await session.commit()
            finally:
                await session.close()
            if recent is None and inserted:
                fired.append(
                    {
                        "organization_id": str(oid),
                        "rule_id": rule["id"],
                        "category": rule["category"],
                        "dimension": rule["dimension"],
                        "baseline_daily_cents": baseline["baseline_daily_cents"],
                        "today_cents": baseline["today_cents"],
                        "threshold_pct": rule["threshold_pct"],
                    }
                )
                # Ops Center: abrir incidente y ejecutar runbooks (fail-soft).
                try:
                    from src.platform.opscenter.runbooks import open_incident

                    await open_incident(
                        oid,
                        title=(
                            f"Costo alto ({rule['category']}"
                            + (f":{rule['dimension']}" if rule["dimension"] else "")
                            + ")"
                        ),
                        description=(
                            f"$ {baseline['today_cents'] / 100:.2f} hoy vs baseline "
                            f"${baseline['baseline_daily_cents'] / 100:.2f}"
                        ),
                        source="cost_alert",
                        severity="major",
                        auto_runbook=True,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Incident auto-open failed", error=str(exc)[:150])
    return {"checked": len(rules), "fired": fired, "count": len(fired)}


async def list_alerts(organization_id: UUID | None = None, limit: int = 50) -> dict:
    session = await get_async_session()
    try:
        params: dict = {"limit": limit}
        where = ""
        if organization_id:
            where = " WHERE organization_id = :oid"
            params["oid"] = organization_id
        rows = (
            await session.execute(
                text(
                    "SELECT id, organization_id, rule_id, category, dimension, "
                    "baseline_daily_cents, today_cents, threshold_pct, triggered_at "
                    f"FROM cost_alerts{where} ORDER BY triggered_at DESC LIMIT :limit"
                ),
                params,
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "alerts": [
            {
                "id": str(r.id),
                "organization_id": str(r.organization_id),
                "rule_id": str(r.rule_id) if r.rule_id else None,
                "category": r.category,
                "dimension": r.dimension,
                "baseline_daily_cents": round(float(r.baseline_daily_cents), 2),
                "today_cents": round(float(r.today_cents), 2),
                "threshold_pct": float(r.threshold_pct),
                "triggered_at": r.triggered_at.isoformat(),
            }
            for r in rows
        ]
    }


# ---------------------------------------------------------------------------
# Forecast de costos (regresión lineal simple)
# ---------------------------------------------------------------------------
async def forecast(organization_id: UUID | None = None, days: int = 30) -> dict:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    session = await get_async_session()
    try:
        params: dict = {"since": since}
        where = ""
        if organization_id:
            where = " AND organization_id = :oid"
            params["oid"] = organization_id
        rows = (
            await session.execute(
                text(
                    "SELECT date_trunc('day', created_at) AS day, "
                    "SUM(COALESCE(actual_cost, estimated_cost)) AS cost "
                    "FROM usage_events WHERE created_at >= :since" + where + " "
                    "GROUP BY day ORDER BY day"
                ),
                params,
            )
        ).fetchall()
        plan_rows = (
            await session.execute(
                text(
                    "SELECT p.name AS plan, SUM(COALESCE(u.actual_cost, u.estimated_cost)) AS cost "
                    "FROM usage_events u JOIN subscriptions s ON s.organization_id = u.organization_id "
                    "JOIN plans p ON p.id = s.plan_id "
                    "WHERE u.created_at >= :since AND s.status IN ('trialing', 'active')"
                    + (" AND u.organization_id = :oid" if organization_id else "")
                    + " "
                    "GROUP BY p.name ORDER BY cost DESC"
                ),
                params,
            )
        ).fetchall()
        model_rows = (
            await session.execute(
                text(
                    "SELECT model, SUM(COALESCE(actual_cost, estimated_cost)) AS cost "
                    "FROM usage_events WHERE created_at >= :since" + where + " "
                    "GROUP BY model ORDER BY cost DESC LIMIT 10"
                ),
                params,
            )
        ).fetchall()
    finally:
        await session.close()

    series = [(r.day, float(r.cost)) for r in rows]
    n = len(series)
    trend = 0.0
    if n >= 2:
        xs = list(range(n))
        mean_x = sum(xs) / n
        mean_y = sum(c for _, c in series) / n
        denom = sum((x - mean_x) ** 2 for x in xs) or 1.0
        slope = sum((x - mean_x) * (c - mean_y) for x, (_, c) in zip(xs, series)) / denom
        trend = slope
    total = sum(c for _, c in series)
    days_left = max(30 - days, 1) if days >= 30 else 1
    projected_month = total + max(trend, 0.0) * n * (days_left / n)
    return {
        "window_days": days,
        "total_cost": round(total, 4),
        "trend_per_day": round(trend, 4),
        "projected_next_30d": round(max(total + max(trend, 0.0) * 30, 0.0), 4),
        "by_plan": [
            {"plan": r.plan, "cost": round(float(r.cost), 4)} for r in plan_rows
        ],
        "by_model": [
            {"model": r.model, "cost": round(float(r.cost), 4)} for r in model_rows
        ],
    }


# ---------------------------------------------------------------------------
# Estado del org (team/BU)
# ---------------------------------------------------------------------------
async def update_org_units(organization_id: UUID, team: str | None, business_unit: str | None) -> dict:
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE organizations SET cost_team = COALESCE(:team, cost_team), "
                "cost_business_unit = COALESCE(:bu, cost_business_unit) WHERE id = :oid"
            ),
            {"team": team, "bu": business_unit, "oid": organization_id},
        )
        await session.commit()
    finally:
        await session.close()
    return {"status": "updated", "team": team, "business_unit": business_unit}
