# =============================================================================
# AI Chat Analytics & Conversational Insights v2 — embudo, temas, fricción
# y comparativa por canal.
# =============================================================================
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

TOPIC_KEYWORDS: dict[str, list[str]] = {
    "soporte": ["soporte", "ayuda", "error", "falla", "no funciona", "problema"],
    "ventas": ["precio", "costo", "plan", "compra", "contratar", "oferta"],
    "despliegue": ["deploy", "desplieg", "producción", "publicar", "entorno"],
    "kb": ["documento", "pdf", "base de conocimiento", "manual", "guía", "guia"],
    "facturación": ["factura", "pago", "suscripción", "suscripcion", "cobro", "iva"],
    "legal": ["legal", "contrato", "cláusula", "clausula", "política", "politica", "términos", "terminos"],
    "rrhh": ["beneficios", "vacaciones", "sueldo", "rrhh", "onboarding", "feriado"],
    "cuentas": ["cuenta", "login", "acceso", "usuario", "password", "contraseña"],
}


def _detect_topics(message: str) -> list[str]:
    lowered = message.lower()
    found = []
    for topic, keywords in TOPIC_KEYWORDS.items():
        if any(kw in lowered for kw in keywords):
            found.append(topic)
    return found


async def _track_topics(organization_id: UUID, message: str) -> list[str]:
    topics = _detect_topics(message)
    if not topics:
        return []
    session = await get_async_session()
    try:
        for topic in topics:
            await session.execute(
                text(
                    "INSERT INTO conversation_topics (id, organization_id, topic, "
                    "keywords, message_count, last_seen_at) "
                    "VALUES (gen_random_uuid(), :oid, :topic, CAST(:kw AS jsonb), 1, NOW()) "
                    "ON CONFLICT (organization_id, topic) DO UPDATE SET "
                    "message_count = conversation_topics.message_count + 1, "
                    "last_seen_at = NOW()"
                ),
                {"oid": organization_id, "topic": topic, "kw": __import__("json").dumps(TOPIC_KEYWORDS[topic])},
            )
        await session.commit()
    finally:
        await session.close()
    return topics


async def record_chat_event(
    organization_id: UUID,
    event_type: str,
    session_id: UUID | None = None,
    detail: str | None = None,
) -> None:
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO chat_events (id, organization_id, session_id, event_type, detail) "
                "VALUES (gen_random_uuid(), :oid, :sid, :etype, :detail)"
            ),
            {"oid": organization_id, "sid": session_id, "etype": event_type[:30], "detail": detail},
        )
        await session.commit()
    finally:
        await session.close()


def _wants_human(message: str) -> bool:
    lowered = message.lower()
    return any(
        kw in lowered
        for kw in ("hablar con un humano", "hablar con alguien", "agente humano", "persona real", "representante")
    )


# ---------------------------------------------------------------------------
# Embudo conversacional
# ---------------------------------------------------------------------------
async def conversation_funnel(organization_id: UUID, days: int = 30) -> dict:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    session = await get_async_session()
    try:
        total_msgs = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM copilot_messages m "
                    "JOIN copilot_sessions s ON s.id = m.session_id "
                    "WHERE s.organization_id = :oid AND m.created_at >= :since"
                ),
                {"oid": organization_id, "since": since},
            )
        ).scalar()
        total_sessions = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM copilot_sessions "
                    "WHERE organization_id = :oid AND created_at >= :since"
                ),
                {"oid": organization_id, "since": since},
            )
        ).scalar()
        active_sessions = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM ("
                    "SELECT s.id FROM copilot_sessions s "
                    "JOIN copilot_messages m ON m.session_id = s.id "
                    "WHERE s.organization_id = :oid AND s.created_at >= :since "
                    "GROUP BY s.id HAVING COUNT(*) FILTER (WHERE m.role = 'user') >= 2"
                    ") t"
                ),
                {"oid": organization_id, "since": since},
            )
        ).scalar()
        resolved_feedbacks = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM feedback f "
                    "WHERE f.organization_id = :oid AND f.rating = 'up' "
                    "AND f.created_at >= :since"
                ),
                {"oid": organization_id, "since": since},
            )
        ).scalar()
        escalated = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM chat_events "
                    "WHERE organization_id = :oid AND event_type = 'escalated' "
                    "AND created_at >= :since"
                ),
                {"oid": organization_id, "since": since},
            )
        ).scalar()
    finally:
        await session.close()
    sessions = int(total_sessions or 0)
    resolved = int(resolved_feedbacks or 0)
    resolution = round(resolved / sessions * 100, 1) if sessions else 0.0
    return {
        "days": days,
        "total_messages": int(total_msgs or 0),
        "total_sessions": sessions,
        "active_sessions": int(active_sessions or 0),
        "resolved_sessions": resolved,
        "resolution_rate": resolution,
        "escalations": int(escalated or 0),
    }


