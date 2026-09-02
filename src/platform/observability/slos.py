# =============================================================================
# SLIs / SLOs por deployment — latencia (p50/p95), error rate, disponibilidad
# Ventanas: 1h, 24h, 7d. Fuente: usage_events (agent_run).
# =============================================================================
from __future__ import annotations

from uuid import UUID

from sqlalchemy import text

from src.core.config import get_settings
from src.infrastructure.postgres.session import get_async_session

_ERROR_STATUSES = ("error", "failed")


def _window_expr(window: str) -> str:
    return {
        "1h": "NOW() - INTERVAL '1 hour'",
        "24h": "NOW() - INTERVAL '24 hours'",
        "7d": "NOW() - INTERVAL '7 days'",
    }[window]


async def _slos_for(
    organization_id: UUID, deployment_id: UUID | None, window: str
) -> dict:
    settings = get_settings()
    from_expr = _window_expr(window)
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    f"SELECT COUNT(*)::int AS requests, "  # noqa: S608 (window fijo)
                    "COUNT(*) FILTER (WHERE status IN ('error', 'failed'))::int AS errors, "
                    "COALESCE(percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms), 0)::float AS p50, "
                    "COALESCE(percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms), 0)::float AS p95 "
                    "FROM usage_events ue "
                    "WHERE ue.organization_id = :oid AND ue.event_type = 'agent_run' "
                    "AND (CAST(:did AS uuid) IS NULL OR ue.deployment_id = :did) "
                    f"AND ue.created_at > {from_expr}"
                ),
                {"oid": organization_id, "did": deployment_id},
            )
        ).fetchone()
    finally:
        await session.close()

    requests = int(row.requests or 0)
    errors = int(row.errors or 0)
    error_rate = (errors / requests * 100) if requests else 0.0
    availability = (1 - errors / requests) * 100 if requests else 100.0
    p50 = float(row.p50 or 0.0)
    p95 = float(row.p95 or 0.0)

    # Estado del SLO vs thresholds configurados.
    if requests and (
        error_rate > settings.OBS_ERROR_RATE_THRESHOLD_PCT
        or availability < settings.OBS_AVAILABILITY_THRESHOLD_PCT
    ):
        status = "failed"
    elif requests and p95 > settings.OBS_P95_LATENCY_MS:
        status = "degraded"
    elif requests == 0:
        status = "no_traffic"
    else:
        status = "healthy"

    return {
        "window": window,
        "requests": requests,
        "errors": errors,
        "error_rate_pct": round(error_rate, 2),
        "availability_pct": round(availability, 2),
        "p50_ms": round(p50, 1),
        "p95_ms": round(p95, 1),
        "status": status,
    }


async def deployment_slos(
    organization_id: UUID, deployment_id: UUID, windows: tuple[str, ...] = ("1h", "24h", "7d")
) -> dict:
    """SLOs de un deployment; verifica además que pertenezca a la org."""
    session = await get_async_session()
    try:
        dep = (
            await session.execute(
                text(
                    "SELECT d.slug, d.status, a.name AS agent_name "
                    "FROM deployments d LEFT JOIN agents a ON a.id = d.agent_id "
                    "WHERE d.id = :did AND d.organization_id = :oid"
                ),
                {"did": deployment_id, "oid": organization_id},
            )
        ).fetchone()
    finally:
        await session.close()
    if dep is None:
        return None
    return {
        "deployment_id": str(deployment_id),
        "slug": dep.slug,
        "status": dep.status,
        "agent_name": dep.agent_name,
        "windows": [await _slos_for(organization_id, deployment_id, w) for w in windows],
    }


async def org_slos(organization_id: UUID) -> dict:
    """SLOs por deployment de una organización + agregado general."""
    session = await get_async_session()
    try:
        deps = (
            await session.execute(
                text(
                    "SELECT id FROM deployments WHERE organization_id = :oid "
                    "AND status IN ('healthy', 'degraded', 'pending')"
                ),
                {"oid": organization_id},
            )
        ).fetchall()
    finally:
        await session.close()
    deployments = []
    for r in deps:
        d = await deployment_slos(organization_id, r.id)
        if d:
            deployments.append(d)
    aggregated = await _slos_for(organization_id, None, "24h")
    return {
        "organization_id": str(organization_id),
        "deployments": deployments,
        "aggregate_24h": aggregated,
    }
