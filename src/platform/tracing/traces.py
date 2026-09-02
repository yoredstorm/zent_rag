# =============================================================================
# AI Observability Traces & Spans v2 — trazado distribuido de runs, búsqueda,
# comparación side-by-side y correlación con usage/billing.
# =============================================================================
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Registro
# ---------------------------------------------------------------------------
async def record_trace(
    *,
    organization_id: UUID,
    trace_id: str,
    status: str,
    model: str | None,
    input_text: str,
    output_text: str,
    error: str | None,
    total_latency_ms: float,
    total_tokens: int,
    cost: float,
    spans: list[dict],
    agent_id: UUID | None = None,
    deployment_id: UUID | None = None,
    run_id: UUID | None = None,
) -> None:
    try:
        session = await get_async_session()
        try:
            started_at = datetime.now(timezone.utc) - timedelta(
                milliseconds=float(total_latency_ms)
            )
            await session.execute(
                text(
                    "INSERT INTO traces (id, organization_id, agent_id, deployment_id, "
                    "run_id, trace_id, status, model, input, output, error, "
                    "total_latency_ms, total_tokens, cost, started_at, completed_at) "
                    "VALUES (gen_random_uuid(), :oid, :aid, :did, :rid, :tid, :status, "
                    ":model, :input, :output, :error, :lat, :tokens, :cost, "
                    ":started, NOW()) "
                    "ON CONFLICT (trace_id) DO NOTHING"
                ),
                {
                    "oid": organization_id,
                    "aid": agent_id,
                    "did": deployment_id,
                    "rid": run_id,
                    "tid": trace_id[:64],
                    "status": status[:20],
                    "model": (model or "")[:120],
                    "input": input_text[:20000],
                    "output": output_text[:20000],
                    "error": (error or "")[:2000],
                    "lat": round(total_latency_ms, 2),
                    "tokens": int(total_tokens),
                    "cost": round(cost, 8),
                    "started": started_at,
                },
            )
            for span in spans[:100]:
                await session.execute(
                    text(
                        "INSERT INTO trace_spans (id, trace_id, parent_span_id, stage, "
                        "name, status, started_ms, duration_ms, tokens, metadata) "
                        "VALUES (gen_random_uuid(), :tid, :parent, :stage, :name, "
                        ":status, :start, :dur, :tokens, :meta)"
                    ),
                    {
                        "tid": trace_id[:64],
                        "parent": span.get("parent_span_id"),
                        "stage": span.get("stage", "total")[:30],
                        "name": span.get("name", "")[:200],
                        "status": span.get("status", "ok")[:20],
                        "start": float(span.get("started_ms", 0)),
                        "dur": round(float(span.get("duration_ms", 0)), 2),
                        "tokens": int(span.get("tokens", 0)),
                        "meta": json.dumps(span.get("metadata", {})),
                    },
                )
            await session.commit()
        finally:
            await session.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Trace record failed", error=str(exc)[:150])


