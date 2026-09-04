# =============================================================================
# AI Security Operations Center (SOC) v2 — detección en tiempo real,
# respuestas automáticas y postura de seguridad.
# =============================================================================
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

EVENT_TYPES = ("prompt_injection", "data_exfiltration", "api_key_abuse", "traffic_anomaly", "pii_exposure")
INJECTION_PATTERNS = (
    "ignora las instrucciones",
    "ignora instrucciones",
    "system prompt",
    "instrucciones del sistema",
    "override",
    "dame tus instrucciones",
    "actúa como si fueras",
    "desbloquea",
)
PII_PATTERNS = ("rut ", "correo:", "tarjeta", "cvv", "ssn", "clave secreta", "contraseña de acceso")


def _severity_for(score: float) -> str:
    if score >= 75:
        return "critical"
    if score >= 50:
        return "high"
    if score >= 25:
        return "medium"
    return "low"


async def _recent_event(organization_id: UUID, event_type: str) -> tuple | None:
    session = await get_async_session()
    try:
        return (
            await session.execute(
                text(
                    "SELECT id FROM security_events WHERE organization_id = :oid "
                    "AND event_type = :etype AND detected_at >= NOW() - interval '24 hours' "
                    "ORDER BY detected_at DESC LIMIT 1"
                ),
                {"oid": organization_id, "etype": event_type},
            )
        ).fetchone()
    finally:
        await session.close()


async def _create_event(
    organization_id: UUID,
    event_type: str,
    score: float,
    evidence: dict,
    timeline: list | None = None,
) -> dict:
    severity = _severity_for(score)
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO security_events (id, organization_id, event_type, severity, "
                    "score, evidence, timeline) "
                    "VALUES (gen_random_uuid(), :oid, :etype, :sev, :score, "
                    "CAST(:ev AS jsonb), CAST(:tl AS jsonb)) RETURNING id, severity"
                ),
                {
                    "oid": organization_id,
                    "etype": event_type,
                    "sev": severity,
                    "score": round(score, 1),
                    "ev": json.dumps(evidence),
                    "tl": json.dumps(timeline or []),
                },
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    return {"event_id": str(row.id), "event_type": event_type, "severity": row.severity}


async def scan_organization(organization_id: UUID) -> dict:
    """Detección en tiempo real con scoring y dedupe de 24h."""
    detected: list[dict] = []
    session = await get_async_session()
    try:
        recent_msgs = (
            await session.execute(
                text(
                    "SELECT m.content, m.created_at FROM copilot_messages m "
                    "JOIN copilot_sessions s ON s.id = m.session_id "
                    "WHERE s.organization_id = :oid AND m.role = 'user' "
                    "AND m.created_at >= NOW() - interval '7 days' "
                    "ORDER BY m.created_at DESC LIMIT 200"
                ),
                {"oid": organization_id},
            )
        ).fetchall()
        blocked_incidents = (
            await session.execute(
                text(
                    "SELECT snippet, score, rule_name, created_at FROM safety_incidents "
                    "WHERE organization_id = :oid AND action = 'block' "
                    "AND created_at >= NOW() - interval '7 days' "
                    "ORDER BY created_at DESC LIMIT 100"
                ),
                {"oid": organization_id},
            )
        ).fetchall()
        hour_count = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM api_logs WHERE organization_id = :oid "
                    "AND created_at >= NOW() - interval '1 hour'"
                ),
                {"oid": organization_id},
            )
        ).scalar()
        day_count = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM api_logs WHERE organization_id = :oid "
                    "AND created_at >= NOW() - interval '24 hours'"
                ),
                {"oid": organization_id},
            )
        ).scalar()
        auth_fails = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM api_logs WHERE organization_id = :oid "
                    "AND status IN (401, 403, 429) "
                    "AND created_at >= NOW() - interval '24 hours'"
                ),
                {"oid": organization_id},
            )
        ).scalar()
    finally:
        await session.close()

    # 1) Prompt injection en mensajes del copilot.
    injections = [
        m.content
        for m in recent_msgs
        if any(p in m.content.lower() for p in INJECTION_PATTERNS)
    ]
    if injections:
        score = min(40 + len(injections) * 20, 100)
        if await _recent_event(organization_id, "prompt_injection") is None:
            result = await _create_event(
                organization_id,
                "prompt_injection",
                score,
                {"matches": len(injections), "samples": injections[:3]},
                [{"step": "detected", "detail": f"{len(injections)} mensajes con patrones de inyección",
                  "at": datetime.now(timezone.utc).isoformat()}],
            )
            detected.append(result)

    # 2) Exfiltración / exposición de datos (incidentes de moderación severos).
    pii_matches = [
        s.snippet for s in blocked_incidents if any(p in (s.snippet or "").lower() for p in PII_PATTERNS)
    ]
    if pii_matches:
        score = min(50 + len(pii_matches) * 15, 100)
        if await _recent_event(organization_id, "pii_exposure") is None:
            result = await _create_event(
                organization_id,
                "pii_exposure",
                score,
                {"matches": len(pii_matches), "samples": pii_matches[:3]},
                [{"step": "detected", "detail": "Datos personales detectados en respuestas bloqueadas",
                  "at": datetime.now(timezone.utc).isoformat()}],
            )
            detected.append(result)
    severe_blocks = [s for s in blocked_incidents if float(s.score or 0) >= 90]
    if severe_blocks:
        score = min(45 + len(severe_blocks) * 10, 100)
        if await _recent_event(organization_id, "data_exfiltration") is None:
            result = await _create_event(
                organization_id,
                "data_exfiltration",
                score,
                {"blocked_with_high_score": len(severe_blocks), "rules": [s.rule_name for s in severe_blocks[:3]]},
                [{"step": "detected", "detail": f"{len(severe_blocks)} salidas bloqueadas con score ≥ 90",
                  "at": datetime.now(timezone.utc).isoformat()}],
            )
            detected.append(result)

    # 3) Abuso de API key (errores de auth).
    fails = int(auth_fails or 0)
    if fails >= 5:
        score = min(30 + fails * 8, 100)
        if await _recent_event(organization_id, "api_key_abuse") is None:
            result = await _create_event(
                organization_id,
                "api_key_abuse",
                score,
                {"auth_failures_24h": fails},
                [{"step": "detected", "detail": f"{fails} fallos de autenticación en 24h",
                  "at": datetime.now(timezone.utc).isoformat()}],
            )
            detected.append(result)

    # 4) Anomalía de tráfico (pico > 3x la media horaria).
    hours = int(day_count or 0) / 24
    current = int(hour_count or 0)
    if hours >= 5 and current > hours * 3:
        score = min(35 + current / hours * 5, 100)
        if await _recent_event(organization_id, "traffic_anomaly") is None:
            result = await _create_event(
                organization_id,
                "traffic_anomaly",
                score,
                {"last_hour": current, "avg_per_hour": round(hours, 1), "ratio": round(current / hours, 1)},
                [{"step": "detected", "detail": f"Tráfico {current}/h vs media {round(hours, 1)}/h",
                  "at": datetime.now(timezone.utc).isoformat()}],
            )
            detected.append(result)

    return {"scanned": True, "detected": detected, "checked_events": EVENT_TYPES}


