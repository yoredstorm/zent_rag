# =============================================================================
# Sentiment & Feedback Analytics — feedback por run, CSAT/NPS por agente,
# causas del feedback negativo y tendencias.
# =============================================================================
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

REASONS = ("wrong_answer", "too_long", "too_slow", "confusing", "other")


# ---------------------------------------------------------------------------
# Recolección
# ---------------------------------------------------------------------------
async def submit_feedback(
    organization_id: UUID,
    rating: str,
    *,
    agent_id: UUID | None = None,
    deployment_id: UUID | None = None,
    run_id: UUID | None = None,
    trace_id: str | None = None,
    reason: str | None = None,
    comment: str | None = None,
) -> dict:
    if rating not in ("up", "down"):
        raise ValueError("rating must be up|down")
    if reason and reason not in REASONS:
        raise ValueError(f"reason must be one of {REASONS}")
    session = await get_async_session()
    try:
        if run_id is not None:
            existing = (
                await session.execute(
                    text(
                        "SELECT id FROM feedback WHERE run_id = :rid AND "
                        "organization_id = :oid"
                    ),
                    {"rid": run_id, "oid": organization_id},
                )
            ).fetchone()
            if existing is not None:
                await session.execute(
                    text(
                        "UPDATE feedback SET rating = :rating, reason = :reason, "
                        "comment = COALESCE(:comment, comment), updated_at = NOW() "
                        "WHERE id = :fid"
                    ),
                    {
                        "rating": rating,
                        "reason": reason,
                        "comment": comment,
                        "fid": existing.id,
                    },
                )
                await session.commit()
                return {"status": "updated", "rating": rating}
        await session.execute(
            text(
                "INSERT INTO feedback (id, organization_id, agent_id, deployment_id, "
                "run_id, trace_id, rating, reason, comment) "
                "VALUES (gen_random_uuid(), :oid, :aid, :did, :rid, :tid, :rating, "
                ":reason, :comment)"
            ),
            {
                "oid": organization_id,
                "aid": agent_id,
                "did": deployment_id,
                "rid": run_id,
                "tid": (trace_id or "")[:64] or None,
                "rating": rating,
                "reason": reason,
                "comment": comment,
            },
        )
        await session.commit()
    finally:
        await session.close()
    return {"status": "created", "rating": rating}


# ---------------------------------------------------------------------------
# Analytics por agente
# ---------------------------------------------------------------------------
async def _analytics_rows(
    organization_id: UUID | None, agent_id: UUID | None, since: datetime
) -> list:
    session = await get_async_session()
    try:
        where = ["created_at >= :since"]
        params: dict = {"since": since}
        if organization_id:
            where.append("organization_id = :oid")
            params["oid"] = organization_id
        if agent_id:
            where.append("agent_id = :aid")
            params["aid"] = agent_id
        rows = (
            await session.execute(
                text(
                    "SELECT COALESCE(agent_id::text, 'sin-agente') AS agent_id, "
                    "COUNT(*) AS total, "
                    "COUNT(*) FILTER (WHERE rating = 'up') AS ups, "
                    "COUNT(*) FILTER (WHERE rating = 'down') AS downs "
                    "FROM feedback WHERE "
                    + " AND ".join(where)
                    + " GROUP BY agent_id ORDER BY total DESC"
                ),
                params,
            )
        ).fetchall()
    finally:
        await session.close()
    return rows


async def analytics(
    organization_id: UUID | None = None,
    agent_id: UUID | None = None,
    hours: int = 168,
) -> dict:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = await _analytics_rows(organization_id, agent_id, since)
    agents = []
    total_up = total_down = 0
    for r in rows:
        ups, downs = int(r.ups), int(r.downs)
        total_up += ups
        total_down += downs
        total = ups + downs
        agents.append(
            {
                "agent_id": r.agent_id if r.agent_id != "sin-agente" else None,
                "total": total,
                "ups": ups,
                "downs": downs,
                "csat": round(ups / total, 4) if total else 0.0,
                "nps": round((ups - downs) / total * 100, 1) if total else 0.0,
            }
        )
    grand = total_up + total_down
    return {
        "window_hours": hours,
        "total_feedback": grand,
        "csat": round(total_up / grand, 4) if grand else 0.0,
        "nps": round((total_up - total_down) / grand * 100, 1) if grand else 0.0,
        "by_agent": agents,
    }