# ---------------------------------------------------------------------------
# Temas
# ---------------------------------------------------------------------------
async def topic_analysis(organization_id: UUID, days: int = 30) -> dict:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT topic, message_count, last_seen_at FROM conversation_topics "
                    "WHERE organization_id = :oid AND last_seen_at >= :since "
                    "ORDER BY message_count DESC LIMIT 15"
                ),
                {"oid": organization_id, "since": since},
            )
        ).fetchall()
        total_msgs = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM copilot_messages m "
                    "JOIN copilot_sessions s ON s.id = m.session_id "
                    "WHERE s.organization_id = :oid AND m.role = 'user' AND m.created_at >= :since"
                ),
                {"oid": organization_id, "since": since},
            )
        ).scalar()
    finally:
        await session.close()
    total = int(total_msgs or 0)
    return {
        "total_user_messages": total,
        "topics": [
            {
                "topic": r.topic,
                "message_count": int(r.message_count),
                "share": round(int(r.message_count) / total * 100, 1) if total else 0.0,
                "last_seen_at": r.last_seen_at.isoformat(),
            }
            for r in rows
        ],
    }


# ---------------------------------------------------------------------------
# Fricción
# ---------------------------------------------------------------------------
async def friction_detection(organization_id: UUID, days: int = 30) -> dict:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    session = await get_async_session()
    try:
        retry_rows = (
            await session.execute(
                text(
                    "SELECT s.id AS session_id, "
                    "COUNT(m.id) FILTER (WHERE m.role = 'user') AS n, "
                    "ARRAY_AGG(m.intent ORDER BY m.created_at DESC) FILTER "
                    "(WHERE m.role = 'user' AND m.intent IS NOT NULL) AS intents "
                    "FROM copilot_sessions s JOIN copilot_messages m ON m.session_id = s.id "
                    "WHERE s.organization_id = :oid AND s.created_at >= :since "
                    "GROUP BY s.id HAVING COUNT(*) FILTER (WHERE m.role = 'user') >= 3 "
                    "ORDER BY n DESC LIMIT 10"
                ),
                {"oid": organization_id, "since": since},
            )
        ).fetchall()
        redirect_rows = (
            await session.execute(
                text(
                    "SELECT s.id AS session_id, "
                    "COUNT(DISTINCT m.intent) FILTER (WHERE m.role = 'user' AND m.intent IS NOT NULL) AS intents "
                    "FROM copilot_sessions s JOIN copilot_messages m ON m.session_id = s.id "
                    "WHERE s.organization_id = :oid AND s.created_at >= :since "
                    "GROUP BY s.id HAVING "
                    "COUNT(DISTINCT m.intent) FILTER (WHERE m.role = 'user' AND m.intent IS NOT NULL) >= 3 "
                    "LIMIT 10"
                ),
                {"oid": organization_id, "since": since},
            )
        ).fetchall()
        events = (
            await session.execute(
                text(
                    "SELECT event_type, COUNT(*) AS n FROM chat_events "
                    "WHERE organization_id = :oid AND created_at >= :since "
                    "GROUP BY event_type"
                ),
                {"oid": organization_id, "since": since},
            )
        ).fetchall()
    finally:
        await session.close()
    retries = [{"session_id": str(r.session_id), "messages": int(r.n)} for r in retry_rows]
    redirects = [{"session_id": str(r.session_id), "intents": int(r.intents)} for r in redirect_rows]
    return {
        "days": days,
        "repetitive_sessions": retries,
        "redirect_sessions": redirects,
        "events": {r.event_type: int(r.n) for r in events},
        "summary": {
            "repetitive": len(retries),
            "redirects": len(redirects),
            "escalations": int(next((r.n for r in events if r.event_type == "escalated"), 0)),
            "friction_index": round((len(retries) * 2 + len(redirects) * 1.5) * 10, 1),
        },
    }


# ---------------------------------------------------------------------------
# Comparativa por canal
# ---------------------------------------------------------------------------
async def channel_comparison(organization_id: UUID, days: int = 30) -> dict:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    session = await get_async_session()
    try:
        api_rows = (
            await session.execute(
                text(
                    "SELECT endpoint, COUNT(*) AS n, AVG(latency_ms) AS avg_latency, "
                    "COUNT(*) FILTER (WHERE status BETWEEN 200 AND 299) AS ok "
                    "FROM api_logs WHERE organization_id = :oid AND created_at >= :since "
                    "GROUP BY endpoint"
                ),
                {"oid": organization_id, "since": since},
            )
        ).fetchall()
        copilot_msgs = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM copilot_messages m "
                    "JOIN copilot_sessions s ON s.id = m.session_id "
                    "WHERE s.organization_id = :oid AND m.created_at >= :since"
                ),
                {"oid": organization_id, "since": since},
            )
        ).scalar()
    finally:
        await session.close()
    widget = [r for r in api_rows if "widget" in (r.endpoint or "")]
    api = [r for r in api_rows if "widget" not in (r.endpoint or "") and "query" in (r.endpoint or "")]

    def _channel(rows: list, label: str) -> dict:
        n = sum(int(r.n) for r in rows)
        if not n:
            return {"channel": label, "messages": 0, "avg_latency_ms": 0, "success_rate": 0.0}
        avg = sum(float(r.avg_latency or 0) * int(r.n) for r in rows) / n
        ok = sum(int(r.ok) for r in rows)
        return {
            "channel": label,
            "messages": n,
            "avg_latency_ms": round(avg, 1),
            "success_rate": round(ok / n * 100, 1),
        }

    return {
        "channels": [
            _channel(api, "api"),
            _channel(widget, "widget"),
            {
                "channel": "copilot",
                "messages": int(copilot_msgs or 0),
                "avg_latency_ms": 0,
                "success_rate": 0.0,
            },
        ]
    }


