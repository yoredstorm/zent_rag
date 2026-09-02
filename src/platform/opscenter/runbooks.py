# =============================================================================
# AI Ops Runbook & Incident Management v2 — runbooks por alerta, incidentes
# con severidad/SLA (MTTR/MTTD), timeline y escalamiento automático
# (webhook/email/slack con retry).
# =============================================================================
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

SEVERITIES = ("severe", "major", "minor")
STATUSES = ("open", "acknowledged", "resolved")


# ---------------------------------------------------------------------------
# Runbooks
# ---------------------------------------------------------------------------
async def list_runbooks() -> dict:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id, trigger_type, trigger_match, title, description, "
                    "steps, enabled, created_at FROM runbooks ORDER BY created_at"
                )
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "runbooks": [
            {
                "id": str(r.id),
                "trigger_type": r.trigger_type,
                "trigger_match": r.trigger_match,
                "title": r.title,
                "description": r.description,
                "steps": r.steps,
                "enabled": bool(r.enabled),
            }
            for r in rows
        ]
    }


async def create_runbook(
    trigger_type: str, trigger_match: str, title: str, description: str | None, steps: list
) -> dict:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO runbooks (id, trigger_type, trigger_match, title, "
                    "description, steps) "
                    "VALUES (gen_random_uuid(), :tt, :tm, :title, :desc, :steps) "
                    "RETURNING id, trigger_type, trigger_match, title"
                ),
                {
                    "tt": trigger_type[:60],
                    "tm": trigger_match[:120],
                    "title": title[:160],
                    "desc": description,
                    "steps": json.dumps(steps),
                },
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    return {"id": str(row.id), "trigger_type": row.trigger_type, "title": row.title}


async def delete_runbook(runbook_id: UUID) -> bool:
    session = await get_async_session()
    try:
        result = await session.execute(
            text("DELETE FROM runbooks WHERE id = :rid"),
            {"rid": runbook_id},
        )
        await session.commit()
        return result.rowcount > 0
    finally:
        await session.close()


async def _execute_step(
    organization_id: UUID,
    incident_id: UUID,
    step: dict,
    runbook_title: str,
    step_index: int,
) -> str:
    action = step.get("action", "annotate")
    params = step.get("params") or {}
    detail = f"runbook={runbook_title!r} step={step_index + 1} action={action}"
    if action == "sleep":
        await asyncio.sleep(min(float(params.get("seconds", 0)), 2.0))
    elif action == "send_webhook":
        ok = await _notify_webhook(
            organization_id,
            {
                "event": params.get("event", "runbook"),
                "incident_id": str(incident_id),
            },
        )
        detail += f" webhook={'ok' if ok else 'failed'}"
    elif action == "send_email":
        ok = await _notify_email(organization_id, params.get("subject", "Incidente Zent"), str(incident_id))
        detail += f" email={'ok' if ok else 'skipped'}"
    await _append_event(incident_id, "runbook_step", detail, actor="runbook")
    return detail


async def run_runbooks(
    organization_id: UUID, incident_id: UUID, trigger_type: str, trigger_match: str = "*"
) -> list[str]:
    """Ejecuta los runbooks cuyo trigger coincide (fail-soft por paso)."""
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id, trigger_type, trigger_match, title, steps FROM runbooks "
                    "WHERE enabled AND trigger_type = :tt "
                    "AND (:tm = '*' OR trigger_match = '*' OR trigger_match = :tm)"
                ),
                {"tt": trigger_type, "tm": trigger_match},
            )
        ).fetchall()
    finally:
        await session.close()
    executed: list[str] = []
    for row in rows:
        steps = row.steps or []
        for index, step in enumerate(steps):
            try:
                await _execute_step(organization_id, incident_id, step, row.title, index)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Runbook step failed", error=str(exc)[:150])
        executed.append(row.title)
    return executed


# ---------------------------------------------------------------------------
# Incidentes
# ---------------------------------------------------------------------------
async def open_incident(
    organization_id: UUID,
    *,
    title: str,
    description: str | None = None,
    source: str = "manual",
    severity: str = "major",
    occurred_at: datetime | None = None,
    actor: str | None = None,
    auto_runbook: bool = True,
) -> dict:
    now = datetime.now(timezone.utc)
    occurred = occurred_at or now
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO incidents (id, organization_id, source, severity, "
                    "status, title, description, occurred_at, detected_at, "
                    "mttd_seconds) "
                    "VALUES (gen_random_uuid(), :oid, :src, :sev, 'open', :title, "
                    ":desc, :occ, :det, :mttd) "
                    "RETURNING id, title, severity"
                ),
                {
                    "oid": organization_id,
                    "src": source[:60],
                    "sev": severity if severity in SEVERITIES else "major",
                    "title": title[:200],
                    "desc": description,
                    "occ": occurred,
                    "det": now,
                    "mttd": round((now - occurred).total_seconds(), 1)
                    if occurred < now
                    else 0.0,
                },
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    await _append_event(
        row.id, "created", f"Incidente {row.severity} desde {source}", actor=actor
    )
    incident = {
        "id": str(row.id),
        "title": row.title,
        "severity": row.severity,
    }
    if auto_runbook:
        try:
            await run_runbooks(organization_id, row.id, source, "*")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Runbook auto-run failed", error=str(exc)[:150])
    return incident