# ---------------------------------------------------------------------------
# Eventos
# ---------------------------------------------------------------------------
async def list_events(organization_id: UUID, status: str | None = None) -> dict:
    session = await get_async_session()
    try:
        params: dict = {"oid": organization_id}
        where = ""
        if status:
            where = " AND status = :status"
            params["status"] = status
        rows = (
            await session.execute(
                text(
                    "SELECT id, event_type, severity, score, status, evidence, detected_at, "
                    "resolved_at, "
                    "(SELECT COUNT(*) FROM security_responses r WHERE r.event_id = e.id) AS responses "
                    "FROM security_events e WHERE organization_id = :oid" + where + " "
                    "ORDER BY detected_at DESC LIMIT 100"
                ),
                params,
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "events": [
            {
                "id": str(r.id),
                "event_type": r.event_type,
                "severity": r.severity,
                "score": float(r.score),
                "status": r.status,
                "evidence": r.evidence,
                "responses": int(r.responses),
                "detected_at": r.detected_at.isoformat(),
                "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
            }
            for r in rows
        ]
    }


async def event_detail(organization_id: UUID, event_id: UUID) -> dict | None:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT id, event_type, severity, score, status, evidence, timeline, "
                    "detected_at, resolved_at FROM security_events "
                    "WHERE id = :eid AND organization_id = :oid"
                ),
                {"eid": event_id, "oid": organization_id},
            )
        ).fetchone()
        if row is None:
            return None
        responses = (
            await session.execute(
                text(
                    "SELECT id, action_type, target, status, detail, created_at "
                    "FROM security_responses WHERE event_id = :eid ORDER BY created_at"
                ),
                {"eid": event_id},
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "id": str(row.id),
        "event_type": row.event_type,
        "severity": row.severity,
        "score": float(row.score),
        "status": row.status,
        "evidence": row.evidence,
        "timeline": row.timeline,
        "detected_at": row.detected_at.isoformat(),
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
        "responses": [
            {
                "id": str(r.id),
                "action_type": r.action_type,
                "target": r.target,
                "status": r.status,
                "detail": r.detail,
                "created_at": r.created_at.isoformat(),
            }
            for r in responses
        ],
    }


async def _append_timeline(event_id: UUID, step: str, detail: str) -> None:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text("SELECT timeline FROM security_events WHERE id = :eid"),
                {"eid": event_id},
            )
        ).fetchone()
        if row is None:
            await session.commit()
            return
        timeline = list(row.timeline or [])
        timeline.append({"step": step, "detail": detail, "at": datetime.now(timezone.utc).isoformat()})
        await session.execute(
            text("UPDATE security_events SET timeline = CAST(:tl AS jsonb) WHERE id = :eid"),
            {"tl": json.dumps(timeline), "eid": event_id},
        )
        await session.commit()
    finally:
        await session.close()


