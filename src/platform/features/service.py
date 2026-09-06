"""Feature flags + Business outcomes + adopción (FASE 03, S23/S24/S13).

Flags por platform/plan/organization/workspace — sin `if tenant === ...`.
Outcomes: métricas de negocio registradas por sistemas cliente (nunca
inventadas). Telemetry: solo conteos agregados, nunca prompts/respuestas.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import text

from src.infrastructure.postgres.session import get_async_session


# ---------------------------------------------------------------------------
# Feature flags
# ---------------------------------------------------------------------------
async def flag_enabled(
    key: str,
    *,
    plan_name: str | None = None,
    organization_id: UUID | None = None,
    workspace_id: UUID | None = None,
) -> bool:
    """Resolución por precedencia: workspace → org → plan → platform."""
    session = await get_async_session()
    try:
        row = None
        if workspace_id is not None:
            row = (
                await session.execute(
                    text(
                        "SELECT enabled FROM feature_flags WHERE key = :key "
                        "AND scope = 'workspace' AND workspace_id = :wid"
                    ),
                    {"key": key, "wid": workspace_id},
                )
            ).fetchone()
        if row is None and organization_id is not None:
            row = (
                await session.execute(
                    text(
                        "SELECT enabled FROM feature_flags WHERE key = :key "
                        "AND scope = 'organization' AND organization_id = :oid"
                    ),
                    {"key": key, "oid": organization_id},
                )
            ).fetchone()
        if row is None and plan_name:
            row = (
                await session.execute(
                    text(
                        "SELECT enabled FROM feature_flags WHERE key = :key "
                        "AND scope = 'plan' AND plan_name = :plan"
                    ),
                    {"key": key, "plan": plan_name},
                )
            ).fetchone()
        if row is None:
            row = (
                await session.execute(
                    text(
                        "SELECT enabled FROM feature_flags WHERE key = :key "
                        "AND scope = 'platform' AND plan_name IS NULL "
                        "AND organization_id IS NULL AND workspace_id IS NULL"
                    ),
                    {"key": key},
                )
            ).fetchone()
    finally:
        await session.close()
    return bool(row and row.enabled)


async def set_flag(
    key: str,
    scope: str,
    enabled: bool,
    *,
    plan_name: str | None = None,
    organization_id: UUID | None = None,
    workspace_id: UUID | None = None,
    created_by: UUID | None = None,
) -> None:
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO feature_flags "
                "(key, scope, plan_name, organization_id, workspace_id, enabled, created_by) "
                "VALUES (:key, :scope, :plan, :oid, :wid, :enabled, :by) "
                "ON CONFLICT (key, scope, plan_name, organization_id, workspace_id) "
                "DO UPDATE SET enabled = EXCLUDED.enabled"
            ),
            {
                "key": key[:80],
                "scope": scope,
                "plan": plan_name,
                "oid": organization_id,
                "wid": workspace_id,
                "enabled": enabled,
                "by": created_by,
            },
        )
        await session.commit()
    finally:
        await session.close()


async def list_flags() -> list[dict]:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT key, scope, plan_name, organization_id, workspace_id, enabled "
                    "FROM feature_flags ORDER BY key, scope, created_at DESC LIMIT 200"
                )
            )
        ).fetchall()
    finally:
        await session.close()
    return [
        {
            "key": r.key,
            "scope": r.scope,
            "plan_name": r.plan_name,
            "organization_id": str(r.organization_id) if r.organization_id else None,
            "workspace_id": str(r.workspace_id) if r.workspace_id else None,
            "enabled": bool(r.enabled),
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Business outcomes (S13): solo eventos reales
# ---------------------------------------------------------------------------
async def record_business_metric(
    organization_id: UUID,
    metric_key: str,
    value: float,
    *,
    agent_id: UUID | None = None,
    period_start: str | None = None,
    period_end: str | None = None,
    source: str | None = None,
) -> None:
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO business_metrics "
                "(id, organization_id, agent_id, metric_key, value, "
                "period_start, period_end, source) "
                "VALUES (gen_random_uuid(), :oid, :aid, :key, :value, "
                "CAST(:ps AS date), CAST(:pe AS date), :source)"
            ),
            {
                "oid": organization_id,
                "aid": agent_id,
                "key": metric_key[:80],
                "value": float(value),
                "ps": period_start,
                "pe": period_end,
                "source": (source or "")[:60],
            },
        )
        await session.commit()
    finally:
        await session.close()


async def business_metrics(
    organization_id: UUID, agent_id: UUID | None = None, days: int = 90
) -> list[dict]:
    session = await get_async_session()
    try:
        params: dict = {"oid": organization_id, "days": days}
        where = "organization_id = :oid AND created_at >= NOW() - (make_interval(days => :days))"
        if agent_id is not None:
            where += " AND agent_id = :aid"
            params["aid"] = agent_id
        rows = (
            await session.execute(
                text(
                    "SELECT agent_id, metric_key, "
                    "ROUND(AVG(value)::numeric, 3) AS value, "
                    "MAX(period_end) AS period_end, MAX(source) AS source "
                    "FROM business_metrics WHERE " + where + " "
                    "GROUP BY agent_id, metric_key ORDER BY metric_key"
                ),
                params,
            )
        ).fetchall()
    finally:
        await session.close()
    return [
        {
            "agent_id": str(r.agent_id) if r.agent_id else None,
            "metric_key": r.metric_key,
            "value": float(r.value or 0),
            "period_end": r.period_end.isoformat() if r.period_end else None,
            "source": r.source,
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Telemetry (S24): adopción agregada — solo conteos
# ---------------------------------------------------------------------------
async def adoption_metrics() -> dict:
    session = await get_async_session()
    try:
        counts = {}
        for label, sql in {
            "organizations": "SELECT COUNT(*) FROM organizations",
            "agents": "SELECT COUNT(*) FROM agents",
            "active_agents": "SELECT COUNT(*) FROM agents WHERE is_active = true",
            "knowledge_bases": "SELECT COUNT(*) FROM knowledge_bases",
            "sources": "SELECT COUNT(*) FROM sources",
            "deployments": "SELECT COUNT(*) FROM deployments WHERE status = 'healthy'",
            "eval_runs": "SELECT COUNT(*) FROM eval_runs WHERE status = 'completed'",
            "mcp_calls": "SELECT COUNT(*) FROM usage_events WHERE event_type = 'mcp_tool'",
            "api_keys": "SELECT COUNT(*) FROM api_keys WHERE is_active = true",
            "requests_30d": "SELECT COUNT(*) FROM usage_events WHERE created_at >= NOW() - interval '30 days'",
        }.items():
            counts[label] = int((await session.execute(text(sql))).scalar() or 0)
        per_org = (
            await session.execute(
                text(
                    "SELECT organization_id, COUNT(*)::int AS agents FROM agents "
                    "GROUP BY organization_id ORDER BY agents DESC LIMIT 10"
                )
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "totals": counts,
        "top_orgs_by_agents": [
            {"organization_id": str(r.organization_id), "agents": int(r.agents)}
            for r in per_org
        ],
    }
