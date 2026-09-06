"""Customer Timeline (FASE 03, S12) — contexto de incidentes para soporte.

Agrega en un solo endpoint: audit, deployments (con rollbacks), feedback,
spikes de error y costo, jobs de ingesta, billing y notificaciones.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.postgres.session import get_async_session


async def _hourly_series(organization_id: UUID, window_hours: int) -> list[dict]:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT date_trunc('hour', created_at) AS bucket, "
                    "COUNT(*) AS requests, "
                    "COUNT(*) FILTER (WHERE status = 'failed') AS errors, "
                    "COALESCE(SUM(estimated_cost), 0) AS cost "
                    "FROM usage_events WHERE organization_id = :oid "
                    "AND created_at >= NOW() - (make_interval(hours => :hours)) "
                    "GROUP BY 1 ORDER BY 1"
                ),
                {"oid": organization_id, "hours": window_hours},
            )
        ).fetchall()
    finally:
        await session.close()
    return [
        {
            "bucket": r.bucket,
            "requests": int(r.requests or 0),
            "errors": int(r.errors or 0),
            "cost": float(r.cost or 0),
        }
        for r in rows
    ]


async def org_timeline(organization_id: UUID, hours: int = 168) -> dict:
    session = await get_async_session()
    try:
        audits = (
            await session.execute(
                text(
                    "SELECT id, action, resource_type, resource_id, created_at "
                    "FROM audit_logs WHERE organization_id = :oid "
                    "AND created_at >= NOW() - (make_interval(hours => :hours)) "
                    "ORDER BY created_at DESC LIMIT 100"
                ),
                {"oid": organization_id, "hours": hours},
            )
        ).fetchall()
        deployments = (
            await session.execute(
                text(
                    "SELECT e.id, e.event, e.metadata, e.created_at, d.slug AS deployment "
                    "FROM deployment_events e "
                    "JOIN deployments d ON d.id = e.deployment_id "
                    "WHERE d.organization_id = :oid "
                    "AND e.created_at >= NOW() - (make_interval(hours => :hours)) "
                    "ORDER BY e.created_at DESC LIMIT 50"
                ),
                {"oid": organization_id, "hours": hours},
            )
        ).fetchall()
        feedback = (
            await session.execute(
                text(
                    "SELECT id, rating, reason, created_at FROM feedback "
                    "WHERE organization_id = :oid "
                    "AND created_at >= NOW() - (make_interval(hours => :hours)) "
                    "ORDER BY created_at DESC LIMIT 50"
                ),
                {"oid": organization_id, "hours": hours},
            )
        ).fetchall()
        jobs = (
            await session.execute(
                text(
                    "SELECT id, job_type, status, error_summary, created_at "
                    "FROM ingestion_jobs WHERE organization_id = :oid "
                    "AND created_at >= NOW() - (make_interval(hours => :hours)) "
                    "ORDER BY created_at DESC LIMIT 50"
                ),
                {"oid": organization_id, "hours": hours},
            )
        ).fetchall()
        invoices = (
            await session.execute(
                text(
                    "SELECT id, status, total_cents, created_at FROM invoices "
                    "WHERE organization_id = :oid "
                    "AND created_at >= NOW() - (make_interval(hours => :hours)) "
                    "ORDER BY created_at DESC LIMIT 20"
                ),
                {"oid": organization_id, "hours": hours},
            )
        ).fetchall()
    finally:
        await session.close()

    items: list[dict] = []

    for r in audits:
        items.append(
            {
                "id": f"audit-{r.id}",
                "at": r.created_at,
                "kind": "audit",
                "title": r.action,
                "detail": f"{r.resource_type or ''} {str(r.resource_id or '')[:12]}",
                "tone": "default",
            }
        )
    for r in deployments:
        tone = {
            "rolled_back": "danger",
            "failed": "danger",
            "healthy": "ok",
            "created": "default",
            "deploying": "default",
        }.get(r.event, "default")
        items.append(
            {
                "id": f"deploy-{r.id}",
                "at": r.created_at,
                "kind": "deployment",
                "title": f"Deployment {r.event} · {r.deployment}",
                "detail": (r.metadata or {}).get("version_number", ""),
                "tone": tone,
            }
        )
    for r in feedback:
        items.append(
            {
                "id": f"feedback-{r.id}",
                "at": r.created_at,
                "kind": "feedback",
                "title": f"Feedback {'negativo' if r.rating == 'down' else 'positivo'}",
                "detail": r.reason or "",
                "tone": "danger" if r.rating == "down" else "ok",
            }
        )
    for r in jobs:
        items.append(
            {
                "id": f"job-{r.id}",
                "at": r.created_at,
                "kind": "job",
                "title": f"{r.job_type or 'job'} {r.status}",
                "detail": str(r.error_summary or "")[:150],
                "tone": "danger" if r.status == "failed" else "ok",
            }
        )
    for r in invoices:
        items.append(
            {
                "id": f"invoice-{r.id}",
                "at": r.created_at,
                "kind": "billing",
                "title": f"Factura {r.status}",
                "detail": f"${float(r.total_cents or 0) / 100:.2f}",
                "tone": "default",
            }
        )

    # Spikes de error y costo (S12: contexto de incidente real).
    series = await _hourly_series(organization_id, hours)
    spikes = _detect_spikes(series)

    items.sort(key=lambda x: x["at"], reverse=True)
    return {
        "items": [
            {
                **{k: v for k, v in item.items() if k != "at"},
                "at": item["at"].isoformat() if isinstance(item["at"], datetime) else item["at"],
            }
            for item in items
        ],
        "spikes": spikes,
    }


def _detect_spikes(series: list[dict]) -> list[dict]:
    """Spikes cuando una hora supera 2x el promedio del período (min 5 eventos)."""
    if not series:
        return []
    avg_errors = sum(s["errors"] for s in series) / len(series)
    avg_cost = sum(s["cost"] for s in series) / len(series)
    spikes: list[dict] = []
    for s in series:
        if s["errors"] > 0 and s["errors"] >= 5 and avg_errors > 0 and s["errors"] >= 2 * avg_errors:
            spikes.append(
                {
                    "kind": "error_spike",
                    "at": s["bucket"].isoformat(),
                    "detail": f"{s['errors']} errores en la hora (promedio {avg_errors:.1f})",
                    "tone": "danger",
                }
            )
        if avg_cost > 0 and s["cost"] >= 2 * avg_cost and s["cost"] >= 1.0:
            spikes.append(
                {
                    "kind": "cost_spike",
                    "at": s["bucket"].isoformat(),
                    "detail": f"${s['cost']:.2f} en la hora (promedio ${avg_cost:.2f})",
                    "tone": "warn",
                }
            )
    return spikes
