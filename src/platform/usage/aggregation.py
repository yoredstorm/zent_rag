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
        event_totals = (
            await session.execute(
                text(
                    """
                    SELECT COALESCE(SUM(estimated_cost), 0)::float AS cost,
                           COUNT(*) FILTER (WHERE status <> 'completed')::int AS errors
                    FROM usage_events
                    WHERE organization_id = :oid
                      AND created_at >= NOW() - (:days || ' days')::interval
                    """
                ),
                {"oid": organization_id, "days": str(days)},
            )
        ).fetchone()
        top_users = await session.execute(
            text(
                """
                SELECT user_id::text AS user_id, COUNT(*)::int AS requests
                FROM usage_logs
                WHERE organization_id = :oid
                  AND created_at >= NOW() - (:days || ' days')::interval
                GROUP BY user_id
                ORDER BY requests DESC
                LIMIT 5
                """
            ),
            {"oid": organization_id, "days": str(days)},
        )
        daily_errors = await session.execute(
            text(
                """
                SELECT date_trunc('day', created_at)::date AS day,
                       COUNT(*) FILTER (WHERE status <> 'completed')::int AS errors,
                       COALESCE(SUM(estimated_cost), 0)::float AS estimated_cost
                FROM usage_events
                WHERE organization_id = :oid
                  AND created_at >= NOW() - (:days || ' days')::interval
                GROUP BY 1
                """
            ),
            {"oid": organization_id, "days": str(days)},
        )
        errors_by_day = {
            r.day.isoformat(): {
                "errors": r.errors,
                "estimated_cost": round(r.estimated_cost, 8),
            }
            for r in daily_errors.fetchall()
        }
        try:
            top_queries = await session.execute(
                text(
                    """
                    SELECT LEFT(query_text, 80) AS query_preview,
                           COUNT(*)::int AS count
                    FROM query_audit_log
                    WHERE organization_id = :oid
                      AND created_at >= NOW() - (:days || ' days')::interval
                    GROUP BY LEFT(query_text, 80)
                    ORDER BY count DESC
                    LIMIT 5
                    """
                ),
                {"oid": organization_id, "days": str(days)},
            )
            top_query_rows = [
                {"query_preview": r.query_preview, "count": r.count}
                for r in top_queries.fetchall()
            ]
        except Exception:
            await session.rollback()
            top_query_rows = []
        from datetime import datetime, timedelta, timezone

        from src.platform.finops.report import (
            storage_dollars,
            usage_cost_breakdown,
        )

        period_end = datetime.now(timezone.utc)
        period_start = period_end - timedelta(days=days)
        breakdown = await usage_cost_breakdown(
            start=period_start, end=period_end, organization_id=organization_id
        )
        storage_cost = await storage_dollars(organization_id)

        return {
            "organization_id": str(organization_id),
            "days": days,
            "estimated_costs": {
                "llm": round(breakdown["llm"], 8),
                "embedding": round(breakdown["embedding"], 8),
                "storage": storage_cost,
            },
            "totals": {
                "requests": total_row.requests if total_row else 0,
                "tokens": total_row.tokens if total_row else 0,
                "avg_latency_ms": round(total_row.avg_latency_ms, 2) if total_row else 0,
                "estimated_cost": round(event_totals.cost, 8) if event_totals else 0.0,
                "errors": event_totals.errors if event_totals else 0,
            },
            "daily": [
                {
                    "day": r.day.isoformat(),
                    "requests": r.requests,
                    "tokens": r.tokens,
                    "avg_latency_ms": round(r.avg_latency_ms, 2),
                    "errors": errors_by_day.get(r.day.isoformat(), {}).get("errors", 0),
                    "estimated_cost": errors_by_day.get(r.day.isoformat(), {}).get(
                        "estimated_cost", 0.0
                    ),
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
            "top_users": [
                {"user_id": r.user_id, "requests": r.requests}
                for r in top_users.fetchall()
            ],
            "top_queries": top_query_rows,
        }
    finally:
        await session.close()