# ---------------------------------------------------------------------------
# Búsqueda / exploración
# ---------------------------------------------------------------------------
async def list_traces(
    organization_id: UUID | None = None,
    *,
    agent_id: UUID | None = None,
    deployment_id: UUID | None = None,
    status: str | None = None,
    model: str | None = None,
    q: str | None = None,
    hours: int = 168,
    limit: int = 100,
) -> dict:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    session = await get_async_session()
    try:
        where = ["created_at >= :since"]
        params: dict = {"since": since, "limit": limit}
        if organization_id:
            where.append("organization_id = :oid")
            params["oid"] = organization_id
        if agent_id:
            where.append("agent_id = :aid")
            params["aid"] = agent_id
        if deployment_id:
            where.append("deployment_id = :did")
            params["did"] = deployment_id
        if status:
            where.append("status = :status")
            params["status"] = status
        if model:
            where.append("model = :model")
            params["model"] = model
        if q:
            where.append("(input ILIKE :q OR output ILIKE :q)")
            params["q"] = f"%{q[:200]}%"
        rows = (
            await session.execute(
                text(
                    "SELECT id, organization_id, agent_id, deployment_id, trace_id, "
                    "status, model, input, total_latency_ms, total_tokens, cost, "
                    "started_at, completed_at FROM traces WHERE "
                    + " AND ".join(where)
                    + " ORDER BY started_at DESC LIMIT :limit"
                ),
                params,
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "traces": [
            {
                "id": str(r.id),
                "organization_id": str(r.organization_id),
                "agent_id": str(r.agent_id) if r.agent_id else None,
                "deployment_id": str(r.deployment_id) if r.deployment_id else None,
                "trace_id": r.trace_id,
                "status": r.status,
                "model": r.model,
                "input": (r.input or "")[:200],
                "total_latency_ms": round(float(r.total_latency_ms), 1),
                "total_tokens": int(r.total_tokens),
                "cost": round(float(r.cost), 6),
                "started_at": r.started_at.isoformat(),
                "completed_at": r.completed_at.isoformat(),
            }
            for r in rows
        ],
        "count": len(rows),
    }


async def get_trace(trace_id: str) -> dict | None:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT id, organization_id, agent_id, deployment_id, run_id, "
                    "trace_id, status, model, input, output, error, total_latency_ms, "
                    "total_tokens, cost, started_at, completed_at "
                    "FROM traces WHERE trace_id = :tid"
                ),
                {"tid": trace_id[:64]},
            )
        ).fetchone()
        if row is None:
            return None
        spans = (
            await session.execute(
                text(
                    "SELECT id, parent_span_id, stage, name, status, started_ms, "
                    "duration_ms, tokens, metadata FROM trace_spans "
                    "WHERE trace_id = :tid ORDER BY started_ms"
                ),
                {"tid": trace_id[:64]},
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "id": str(row.id),
        "organization_id": str(row.organization_id),
        "agent_id": str(row.agent_id) if row.agent_id else None,
        "deployment_id": str(row.deployment_id) if row.deployment_id else None,
        "run_id": str(row.run_id) if row.run_id else None,
        "trace_id": row.trace_id,
        "status": row.status,
        "model": row.model,
        "input": row.input,
        "output": row.output,
        "error": row.error,
        "total_latency_ms": round(float(row.total_latency_ms), 1),
        "total_tokens": int(row.total_tokens),
        "cost": round(float(row.cost), 6),
        "started_at": row.started_at.isoformat(),
        "completed_at": row.completed_at.isoformat(),
        "spans": [
            {
                "id": str(s.id),
                "parent_span_id": str(s.parent_span_id) if s.parent_span_id else None,
                "stage": s.stage,
                "name": s.name,
                "status": s.status,
                "started_ms": round(float(s.started_ms), 1),
                "duration_ms": round(float(s.duration_ms), 1),
                "tokens": int(s.tokens),
                "metadata": s.metadata,
            }
            for s in spans
        ],
    }


# ---------------------------------------------------------------------------
# Comparación side-by-side
# ---------------------------------------------------------------------------
async def compare_traces(trace_a: str, trace_b: str) -> dict | None:
    a = await get_trace(trace_a)
    b = await get_trace(trace_b)
    if a is None or b is None:
        return None
    stages_a = {s["stage"]: s for s in a["spans"]}
    stages_b = {s["stage"]: s for s in b["spans"]}
    stages = sorted(set(stages_a) | set(stages_b))
    spans_diff = []
    for stage in stages:
        sa = stages_a.get(stage)
        sb = stages_b.get(stage)
        spans_diff.append(
            {
                "stage": stage,
                "a_duration_ms": round(sa["duration_ms"], 1) if sa else None,
                "b_duration_ms": round(sb["duration_ms"], 1) if sb else None,
                "a_tokens": sa["tokens"] if sa else None,
                "b_tokens": sb["tokens"] if sb else None,
            }
        )
    return {
        "same_input": (a["input"] or "").strip() == (b["input"] or "").strip(),
        "a": {
            "trace_id": a["trace_id"],
            "status": a["status"],
            "model": a["model"],
            "latency_ms": a["total_latency_ms"],
            "tokens": a["total_tokens"],
            "cost": a["cost"],
            "spans_count": len(a["spans"]),
            "error": a["error"],
        },
        "b": {
            "trace_id": b["trace_id"],
            "status": b["status"],
            "model": b["model"],
            "latency_ms": b["total_latency_ms"],
            "tokens": b["total_tokens"],
            "cost": b["cost"],
            "spans_count": len(b["spans"]),
            "error": b["error"],
        },
        "deltas": {
            "latency_ms": round(b["total_latency_ms"] - a["total_latency_ms"], 1),
            "tokens": b["total_tokens"] - a["total_tokens"],
            "cost": round(b["cost"] - a["cost"], 6),
            "spans_count": len(b["spans"]) - len(a["spans"]),
        },
        "spans_diff": spans_diff,
        "output_a": (a["output"] or "")[:2000],
        "output_b": (b["output"] or "")[:2000],
    }


# ---------------------------------------------------------------------------
# Correlación con usage/billing
# ---------------------------------------------------------------------------
async def trace_usage(trace_id: str) -> dict:
    session = await get_async_session()
    try:
        usage = (
            await session.execute(
                text(
                    "SELECT id, event_type, agent_id, model, total_tokens, latency_ms, "
                    "status, estimated_cost, actual_cost, created_at "
                    "FROM usage_events WHERE trace_id = :tid ORDER BY created_at LIMIT 20"
                ),
                {"tid": trace_id[:64]},
            )
        ).fetchall()
        api_logs = (
            await session.execute(
                text(
                    "SELECT id, endpoint, method, status, latency_ms, tokens, cost, "
                    "created_at FROM api_logs WHERE trace_id = :tid ORDER BY created_at LIMIT 20"
                ),
                {"tid": trace_id[:64]},
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "trace_id": trace_id,
        "usage_events": [
            {
                "id": str(r.id),
                "event_type": r.event_type,
                "agent_id": str(r.agent_id) if r.agent_id else None,
                "model": r.model,
                "total_tokens": int(r.total_tokens or 0),
                "latency_ms": round(float(r.latency_ms or 0), 1),
                "status": r.status,
                "cost": round(float(r.actual_cost or r.estimated_cost or 0), 6),
                "created_at": r.created_at.isoformat(),
            }
            for r in usage
        ],
        "api_logs": [
            {
                "id": str(r.id),
                "endpoint": r.endpoint,
                "method": r.method,
                "status": r.status,
                "latency_ms": round(float(r.latency_ms or 0), 1),
                "tokens": int(r.tokens or 0),
                "cost": r.cost,
                "created_at": r.created_at.isoformat(),
            }
            for r in api_logs
        ],
    }


# ---------------------------------------------------------------------------
# Agregados por etapa
# ---------------------------------------------------------------------------
async def stages_dashboard(hours: int = 24) -> dict:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT stage, COUNT(*) AS total, "
                    "AVG(duration_ms) AS avg_duration_ms, "
                    "PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95, "
                    "SUM(tokens) AS tokens, "
                    "COUNT(*) FILTER (WHERE status <> 'ok') AS errors "
                    "FROM trace_spans WHERE created_at >= :since "
                    "GROUP BY stage ORDER BY avg_duration_ms DESC"
                ),
                {"since": since},
            )
        ).fetchall()
        traces_count = (
            await session.execute(
                text("SELECT COUNT(*) FROM traces WHERE created_at >= :since"),
                {"since": since},
            )
        ).scalar()
    finally:
        await session.close()
    return {
        "window_hours": hours,
        "traces": int(traces_count),
        "stages": [
            {
                "stage": r.stage,
                "spans": int(r.total),
                "avg_duration_ms": round(float(r.avg_duration_ms), 1),
                "p95_duration_ms": round(float(r.p95), 1),
                "tokens": int(r.tokens),
                "errors": int(r.errors),
                "error_rate": round(int(r.errors) / int(r.total), 3) if int(r.total) else 0.0,
            }
            for r in rows
        ],
    }