# ---------------------------------------------------------------------------
# Agregación diaria + overview
# ---------------------------------------------------------------------------
async def aggregate_daily(organization_id: UUID, day: date | None = None) -> dict:
    """Upsert de métricas diarias (embudo + temas) en conversation_insights."""
    day = day or datetime.now(timezone.utc).date()
    funnel = await conversation_funnel(organization_id, days=1)
    topics = await topic_analysis(organization_id, days=1)
    friction = await friction_detection(organization_id, days=1)
    metrics = {
        "messages": funnel["total_messages"],
        "sessions": funnel["total_sessions"],
        "resolution_rate": funnel["resolution_rate"],
        "escalations": funnel["escalations"],
        "topics_detected": len(topics["topics"]),
        "friction_index": friction["summary"]["friction_index"],
    }
    session = await get_async_session()
    try:
        for key, value in metrics.items():
            await session.execute(
                text(
                    "INSERT INTO conversation_insights (id, organization_id, date, metric_key, metric_value) "
                    "VALUES (gen_random_uuid(), :oid, :day, :key, :val) "
                    "ON CONFLICT (organization_id, date, metric_key) DO UPDATE SET "
                    "metric_value = :val"
                ),
                {"oid": organization_id, "day": day, "key": key, "val": float(value)},
            )
        await session.commit()
    finally:
        await session.close()
    return {"date": day.isoformat(), "metrics": metrics}


async def insights_overview(organization_id: UUID, days: int = 7) -> dict:
    since = date.today() - timedelta(days=days)
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT date, metric_key, metric_value FROM conversation_insights "
                    "WHERE organization_id = :oid AND date >= :since "
                    "ORDER BY date"
                ),
                {"oid": organization_id, "since": since},
            )
        ).fetchall()
    finally:
        await session.close()
    trend: dict[str, list] = {}
    for r in rows:
        trend.setdefault(r.metric_key, []).append(
            {"date": r.date.isoformat(), "value": float(r.metric_value)}
        )
    return {
        "days": days,
        "trend": trend,
        "funnel": await conversation_funnel(organization_id, days),
        "topics": await topic_analysis(organization_id, days),
        "friction": await friction_detection(organization_id, days),
        "channels": await channel_comparison(organization_id, days),
    }


# ---------------------------------------------------------------------------
# Dashboard platform
# ---------------------------------------------------------------------------
async def insights_dashboard() -> dict:
    session = await get_async_session()
    try:
        global_funnel = (
            await session.execute(
                text(
                    "SELECT COUNT(DISTINCT s.id) AS sessions, "
                    "COUNT(m.id) AS messages "
                    "FROM copilot_sessions s "
                    "LEFT JOIN copilot_messages m ON m.session_id = s.id "
                    "WHERE s.created_at >= NOW() - interval '30 days'"
                )
            )
        ).fetchone()
        escalations = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM chat_events "
                    "WHERE event_type = 'escalated' AND created_at >= NOW() - interval '30 days'"
                )
            )
        ).scalar()
        top_topics = (
            await session.execute(
                text(
                    "SELECT topic, SUM(message_count) AS n FROM conversation_topics "
                    "WHERE last_seen_at >= NOW() - interval '30 days' "
                    "GROUP BY topic ORDER BY n DESC LIMIT 8"
                )
            )
        ).fetchall()
        org_usage = (
            await session.execute(
                text(
                    "SELECT COUNT(DISTINCT organization_id) AS orgs FROM copilot_sessions "
                    "WHERE created_at >= NOW() - interval '30 days'"
                )
            )
        ).scalar()
        daily_insights = (
            await session.execute(
                text(
                    "SELECT date, SUM(metric_value) FILTER (WHERE metric_key = 'messages') AS msgs, "
                    "AVG(metric_value) FILTER (WHERE metric_key = 'resolution_rate') AS reso "
                    "FROM conversation_insights "
                    "WHERE date >= CURRENT_DATE - 7 GROUP BY date ORDER BY date DESC LIMIT 7"
                )
            )
        ).fetchall()
    finally:
        await session.close()
    sessions = int(global_funnel.sessions or 0)
    messages = int(global_funnel.messages or 0)
    return {
        "sessions_30d": sessions,
        "messages_30d": messages,
        "messages_per_session": round(messages / sessions, 1) if sessions else 0.0,
        "organizations_using": int(org_usage or 0),
        "escalations_30d": int(escalations or 0),
        "top_topics": [{"topic": r.topic, "message_count": int(r.n)} for r in top_topics],
        "daily_trend": [
            {"date": r.date.isoformat(), "messages": int(r.msgs or 0), "resolution_rate": round(float(r.reso or 0), 1)}
            for r in daily_insights
        ],
    }