async def _append_event(incident_id: UUID, event_type: str, detail: str, actor: str | None = None) -> None:
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO incident_events (id, incident_id, type, detail, actor) "
                "VALUES (gen_random_uuid(), :iid, :type, :detail, :actor)"
            ),
            {
                "iid": incident_id,
                "type": event_type[:30],
                "detail": detail,
                "actor": actor,
            },
        )
        await session.commit()
    finally:
        await session.close()


async def ack_incident(incident_id: UUID, actor: str | None = None) -> bool:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "UPDATE incidents SET status = 'acknowledged', acknowledged_at = NOW() "
                    "WHERE id = :iid AND status <> 'resolved' RETURNING id"
                ),
                {"iid": incident_id},
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    if row is None:
        return False
    await _append_event(incident_id, "acknowledged", "Incidente reconocido", actor=actor)
    return True


async def resolve_incident(incident_id: UUID, actor: str | None = None, resolution: str | None = None) -> bool:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "UPDATE incidents SET status = 'resolved', resolved_at = NOW(), "
                    "mttr_seconds = EXTRACT(EPOCH FROM (NOW() - detected_at)) "
                    "WHERE id = :iid AND status <> 'resolved' RETURNING id, mttr_seconds"
                ),
                {"iid": incident_id},
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    if row is None:
        return False
    await _append_event(
        incident_id,
        "resolved",
        f"Incidente resuelto ({resolution or ''}) MTTR={round(float(row.mttr_seconds), 1)}s",
        actor=actor,
    )
    return True


async def list_incidents(
    organization_id: UUID | None = None,
    status: str | None = None,
    hours: int = 168,
    limit: int = 100,
) -> dict:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    session = await get_async_session()
    try:
        where = ["detected_at >= :since"]
        params: dict = {"since": since, "limit": limit}
        if organization_id:
            where.append("organization_id = :oid")
            params["oid"] = organization_id
        if status:
            where.append("status = :status")
            params["status"] = status
        rows = (
            await session.execute(
                text(
                    "SELECT id, organization_id, source, severity, status, title, "
                    "description, occurred_at, detected_at, acknowledged_at, "
                    "resolved_at, mttd_seconds, mttr_seconds, assigned_to "
                    "FROM incidents WHERE "
                    + " AND ".join(where)
                    + " ORDER BY detected_at DESC LIMIT :limit"
                ),
                params,
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "incidents": [
            {
                "id": str(r.id),
                "organization_id": str(r.organization_id),
                "source": r.source,
                "severity": r.severity,
                "status": r.status,
                "title": r.title,
                "description": r.description,
                "occurred_at": r.occurred_at.isoformat(),
                "detected_at": r.detected_at.isoformat(),
                "acknowledged_at": r.acknowledged_at.isoformat() if r.acknowledged_at else None,
                "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
                "mttd_seconds": round(float(r.mttd_seconds), 1) if r.mttd_seconds is not None else None,
                "mttr_seconds": round(float(r.mttr_seconds), 1) if r.mttr_seconds is not None else None,
                "assigned_to": r.assigned_to,
            }
            for r in rows
        ],
        "count": len(rows),
    }


async def incident_detail(incident_id: UUID) -> dict | None:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT id, organization_id, source, severity, status, title, "
                    "description, occurred_at, detected_at, acknowledged_at, "
                    "resolved_at, mttd_seconds, mttr_seconds, assigned_to "
                    "FROM incidents WHERE id = :iid"
                ),
                {"iid": incident_id},
            )
        ).fetchone()
        if row is None:
            return None
        events = (
            await session.execute(
                text(
                    "SELECT id, type, detail, actor, created_at FROM incident_events "
                    "WHERE incident_id = :iid ORDER BY created_at"
                ),
                {"iid": incident_id},
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "id": str(row.id),
        "organization_id": str(row.organization_id),
        "source": row.source,
        "severity": row.severity,
        "status": row.status,
        "title": row.title,
        "description": row.description,
        "occurred_at": row.occurred_at.isoformat(),
        "detected_at": row.detected_at.isoformat(),
        "acknowledged_at": row.acknowledged_at.isoformat() if row.acknowledged_at else None,
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
        "mttd_seconds": round(float(row.mttd_seconds), 1) if row.mttd_seconds is not None else None,
        "mttr_seconds": round(float(row.mttr_seconds), 1) if row.mttr_seconds is not None else None,
        "assigned_to": row.assigned_to,
        "timeline": [
            {
                "id": str(e.id),
                "type": e.type,
                "detail": e.detail,
                "actor": e.actor,
                "created_at": e.created_at.isoformat(),
            }
            for e in events
        ],
    }


# ---------------------------------------------------------------------------
# Métricas (MTTR/MTTD por severidad)
# ---------------------------------------------------------------------------
async def incident_metrics(hours: int = 168) -> dict:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT severity, "
                    "COUNT(*) AS total, "
                    "COUNT(*) FILTER (WHERE status = 'resolved') AS resolved, "
                    "AVG(mttr_seconds) FILTER (WHERE mttr_seconds IS NOT NULL) AS avg_mttr, "
                    "AVG(mttd_seconds) FILTER (WHERE mttd_seconds IS NOT NULL) AS avg_mttd "
                    "FROM incidents WHERE detected_at >= :since "
                    "GROUP BY severity ORDER BY severity"
                ),
                {"since": since},
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "window_hours": hours,
        "by_severity": [
            {
                "severity": r.severity,
                "total": int(r.total),
                "resolved": int(r.resolved),
                "avg_mttr_seconds": round(float(r.avg_mttr), 1) if r.avg_mttr is not None else None,
                "avg_mttd_seconds": round(float(r.avg_mttd), 1) if r.avg_mttd is not None else None,
            }
            for r in rows
        ],
    }