# ---------------------------------------------------------------------------
# Respuestas automáticas
# ---------------------------------------------------------------------------
async def respond(organization_id: UUID, event_id: UUID, action_type: str) -> dict | None:
    if action_type not in ("revoke_key", "block_deployment", "throttle", "alert"):
        raise ValueError("action_type debe ser revoke_key|block_deployment|throttle|alert")
    row = await event_detail(organization_id, event_id)
    if row is None:
        return None
    detail = ""
    target = ""
    executed = True

    if action_type == "revoke_key":
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "UPDATE api_keys SET is_active = false WHERE organization_id = :oid "
                    "AND is_active = true"
                ),
                {"oid": organization_id},
            )
            await session.commit()
            detail = f"{result.rowcount} API key(s) revocada(s)"
            target = "api_keys"
        finally:
            await session.close()
    elif action_type == "block_deployment":
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "UPDATE deployments SET status = 'blocked' "
                    "WHERE organization_id = :oid AND status = 'healthy'"
                ),
                {"oid": organization_id},
            )
            await session.commit()
            detail = f"{result.rowcount} deployment(s) bloqueado(s)"
            target = "deployments"
        finally:
            await session.close()
    elif action_type == "throttle":
        session = await get_async_session()
        try:
            plan = (
                await session.execute(
                    text(
                        "SELECT p.name FROM subscriptions s "
                        "JOIN plans p ON p.id = s.plan_id "
                        "WHERE s.organization_id = :oid AND s.status = 'active' LIMIT 1"
                    ),
                    {"oid": organization_id},
                )
            ).scalar()
            result = await session.execute(
                text(
                    "UPDATE rate_limit_rules SET throttle_factor = 0.5 "
                    "WHERE (plan_name = :plan) OR (plan_name IS NULL)"
                ),
                {"plan": plan or "trial"},
            )
            await session.commit()
            detail = f"Throttling 50% aplicado a {result.rowcount} regla(s)"
            target = "rate_limit_rules"
        finally:
            await session.close()
    elif action_type == "alert":
        from src.platform.notifyv2.notifications import notify

        await notify(
            organization_id=organization_id,
            event_type="security.event",
            title=f"Incidente {row['event_type']} ({row['severity']})",
            body=f"Score {row['score']}: {row['evidence']}",
        )
        detail = "Notificación enviada al equipo"
        target = "notifications"

    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO security_responses (id, event_id, action_type, target, status, detail) "
                "VALUES (gen_random_uuid(), :eid, :action, :target, :status, :detail)"
            ),
            {
                "eid": event_id,
                "action": action_type,
                "target": target,
                "status": "executed" if executed else "failed",
                "detail": detail,
            },
        )
        await session.execute(
            text(
                "UPDATE security_events SET status = 'contained' "
                "WHERE id = :eid AND status = 'detected'"
            ),
            {"eid": event_id},
        )
        await session.commit()
    finally:
        await session.close()
    await _append_timeline(event_id, "response", f"{action_type}: {detail}")
    return {"event_id": str(event_id), "action_type": action_type, "detail": detail}


async def resolve_event(organization_id: UUID, event_id: UUID, verdict: str = "resolved") -> dict | None:
    if verdict not in ("resolved", "false_positive"):
        raise ValueError("verdict debe ser resolved|false_positive")
    row = await event_detail(organization_id, event_id)
    if row is None:
        return None
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE security_events SET status = :verdict, resolved_at = NOW() "
                "WHERE id = :eid"
            ),
            {"verdict": verdict, "eid": event_id},
        )
        await session.commit()
    finally:
        await session.close()
    await _append_timeline(event_id, "resolved", f"Evento marcado como {verdict}")
    return {"event_id": str(event_id), "status": verdict}


