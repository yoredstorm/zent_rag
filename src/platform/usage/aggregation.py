# =============================================================================
# Usage — agregación de la organización (requests, tokens, cost, historial)
# =============================================================================
# Fuente compartida por el endpoint REST GET /api/v1/billing/usage y la tool
# MCP get_usage. Agrega usage_logs (dashboard legacy) + usage_events (costos).
# =============================================================================
from __future__ import annotations

from uuid import UUID

from sqlalchemy import text

from src.infrastructure.postgres.session import get_async_session


async def get_organization_usage(
    organization_id: UUID,
    *,
    days: int = 30,
    limit: int = 50,
) -> dict:
    """Agregados de uso de una organización para un rango de días."""
    days = max(1, min(days, 90))
    limit = max(1, min(limit, 200))

    session = await get_async_session()
    try:
        daily = await session.execute(
            text(
                """
                SELECT date_trunc('day', created_at)::date AS day,
                       COUNT(*)::int AS requests,
                       COALESCE(SUM(total_tokens), 0)::int AS tokens,
                       COALESCE(AVG(latency_ms), 0)::float AS avg_latency_ms
                FROM usage_logs
                WHERE organization_id = :oid
                  AND created_at >= NOW() - (:days || ' days')::interval
                GROUP BY 1
                ORDER BY 1 DESC
                """
            ),
            {"oid": organization_id, "days": str(days)},
        )
        recent = await session.execute(
            text(
                """
                SELECT id, total_tokens, latency_ms, model, created_at
                FROM usage_logs
                WHERE organization_id = :oid
                ORDER BY created_at DESC
                LIMIT :lim
                """
            ),
            {"oid": organization_id, "lim": limit},
        )
        totals = await session.execute(
            text(
                """
                SELECT COUNT(*)::int AS requests,
                       COALESCE(SUM(total_tokens), 0)::int AS tokens,
                       COALESCE(AVG(latency_ms), 0)::float AS avg_latency_ms
                FROM usage_logs
                WHERE organization_id = :oid
                  AND created_at >= NOW() - (:days || ' days')::interval
                """
            ),
            {"oid": organization_id, "days": str(days)},
        )
        total_row = totals.fetchone()
        cost_row = (
            await session.execute(
                text(
                    "SELECT COALESCE(SUM(estimated_cost), 0)::float AS cost "
                    "FROM usage_events "
                    "WHERE organization_id = :oid "
                    "AND created_at >= NOW() - (:days || ' days')::interval"
                ),
                {"oid": organization_id, "days": str(days)},
            )
        ).fetchone()
        return {
            "organization_id": str(organization_id),
            "days": days,
            "totals": {
                "requests": total_row.requests if total_row else 0,
                "tokens": total_row.tokens if total_row else 0,
                "avg_latency_ms": round(total_row.avg_latency_ms, 2) if total_row else 0,
                "estimated_cost": round(cost_row.cost, 8) if cost_row else 0.0,
            },
            "daily": [
                {
                    "day": r.day.isoformat(),
                    "requests": r.requests,
                    "tokens": r.tokens,
                    "avg_latency_ms": round(r.avg_latency_ms, 2),
                }
                for r in daily.fetchall()
            ],
            "recent": [
                {
                    "id": r.id,
                    "total_tokens": r.total_tokens,
                    "latency_ms": r.latency_ms,
                    "model": r.model,
                    "created_at": r.created_at.isoformat(),
                }
                for r in recent.fetchall()
            ],
        }
    finally:
        await session.close()