# ---------------------------------------------------------------------------
# Escalamiento automático
# ---------------------------------------------------------------------------
async def _notify_webhook(organization_id: UUID, payload: dict) -> bool:
    try:
        from src.platform.observability.alerts import _get_webhook, _post_webhook

        url, enabled = await _get_webhook(organization_id)
        if not url or not enabled:
            return False
        return await _post_webhook(url, {"event": "incident_escalation", **payload})
    except Exception as exc:  # noqa: BLE001
        logger.warning("Escalation webhook failed", error=str(exc)[:150])
        return False


async def _notify_email(organization_id: UUID, subject: str, incident_id: str) -> bool:
    try:
        from src.platform.customer_success.customer_success import send_email

        session = await get_async_session()
        try:
            email = (
                await session.execute(
                    text("SELECT email FROM users WHERE organization_id = :oid LIMIT 1"),
                    {"oid": organization_id},
                )
            ).scalar()
        finally:
            await session.close()
        if not email:
            return False
        return await send_email(email, subject, f"<p>Incidente {incident_id}: {subject}</p>")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Escalation email failed", error=str(exc)[:150])
        return False


async def check_escalations() -> dict:
    """Dispara los pasos de escalamiento pendientes (retry: reintenta con 3
    intentos espaciados 5 s si la notificación falla)."""
    now = datetime.now(timezone.utc)
    session = await get_async_session()
    try:
        policies = (
            await session.execute(
                text("SELECT severity, steps FROM escalation_policies WHERE enabled")
            )
        ).fetchall()
        incidents = (
            await session.execute(
                text(
                    "SELECT id, organization_id, severity, detected_at FROM incidents "
                    "WHERE status <> 'resolved'"
                )
            )
        ).fetchall()
        fired_events = (
            await session.execute(
                text(
                    "SELECT incident_id, detail FROM incident_events "
                    "WHERE type = 'escalation'"
                )
            )
        ).fetchall()
    finally:
        await session.close()

    fired: list[tuple] = [
        (e.incident_id, marker)
        for e in fired_events
        for marker in ("step=0", "step=1", "step=2", "step=3", "step=4")
        if marker in (e.detail or "")
    ]
    policy_by_severity = {p.severity: (p.steps or []) for p in policies}
    triggered: list[dict] = []

    for incident in incidents:
        steps = policy_by_severity.get(incident.severity, [])
        elapsed = (now - incident.detected_at).total_seconds() / 60
        for index, step in enumerate(steps):
            if elapsed < float(step.get("after_minutes", 60)):
                continue
            marker = f"step={index}"
            if (incident.id, marker) in fired:
                continue
            notified = []
            for channel in step.get("notify", ["webhook"]):
                ok = False
                for _attempt in range(3):
                    if channel == "webhook":
                        ok = await _notify_webhook(
                            incident.organization_id,
                            {"severity": incident.severity, "incident_id": str(incident.id)},
                        )
                    elif channel in ("email", "slack"):
                        ok = await _notify_email(
                            incident.organization_id,
                            f"[{incident.severity}] Incidente requiere atención",
                            str(incident.id),
                        )
                    if ok:
                        break
                    await asyncio.sleep(5)
                notified.append(f"{channel}:{'ok' if ok else 'failed'}")
            await _append_event(
                incident.id,
                "escalation",
                f"Escalación {marker} tras {step.get('after_minutes')}min → {', '.join(notified)}",
                actor="escalation_policy",
            )
            triggered.append(
                {
                    "incident_id": str(incident.id),
                    "severity": incident.severity,
                    "step": index,
                    "notify": notified,
                }
            )
    return {"triggered": triggered, "count": len(triggered)}