# ---------------------------------------------------------------------------
# Causas del feedback negativo + correlación con traces
# ---------------------------------------------------------------------------
async def negative_breakdown(
    organization_id: UUID | None = None, hours: int = 168
) -> dict:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    session = await get_async_session()
    try:
        params: dict = {"since": since}
        where = "WHERE f.created_at >= :since AND f.rating = 'down'"
        if organization_id:
            where += " AND f.organization_id = :oid"
            params["oid"] = organization_id
        by_reason = (
            await session.execute(
                text(
                    "SELECT COALESCE(f.reason, 'other') AS reason, COUNT(*) AS total "
                    "FROM feedback f " + where + " GROUP BY reason ORDER BY total DESC"
                ),
                params,
            )
        ).fetchall()
        # Correlación con trazas: latencia/tokens promedio de runs con down.
        correlation = (
            await session.execute(
                text(
                    "SELECT COUNT(*) AS total, "
                    "AVG(t.total_latency_ms) FILTER (WHERE t.total_latency_ms IS NOT NULL) AS avg_latency, "
                    "AVG(t.total_tokens) FILTER (WHERE t.total_tokens IS NOT NULL) AS avg_tokens, "
                    "MAX(t.total_latency_ms) AS max_latency "
                    "FROM feedback f LEFT JOIN traces t ON t.trace_id = f.trace_id "
                    "WHERE f.created_at >= :since AND f.rating = 'down'"
                    + (" AND f.organization_id = :oid" if organization_id else "")
                ),
                {"since": since, **({"oid": organization_id} if organization_id else {})},
            )
        ).fetchone()
        # Contexto de la respuesta: longitud del output en trazas con down.
        length = (
            await session.execute(
                text(
                    "SELECT AVG(LENGTH(t.output)) AS avg_output_len FROM feedback f "
                    "JOIN traces t ON t.trace_id = f.trace_id "
                    "WHERE f.created_at >= :since AND f.rating = 'down'"
                    + (" AND f.organization_id = :oid" if organization_id else "")
                ),
                {"since": since, **({"oid": organization_id} if organization_id else {})},
            )
        ).fetchone()
    finally:
        await session.close()
    total = int(correlation.total or 0)
    return {
        "window_hours": hours,
        "total_negative": total,
        "by_reason": [
            {"reason": r.reason, "total": int(r.total),
             "pct": round(int(r.total) / total, 3) if total else 0.0}
            for r in by_reason
        ],
        "correlation": {
            "avg_latency_ms": round(float(correlation.avg_latency), 1)
            if correlation.avg_latency is not None else None,
            "avg_tokens": round(float(correlation.avg_tokens), 1)
            if correlation.avg_tokens is not None else None,
            "max_latency_ms": round(float(correlation.max_latency), 1)
            if correlation.max_latency is not None else None,
            "avg_output_length": round(float(length.avg_output_len), 1)
            if length.avg_output_len is not None else None,
        },
    }


# ---------------------------------------------------------------------------
# Tendencias
# ---------------------------------------------------------------------------
async def trends(organization_id: UUID | None = None, days: int = 14) -> dict:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    session = await get_async_session()
    try:
        params: dict = {"since": since}
        where = "WHERE created_at >= :since"
        if organization_id:
            where += " AND organization_id = :oid"
            params["oid"] = organization_id
        rows = (
            await session.execute(
                text(
                    "SELECT date_trunc('day', created_at) AS day, "
                    "COUNT(*) FILTER (WHERE rating = 'up') AS ups, "
                    "COUNT(*) FILTER (WHERE rating = 'down') AS downs "
                    "FROM feedback " + where + " GROUP BY day ORDER BY day"
                ),
                params,
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "days": days,
        "series": [
            {
                "day": r.day.strftime("%Y-%m-%d"),
                "ups": int(r.ups),
                "downs": int(r.downs),
                "csat": round(int(r.ups) / (int(r.ups) + int(r.downs)), 3)
                if (int(r.ups) + int(r.downs)) else None,
            }
            for r in rows
        ],
    }
