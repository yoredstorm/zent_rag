# =============================================================================
# Incident alerts — high error rate, alta latencia p95, baja disponibilidad,
# worker stalled, deployment unhealthy. Delivery por webhook (ops channel).
# =============================================================================
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import text

from src.core.config import get_settings
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

ALERT_HIGH_ERROR_RATE = "high_error_rate"
ALERT_HIGH_LATENCY = "high_latency_p95"
ALERT_LOW_AVAILABILITY = "low_availability"
ALERT_WORKER_STALLED = "worker_stalled"
ALERT_DEPLOYMENT_UNHEALTHY = "deployment_unhealthy"


async def _get_webhook(organization_id: UUID) -> tuple[str | None, bool]:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT ops_webhook_url, ops_webhook_enabled "
                    "FROM organizations WHERE id = :oid"
                ),
                {"oid": organization_id},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        return None, False
    return row.ops_webhook_url, bool(row.ops_webhook_enabled)


async def _post_webhook(url: str, payload: dict) -> bool:
    """Entrega el payload al webhook; True si 2xx. Fail-soft."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
        return 200 <= resp.status_code < 300
    except Exception as exc:
        logger.warning("Webhook delivery failed", url=url, error=str(exc)[:200])
        return False


async def deliver_webhook(organization_id: UUID, alert: dict) -> str | None:
    """Devuelve 'delivered' | 'failed' | None si no hay webhook configurado."""
    url, enabled = await _get_webhook(organization_id)
    if not url or not enabled:
        return None
    payload = {
        "event": "incident",
        "organization_id": str(organization_id),
        "alert_type": alert["alert_type"],
        "severity": alert["severity"],
        "message": alert["message"],
        "deployment_id": alert.get("deployment_id"),
        "threshold_value": alert.get("threshold_value"),
        "actual_value": alert.get("actual_value"),
        "created_at": alert["created_at"],
    }
    ok = await _post_webhook(url, payload)
    return "delivered" if ok else "failed"


async def _insert_alert(
    organization_id: UUID,
    alert_type: str,
    severity: str,
    message: str,
    threshold_value: float | None,
    actual_value: float | None,
    deployment_id: UUID | None,
) -> dict | None:
    """Inserta si no existe una alerta abierta del mismo tipo+deployment (< 24h)."""
    session = await get_async_session()
    try:
        exists = (
            await session.execute(
                text(
                    "SELECT 1 FROM incident_alerts "
                    "WHERE organization_id = :oid AND alert_type = :atype "
                    "AND status IN ('open', 'acknowledged') "
                    "AND (deployment_id IS NOT DISTINCT FROM :did) "
                    "AND created_at > NOW() - INTERVAL '24 hours' LIMIT 1"
                ),
                {"oid": organization_id, "atype": alert_type, "did": deployment_id},
            )
        ).fetchone()
        if exists:
            return None
        created = datetime.now(timezone.utc)
        row = await session.execute(
            text(
                "INSERT INTO incident_alerts (id, organization_id, deployment_id, "
                "alert_type, severity, message, threshold_value, actual_value, status) "
                "VALUES (gen_random_uuid(), :oid, :did, :atype, :sev, :msg, :thr, :act, 'open') "
                "RETURNING id"
            ),
            {
                "oid": organization_id,
                "did": deployment_id,
                "atype": alert_type,
                "sev": severity,
                "msg": message[:500],
                "thr": threshold_value,
                "act": actual_value,
            },
        )
        await session.commit()
        alert_id = row.scalar()
        return {
            "id": str(alert_id),
            "organization_id": str(organization_id),
            "deployment_id": str(deployment_id) if deployment_id else None,
            "alert_type": alert_type,
            "severity": severity,
            "message": message,
            "threshold_value": threshold_value,
            "actual_value": actual_value,
            "status": "open",
            "created_at": created.isoformat(),
        }
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def check_organization(organization_id: UUID) -> list[dict]:
    """Ejecuta las checks de SLO por deployment + worker stall. Devuelve alertas creadas."""
    settings = get_settings()
    created: list[dict] = []

    # 1) Worker stalled (ingestion).
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT last_seen_at FROM worker_heartbeats "
                    "WHERE worker_name = 'ingestion'"
                )
            )
        ).fetchone()
    finally:
        await session.close()
    if row is not None and datetime.now(timezone.utc) - row.last_seen_at > timedelta(
        minutes=settings.OBS_WORKER_STALE_MINUTES
    ):
        alert = await _insert_alert(
            organization_id,
            ALERT_WORKER_STALLED,
            "critical",
            "El worker de ingestion no reporta heartbeat (stale).",
            threshold_value=None,
            actual_value=None,
            deployment_id=None,
        )
        if alert:
            created.append(alert)

    # 2) SLOs por deployment (1h y 24h).
    from src.platform.observability.slos import _slos_for

    session = await get_async_session()
    try:
        deps = (
            await session.execute(
                text(
                    "SELECT d.id, d.slug, d.status FROM deployments d "
                    "WHERE d.organization_id = :oid "
                    "AND d.status IN ('healthy', 'degraded', 'pending')"
                ),
                {"oid": organization_id},
            )
        ).fetchall()
    finally:
        await session.close()

    for dep in deps:
        slo_1h = await _slos_for(organization_id, dep.id, "1h")
        slo_24h = await _slos_for(organization_id, dep.id, "24h")

        if slo_1h["requests"] >= 5 and slo_1h["error_rate_pct"] > settings.OBS_ERROR_RATE_THRESHOLD_PCT:
            alert = await _insert_alert(
                organization_id,
                ALERT_HIGH_ERROR_RATE,
                "critical",
                f"Error rate 1h del deployment '{dep.slug}': {slo_1h['error_rate_pct']}% "
                f"(threshold {settings.OBS_ERROR_RATE_THRESHOLD_PCT}%)",
                threshold_value=settings.OBS_ERROR_RATE_THRESHOLD_PCT,
                actual_value=slo_1h["error_rate_pct"],
                deployment_id=dep.id,
            )
            if alert:
                created.append(alert)

        if slo_1h["requests"] >= 5 and slo_1h["p95_ms"] > settings.OBS_P95_LATENCY_MS:
            alert = await _insert_alert(
                organization_id,
                ALERT_HIGH_LATENCY,
                "warning",
                f"p95 1h del deployment '{dep.slug}': {slo_1h['p95_ms']:.0f}ms "
                f"(threshold {settings.OBS_P95_LATENCY_MS:.0f}ms)",
                threshold_value=settings.OBS_P95_LATENCY_MS,
                actual_value=slo_1h["p95_ms"],
                deployment_id=dep.id,
            )
            if alert:
                created.append(alert)

        if slo_24h["requests"] >= 20 and slo_24h["availability_pct"] < settings.OBS_AVAILABILITY_THRESHOLD_PCT:
            alert = await _insert_alert(
                organization_id,
                ALERT_LOW_AVAILABILITY,
                "critical",
                f"Disponibilidad 24h del deployment '{dep.slug}': "
                f"{slo_24h['availability_pct']}% (threshold "
                f"{settings.OBS_AVAILABILITY_THRESHOLD_PCT}%)",
                threshold_value=settings.OBS_AVAILABILITY_THRESHOLD_PCT,
                actual_value=slo_24h["availability_pct"],
                deployment_id=dep.id,
            )
            if alert:
                created.append(alert)

        if dep.status in ("failed", "degraded"):
            alert = await _insert_alert(
                organization_id,
                ALERT_DEPLOYMENT_UNHEALTHY,
                "critical",
                f"Deployment '{dep.slug}' está en estado {dep.status}.",
                threshold_value=None,
                actual_value=None,
                deployment_id=dep.id,
            )
            if alert:
                created.append(alert)

    # 3) Webhook delivery para las alertas nuevas.
    for alert in created:
        try:
            alert["webhook_status"] = await deliver_webhook(organization_id, alert)
            if alert["webhook_status"]:
                session = await get_async_session()
                try:
                    await session.execute(
                        text(
                            "UPDATE incident_alerts SET webhook_status = :ws "
                            "WHERE id = :aid"
                        ),
                        {"ws": alert["webhook_status"], "aid": UUID(alert["id"])},
                    )
                    await session.commit()
                finally:
                    await session.close()
        except Exception as exc:
            logger.warning("Webhook step failed", error=str(exc)[:200])

    return created


async def list_alerts(
    organization_id: UUID | None,
    status: str | None = None,
    limit: int = 50,
) -> list[dict]:
    session = await get_async_session()
    try:
        sql = (
            "SELECT id, organization_id, deployment_id, alert_type, severity, "
            "message, threshold_value, actual_value, status, webhook_status, "
            "created_at, resolved_at FROM incident_alerts WHERE 1=1 "
        )
        params: dict = {"limit": limit}
        if organization_id is not None:
            sql += " AND organization_id = :oid "
            params["oid"] = organization_id
        if status:
            sql += " AND status = :status "
            params["status"] = status
        sql += " ORDER BY created_at DESC LIMIT :limit"
        rows = (
            await session.execute(text(sql), params)
        ).fetchall()
    finally:
        await session.close()
    return [
        {
            "id": str(r.id),
            "organization_id": str(r.organization_id),
            "deployment_id": str(r.deployment_id) if r.deployment_id else None,
            "alert_type": r.alert_type,
            "severity": r.severity,
            "message": r.message,
            "threshold_value": r.threshold_value,
            "actual_value": r.actual_value,
            "status": r.status,
            "webhook_status": r.webhook_status,
            "created_at": r.created_at.isoformat(),
            "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
        }
        for r in rows
    ]


async def resolve_alert(alert_id: UUID) -> bool:
    session = await get_async_session()
    try:
        result = await session.execute(
            text(
                "UPDATE incident_alerts SET status = 'resolved', resolved_at = NOW() "
                "WHERE id = :aid AND status <> 'resolved'"
            ),
            {"aid": alert_id},
        )
        await session.commit()
        return result.rowcount > 0
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def acknowledge_alert(alert_id: UUID) -> bool:
    session = await get_async_session()
    try:
        result = await session.execute(
            text(
                "UPDATE incident_alerts SET status = 'acknowledged' "
                "WHERE id = :aid AND status = 'open'"
            ),
            {"aid": alert_id},
        )
        await session.commit()
        return result.rowcount > 0
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def set_webhook(organization_id: UUID, url: str | None, enabled: bool) -> None:
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE organizations SET ops_webhook_url = :url, "
                "ops_webhook_enabled = :enabled WHERE id = :oid"
            ),
            {"url": url, "enabled": enabled, "oid": organization_id},
        )
        await session.commit()
    finally:
        await session.close()
