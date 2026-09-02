# =============================================================================
# FinOps Breakdown — costos por tenant/workspace/agent/deployment/provider/model
# =============================================================================
from __future__ import annotations

from uuid import UUID

from sqlalchemy import text

from src.infrastructure.postgres.session import get_async_session


async def usage_breakdown(
    organization_id: UUID,
    days: int = 30,
) -> dict:
    """Agrega costos/tokens/requests de usage_events agrupado por dimensión."""
    days = max(1, min(days, 365))
    session = await get_async_session()
    try:
        by_agent = (
            await session.execute(
                text(
                    "SELECT COALESCE(a.name, 'sin agente') AS label, "
                    "COUNT(*)::int AS requests, "
                    "COALESCE(SUM(COALESCE(actual_cost, estimated_cost)), 0)::float AS cost, "
                    "COALESCE(SUM(total_tokens), 0)::bigint AS tokens "
                    "FROM usage_events ue LEFT JOIN agents a ON a.id = ue.agent_id "
                    "WHERE ue.organization_id = :oid AND ue.created_at > NOW() - "
                    "MAKE_INTERVAL(days => :days) "
                    "GROUP BY 1 ORDER BY cost DESC LIMIT 20"
                ),
                {"oid": organization_id, "days": days},
            )
        ).fetchall()
        by_workspace = (
            await session.execute(
                text(
                    "SELECT COALESCE(w.name, 'sin workspace') AS label, "
                    "COUNT(*)::int AS requests, "
                    "COALESCE(SUM(COALESCE(actual_cost, estimated_cost)), 0)::float AS cost, "
                    "COALESCE(SUM(total_tokens), 0)::bigint AS tokens "
                    "FROM usage_events ue "
                    "LEFT JOIN agents a ON a.id = ue.agent_id "
                    "LEFT JOIN workspaces w ON w.id = a.workspace_id "
                    "WHERE ue.organization_id = :oid AND ue.created_at > NOW() - "
                    "MAKE_INTERVAL(days => :days) "
                    "GROUP BY 1 ORDER BY cost DESC LIMIT 20"
                ),
                {"oid": organization_id, "days": days},
            )
        ).fetchall()
        by_deployment = (
            await session.execute(
                text(
                    "SELECT COALESCE(d.slug, 'sin deployment') AS label, "
                    "COUNT(*)::int AS requests, "
                    "COALESCE(SUM(COALESCE(actual_cost, estimated_cost)), 0)::float AS cost, "
                    "COALESCE(SUM(total_tokens), 0)::bigint AS tokens "
                    "FROM usage_events ue LEFT JOIN deployments d ON d.id = ue.deployment_id "
                    "WHERE ue.organization_id = :oid AND ue.created_at > NOW() - "
                    "MAKE_INTERVAL(days => :days) "
                    "GROUP BY 1 ORDER BY cost DESC LIMIT 20"
                ),
                {"oid": organization_id, "days": days},
            )
        ).fetchall()
        by_provider = (
            await session.execute(
                text(
                    "SELECT COALESCE(provider, 'unknown') AS label, "
                    "COUNT(*)::int AS requests, "
                    "COALESCE(SUM(COALESCE(actual_cost, estimated_cost)), 0)::float AS cost, "
                    "COALESCE(SUM(total_tokens), 0)::bigint AS tokens "
                    "FROM usage_events ue "
                    "WHERE ue.organization_id = :oid AND ue.created_at > NOW() - "
                    "MAKE_INTERVAL(days => :days) "
                    "GROUP BY 1 ORDER BY cost DESC"
                ),
                {"oid": organization_id, "days": days},
            )
        ).fetchall()
        by_model = (
            await session.execute(
                text(
                    "SELECT COALESCE(model, 'unknown') AS label, "
                    "COUNT(*)::int AS requests, "
                    "COALESCE(SUM(COALESCE(actual_cost, estimated_cost)), 0)::float AS cost, "
                    "COALESCE(SUM(total_tokens), 0)::bigint AS tokens "
                    "FROM usage_events ue "
                    "WHERE ue.organization_id = :oid AND ue.created_at > NOW() - "
                    "MAKE_INTERVAL(days => :days) "
                    "GROUP BY 1 ORDER BY cost DESC LIMIT 20"
                ),
                {"oid": organization_id, "days": days},
            )
        ).fetchall()
    finally:
        await session.close()

    def _rows(rows) -> list[dict]:
        return [
            {
                "label": r.label,
                "requests": int(r.requests),
                "cost": float(r.cost),
                "tokens": int(r.tokens),
            }
            for r in rows
        ]

    return {
        "days": days,
        "by_agent": _rows(by_agent),
        "by_workspace": _rows(by_workspace),
        "by_deployment": _rows(by_deployment),
        "by_provider": _rows(by_provider),
        "by_model": _rows(by_model),
    }


async def economics(
    organization_id: UUID, days: int = 30
) -> dict:
    """Métricas económicas: requests, cost, cost/request, cost/1K requests."""
    days = max(1, min(days, 365))
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT COUNT(*)::int AS requests, "
                    "COALESCE(SUM(total_tokens), 0)::bigint AS tokens, "
                    "COALESCE(SUM(COALESCE(actual_cost, estimated_cost)), 0)::float AS cost "
                    "FROM usage_events ue "
                    "WHERE ue.organization_id = :oid AND ue.created_at > NOW() - "
                    "MAKE_INTERVAL(days => :days)"
                ),
                {"oid": organization_id, "days": days},
            )
        ).fetchone()
    finally:
        await session.close()
    requests = int(row.requests or 0)
    cost = float(row.cost or 0.0)
    tokens = int(row.tokens or 0)
    return {
        "requests": requests,
        "tokens": tokens,
        "total_cost": round(cost, 6),
        "cost_per_request": round(cost / requests, 6) if requests else None,
        "cost_per_1k_requests": round(cost / requests * 1000, 4) if requests else None,
        "tokens_per_request": round(tokens / requests, 1) if requests else None,
    }