# ---------------------------------------------------------------------------
# Postura de seguridad
# ---------------------------------------------------------------------------
async def security_posture(organization_id: UUID) -> dict:
    session = await get_async_session()
    try:
        open_events = (
            await session.execute(
                text(
                    "SELECT COUNT(*) AS open_count, COALESCE(SUM(score), 0) AS total_score "
                    "FROM security_events WHERE organization_id = :oid "
                    "AND status IN ('detected', 'analyzing', 'contained')"
                ),
                {"oid": organization_id},
            )
        ).fetchone()
        by_type = (
            await session.execute(
                text(
                    "SELECT event_type, COUNT(*) AS n, COALESCE(AVG(score), 0) AS avg_score "
                    "FROM security_events WHERE organization_id = :oid "
                    "AND status NOT IN ('resolved', 'false_positive') "
                    "GROUP BY event_type ORDER BY n DESC"
                ),
                {"oid": organization_id},
            )
        ).fetchall()
    finally:
        await session.close()
    open_count = int(open_events.open_count or 0)
    total_score = float(open_events.total_score or 0)
    threat_score = round(min(total_score / max(open_count, 1) * 0.6, 100), 1) if open_count else 0.0
    today = date.today()
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO security_posture_snapshots (id, organization_id, date, threat_score, open_events) "
                "VALUES (gen_random_uuid(), :oid, :day, :score, :open) "
                "ON CONFLICT (organization_id, date) DO UPDATE SET "
                "threat_score = :score, open_events = :open"
            ),
            {"oid": organization_id, "day": today, "score": threat_score, "open": open_count},
        )
        await session.commit()
    finally:
        await session.close()
    return {
        "threat_score": threat_score,
        "open_events": open_count,
        "by_type": [
            {"event_type": r.event_type, "count": int(r.n), "avg_score": round(float(r.avg_score or 0), 1)}
            for r in by_type
        ],
    }


async def posture_trend(organization_id: UUID, days: int = 30) -> dict:
    since = date.today() - timedelta(days=days)
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT date, threat_score, open_events FROM security_posture_snapshots "
                    "WHERE organization_id = :oid AND date >= :since ORDER BY date"
                ),
                {"oid": organization_id, "since": since},
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "trend": [
            {"date": r.date.isoformat(), "threat_score": float(r.threat_score), "open_events": int(r.open_events)}
            for r in rows
        ]
    }


# ---------------------------------------------------------------------------
# Dashboard platform
# ---------------------------------------------------------------------------
async def soc_dashboard() -> dict:
    session = await get_async_session()
    try:
        totals = (
            await session.execute(
                text(
                    "SELECT COUNT(*) AS total, "
                    "COUNT(*) FILTER (WHERE status IN ('detected', 'analyzing', 'contained')) AS open_count, "
                    "COUNT(*) FILTER (WHERE status = 'resolved') AS resolved_count "
                    "FROM security_events WHERE detected_at >= NOW() - interval '7 days'"
                )
            )
        ).fetchone()
        by_type = (
            await session.execute(
                text(
                    "SELECT event_type, COUNT(*) AS n, "
                    "COUNT(*) FILTER (WHERE severity = 'critical') AS criticals "
                    "FROM security_events WHERE detected_at >= NOW() - interval '7 days' "
                    "GROUP BY event_type ORDER BY n DESC"
                )
            )
        ).fetchall()
        by_severity = (
            await session.execute(
                text(
                    "SELECT severity, COUNT(*) AS n FROM security_events "
                    "WHERE detected_at >= NOW() - interval '7 days' GROUP BY severity"
                )
            )
        ).fetchall()
        responses = (
            await session.execute(
                text(
                    "SELECT action_type, COUNT(*) AS n FROM security_responses "
                    "WHERE created_at >= NOW() - interval '7 days' GROUP BY action_type"
                )
            )
        ).fetchall()
        top_orgs = (
            await session.execute(
                text(
                    "SELECT o.name AS org_name, COUNT(e.id) AS events, "
                    "COALESCE(SUM(e.score), 0) AS total_score "
                    "FROM security_events e JOIN organizations o ON o.id = e.organization_id "
                    "WHERE e.detected_at >= NOW() - interval '7 days' "
                    "GROUP BY o.id ORDER BY total_score DESC LIMIT 8"
                )
            )
        ).fetchall()
        avg_posture = (
            await session.execute(
                text(
                    "SELECT COALESCE(AVG(threat_score), 0) FROM security_posture_snapshots "
                    "WHERE date = CURRENT_DATE"
                )
            )
        ).scalar()
    finally:
        await session.close()
    return {
        "events_7d": int(totals.total or 0),
        "open_events": int(totals.open_count or 0),
        "resolved_7d": int(totals.resolved_count or 0),
        "avg_threat_score": round(float(avg_posture or 0), 1),
        "by_type": [
            {"event_type": r.event_type, "count": int(r.n), "criticals": int(r.criticals)} for r in by_type
        ],
        "by_severity": [{"severity": r.severity, "count": int(r.n)} for r in by_severity],
        "responses": [{"action_type": r.action_type, "count": int(r.n)} for r in responses],
        "top_organizations": [
            {"org": r.org_name, "events": int(r.events), "total_score": round(float(r.total_score or 0), 1)}
            for r in top_orgs
        ],
    }
