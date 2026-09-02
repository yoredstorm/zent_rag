# =============================================================================
# Federated Analytics — métricas multi-tenant agregadas con drill-down y export
# =============================================================================
from __future__ import annotations

import csv
import io
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.postgres.session import get_async_session


async def _totals_and_by_org() -> tuple[dict, list[dict]]:
    session = await get_async_session()
    try:
        total = (
            await session.execute(
                text(
                    "SELECT COUNT(*)::int AS requests, "
                    "COUNT(*) FILTER (WHERE status IN ('error','failed'))::int AS errors, "
                    "COALESCE(SUM(total_tokens), 0)::bigint AS tokens, "
                    "COALESCE(SUM(COALESCE(actual_cost, estimated_cost)), 0)::float AS cost "
                    "FROM usage_events WHERE created_at > NOW() - INTERVAL '30 days'"
                )
            )
        ).fetchone()
        rows = (
            await session.execute(
                text(
                    "SELECT ue.organization_id, "
                    "COUNT(*)::int AS requests, "
                    "COUNT(*) FILTER (WHERE ue.status IN ('error','failed'))::int AS errors, "
                    "COALESCE(SUM(ue.total_tokens), 0)::bigint AS tokens, "
                    "COALESCE(SUM(COALESCE(ue.actual_cost, ue.estimated_cost)), 0)::float AS cost, "
                    "MAX(ue.created_at) AS last_activity, "
                    "(SELECT COUNT(*) FROM agents a WHERE a.organization_id = ue.organization_id) AS agents, "
                    "(SELECT COUNT(*) FROM knowledge_bases kb "  # noqa: E501
                    "WHERE kb.organization_id = ue.organization_id) AS knowledge_bases, "
                    "(SELECT COUNT(*) FROM deployments d "  # noqa: E501
                    "WHERE d.organization_id = ue.organization_id "
                    "AND d.status = 'healthy') AS deployments "
                    "FROM usage_events ue "
                    "WHERE ue.created_at > NOW() - INTERVAL '30 days' "
                    "GROUP BY 1 ORDER BY cost DESC LIMIT 50"
                )
            )
        ).fetchall()
        timeline = (
            await session.execute(
                text(
                    "SELECT DATE_TRUNC('day', created_at)::date AS day, "
                    "COUNT(*)::int AS requests, "
                    "COALESCE(SUM(COALESCE(actual_cost, estimated_cost)), 0)::float AS cost "
                    "FROM usage_events "
                    "WHERE created_at > NOW() - INTERVAL '30 days' "
                    "GROUP BY 1 ORDER BY 1"
                )
            )
        ).fetchall()
    finally:
        await session.close()
    totals = {
        "requests": int(total.requests or 0),
        "errors": int(total.errors or 0),
        "error_rate_pct": round(float(total.errors or 0) / max(int(total.requests or 0), 1) * 100, 2),
        "tokens": int(total.tokens or 0),
        "cost": round(float(total.cost or 0), 4),
    }
    by_org = [
        {
            "organization_id": str(r.organization_id),
            "requests": int(r.requests),
            "errors": int(r.errors),
            "error_rate_pct": round(float(r.errors) / max(int(r.requests), 1) * 100, 2),
            "tokens": int(r.tokens),
            "cost": round(float(r.cost), 4),
            "agents": int(r.agents or 0),
            "knowledge_bases": int(r.knowledge_bases or 0),
            "deployments": int(r.deployments or 0),
            "last_activity": r.last_activity.isoformat() if r.last_activity else None,
        }
        for r in rows
    ]
    return totals, by_org


async def federated_analytics() -> dict:
    totals, by_org = await _totals_and_by_org()
    return {
        "period_days": 30,
        "totals": totals,
        "by_organization": by_org,
    }


async def organization_analytics(organization_id: UUID) -> dict:
    """Drill-down: economics + breakdown + SLO agregado de un tenant."""
    from src.platform.finops.breakdown import economics, usage_breakdown
    from src.platform.observability.slos import org_slos

    econ = await economics(organization_id, 30)
    breakdown = await usage_breakdown(organization_id, 30)
    slos = await org_slos(organization_id)
    return {
        "organization_id": str(organization_id),
        "period_days": 30,
        "economics": econ,
        "breakdown": breakdown,
        "aggregate_slo_24h": slos["aggregate_24h"],
        "deployments_slos": slos["deployments"],
    }


async def export_federated_analytics(format: str = "csv") -> dict:
    """CSV (org rows) o JSON passthrough para exportación desde el CC."""
    totals, by_org = await _totals_and_by_org()
    if format == "json":
        return {
            "content_type": "application/json",
            "filename": "zent-federated-analytics.json",
            "payload": {"totals": totals, "by_organization": by_org},
        }
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["organization_id", "requests", "errors", "error_rate_pct", "tokens", "cost",
         "agents", "knowledge_bases", "deployments", "last_activity"]
    )
    for r in by_org:
        writer.writerow(
            [r["organization_id"], r["requests"], r["errors"], r["error_rate_pct"],
             r["tokens"], r["cost"], r["agents"], r["knowledge_bases"],
             r["deployments"], r["last_activity"]]
        )
    return {
        "content_type": "text/csv",
        "filename": "zent-federated-analytics.csv",
        "payload": buffer.getvalue(),
    }


async def export_organization_analytics(organization_id: UUID, format: str = "csv") -> dict:
    org = await organization_analytics(organization_id)
    if format == "json":
        return {
            "content_type": "application/json",
            "filename": f"zent-org-{str(organization_id)[:8]}-analytics.json",
            "payload": org,
        }
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["metric", "value"])
    econ = org["economics"]
    for key in ("requests", "tokens", "total_cost", "cost_per_request", "cost_per_1k_requests"):
        writer.writerow([key, econ.get(key)])
    writer.writerow(["aggregate_slo_status", org["aggregate_slo_24h"]["status"]])
    writer.writerow(["aggregate_slo_availability_pct", org["aggregate_slo_24h"]["availability_pct"]])
    writer.writerow([])
    writer.writerow(["dimension", "label", "requests", "cost"])
    for dim, rows in org["breakdown"].items():
        if not isinstance(rows, list):
            continue
        for r in rows:
            writer.writerow([dim, r["label"], r["requests"], r["cost"]])
    return {
        "content_type": "text/csv",
        "filename": f"zent-org-{str(organization_id)[:8]}-analytics.csv",
        "payload": buffer.getvalue(),
    }
