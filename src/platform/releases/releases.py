# =============================================================================
# AI Agent Versioning & Rollout v2 — historial con diff, canales canary/
# stable, promoción gradual con health-gate y rollbacks.
# =============================================================================
from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

HEALTH_GATE_MIN = 70.0


# ---------------------------------------------------------------------------
# Historial de versiones + diff
# ---------------------------------------------------------------------------
async def list_versions(agent_id: UUID) -> dict:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id, version_number, status, notes, created_at "
                    "FROM agent_versions WHERE agent_id = :aid "
                    "ORDER BY version_number DESC"
                ),
                {"aid": agent_id},
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "versions": [
            {
                "id": str(r.id),
                "version_number": int(r.version_number or 0),
                "status": r.status,
                "notes": r.notes,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
    }


def _diff_config(a: dict, b: dict) -> list[dict]:
    changes: list[dict] = []
    keys = set(a) | set(b)
    for key in sorted(keys):
        if key in a and key not in b:
            changes.append({"key": key, "kind": "removed", "a": a[key], "b": None})
        elif key in b and key not in a:
            changes.append({"key": key, "kind": "added", "a": None, "b": b[key]})
        elif json.dumps(a.get(key), default=str) != json.dumps(b.get(key), default=str):
            changes.append({"key": key, "kind": "changed", "a": a.get(key), "b": b.get(key)})
    return changes


async def diff_versions(agent_id: UUID, version_a: UUID, version_b: UUID) -> dict | None:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id, version_number, config_snapshot, notes, created_at "
                    "FROM agent_versions WHERE agent_id = :aid AND id IN (:a, :b)"
                ),
                {"aid": agent_id, "a": version_a, "b": version_b},
            )
        ).fetchall()
    finally:
        await session.close()
    if len(rows) != 2:
        return None
    by_id = {r.id: r for r in rows}
    va = by_id[version_a]
    vb = by_id[version_b]
    config_a = va.config_snapshot or {}
    config_b = vb.config_snapshot or {}
    config_diff = _diff_config(config_a, config_b)
    prompt_a = str(config_a.get("system_prompt") or "")
    prompt_b = str(config_b.get("system_prompt") or "")
    prompt_diff = {
        "a": prompt_a,
        "b": prompt_b,
        "changed": prompt_a != prompt_b,
        "a_chars": len(prompt_a),
        "b_chars": len(prompt_b),
    }
    model_changed = config_a.get("model") != config_b.get("model")
    tools_changed = json.dumps(config_a.get("tools", []), default=str) != json.dumps(
        config_b.get("tools", []), default=str
    )
    return {
        "version_a": {"id": str(va.id), "number": int(va.version_number or 0)},
        "version_b": {"id": str(vb.id), "number": int(vb.version_number or 0)},
        "config_diff": config_diff,
        "prompt_diff": prompt_diff,
        "model_changed": model_changed,
        "tools_changed": tools_changed,
    }


# ---------------------------------------------------------------------------
# Releases
# ---------------------------------------------------------------------------
async def _append_event(release_id: UUID, event_type: str, detail: str) -> None:
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO release_events (id, release_id, event_type, detail) "
                "VALUES (gen_random_uuid(), :rid, :etype, :detail)"
            ),
            {"rid": release_id, "etype": event_type[:30], "detail": detail},
        )
        await session.commit()
    finally:
        await session.close()


async def start_release(
    agent_id: UUID,
    version_id: UUID,
    channel: str = "canary",
    traffic_pct: int = 100,
    notes: str | None = None,
) -> dict:
    if channel not in ("canary", "stable"):
        raise ValueError("channel must be canary|stable")
    traffic = max(0, min(int(traffic_pct), 100))
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO agent_releases (id, agent_id, version_id, channel, "
                    "traffic_pct, status, notes) "
                    "VALUES (gen_random_uuid(), :aid, :vid, :channel, :traffic, "
                    "'running', :notes) RETURNING id, channel"
                ),
                {
                    "aid": agent_id,
                    "vid": version_id,
                    "channel": channel,
                    "traffic": traffic,
                    "notes": notes,
                },
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    await _append_event(
        row.id,
        "started",
        f"Release {channel} iniciado con {traffic}% de tráfico",
    )
    return {"release_id": str(row.id), "channel": row.channel, "traffic_pct": traffic}


async def _release_row(release_id: UUID) -> tuple:
    session = await get_async_session()
    try:
        return (
            await session.execute(
                text(
                    "SELECT r.id, r.agent_id, r.version_id, r.channel, r.traffic_pct, "
                    "r.status, r.health_score, r.promoted_by, r.created_at, "
                    "r.promoted_at, r.rolled_back_at, r.notes, "
                    "v.version_number, a.name AS agent_name "
                    "FROM agent_releases r "
                    "JOIN agent_versions v ON v.id = r.version_id "
                    "JOIN agents a ON a.id = r.agent_id "
                    "WHERE r.id = :rid"
                ),
                {"rid": release_id},
            )
        ).fetchone()
    finally:
        await session.close()


async def health_check(release_id: UUID) -> dict:
    """Score 0-100 desde SLOs del deployment del agente y evals recientes."""
    row = await _release_row(release_id)
    if row is None:
        return None
    session = await get_async_session()
    try:
        # SLOs: latencia p95 y error rate del deployment activo del agente.
        slo = (
            await session.execute(
                text(
                    "SELECT COUNT(*) AS requests, "
                    "COALESCE(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms), 0) AS p95, "
                    "COUNT(*) FILTER (WHERE status <> 'completed') AS errors "
                    "FROM inference_logs WHERE agent_id = :aid "
                    "AND created_at >= NOW() - interval '6 hours'"
                ),
                {"aid": row.agent_id},
            )
        ).fetchone()
        eval_score = (
            await session.execute(
                text(
                    "SELECT COALESCE(AVG(score_overall), 0) FROM eval_v2_runs "
                    "WHERE agent_id = :aid AND status = 'completed' "
                    "AND completed_at >= NOW() - interval '7 days'"
                ),
                {"aid": row.agent_id},
            )
        ).scalar()
    finally:
        await session.close()

    requests = int(slo.requests or 0)
    error_rate = int(slo.errors or 0) / requests if requests else 0.0
    p95 = float(slo.p95 or 0)
    latency_score = max(0.0, 100 - (p95 - 500) / 50) if p95 > 500 else 100.0
    error_score = max(0.0, 100 - error_rate * 2000)
    eval_score_f = float(eval_score or 0)
    if requests == 0 and eval_score_f == 0:
        score = 100.0  # sin tráfico ni evals → asumir saludable
    elif requests == 0:
        score = eval_score_f
    else:
        score = latency_score * 0.4 + error_score * 0.4 + eval_score_f * 0.2
    score = round(max(0.0, min(score, 100.0)), 1)
    passed = score >= HEALTH_GATE_MIN
    await session.close() if False else None

    await _append_event(
        release_id,
        "health_ok" if passed else "health_fail",
        f"health_score={score} (p95={p95:.0f}ms, err={error_rate:.2%}, evals={eval_score_f:.0f})",
    )
    session2 = await get_async_session()
    try:
        await session2.execute(
            text("UPDATE agent_releases SET health_score = :score WHERE id = :rid"),
            {"score": score, "rid": release_id},
        )
        await session2.commit()
    finally:
        await session2.close()
    return {"release_id": str(release_id), "health_score": score, "passed_gate": passed}


async def _set_deployment_version(agent_id: UUID, version_id: UUID) -> int:
    """Actualiza los deployments del agente en producción a la versión."""
    session = await get_async_session()
    try:
        result = await session.execute(
            text(
                "UPDATE deployments SET agent_version_id = :vid "
                "WHERE agent_id = :aid AND status = 'healthy'"
            ),
            {"vid": version_id, "aid": agent_id},
        )
        await session.commit()
        return result.rowcount
    finally:
        await session.close()


async def promote(release_id: UUID, promoted_by: UUID | None = None) -> dict:
    row = await _release_row(release_id)
    if row is None:
        return None
    if row.status not in ("running", "paused"):
        return {"status": "not_promotable", "current": row.status}
    updated = await _set_deployment_version(row.agent_id, row.version_id)
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE agent_releases SET status = 'promoted', traffic_pct = 100, "
                "promoted_by = :by, promoted_at = NOW() WHERE id = :rid"
            ),
            {"by": promoted_by, "rid": release_id},
        )
        await session.commit()
    finally:
        await session.close()
    await _append_event(
        release_id,
        "promoted",
        f"Promovido a stable (100% tráfico) en {updated} deployment(s)",
    )
    return {"status": "promoted", "deployments_updated": updated}


async def rollback(release_id: UUID, detail: str | None = None) -> dict:
    """Revierte el deployment a la versión anterior (previa al release)."""
    row = await _release_row(release_id)
    if row is None:
        return None
    session = await get_async_session()
    try:
        previous = (
            await session.execute(
                text(
                    "SELECT id FROM agent_versions WHERE agent_id = :aid "
                    "AND version_number < :num ORDER BY version_number DESC LIMIT 1"
                ),
                {"aid": row.agent_id, "num": row.version_number},
            )
        ).fetchone()
        if previous is None:
            await session.commit()
            return {"status": "no_previous_version"}
        updated = await _set_deployment_version(row.agent_id, previous.id)
        await session.execute(
            text(
                "UPDATE agent_releases SET status = 'rolled_back', rolled_back_at = NOW() "
                "WHERE id = :rid"
            ),
            {"rid": release_id},
        )
        await session.commit()
    finally:
        await session.close()
    await _append_event(
        release_id,
        "rolled_back",
        f"Rollback a v{int(row.version_number) - 1} en {updated} deployment(s): {detail or ''}",
    )
    return {"status": "rolled_back", "deployments_updated": updated}


async def pause_release(release_id: UUID) -> dict:
    row = await _release_row(release_id)
    if row is None:
        return None
    session = await get_async_session()
    try:
        await session.execute(
            text("UPDATE agent_releases SET status = 'paused' WHERE id = :rid"),
            {"rid": release_id},
        )
        await session.commit()
    finally:
        await session.close()
    await _append_event(release_id, "paused", "Release pausado")
    return {"status": "paused"}


async def resume_release(release_id: UUID) -> dict:
    row = await _release_row(release_id)
    if row is None:
        return None
    session = await get_async_session()
    try:
        await session.execute(
            text("UPDATE agent_releases SET status = 'running' WHERE id = :rid"),
            {"rid": release_id},
        )
        await session.commit()
    finally:
        await session.close()
    await _append_event(release_id, "resumed", "Release reanudado")
    return {"status": "running"}


async def list_releases(agent_id: UUID | None = None) -> dict:
    session = await get_async_session()
    try:
        params: dict = {}
        where = ""
        if agent_id:
            where = " WHERE r.agent_id = :aid"
            params["aid"] = agent_id
        rows = (
            await session.execute(
                text(
                    "SELECT r.id, r.agent_id, r.version_id, r.channel, r.traffic_pct, "
                    "r.status, r.health_score, r.promoted_at, r.rolled_back_at, "
                    "r.created_at, v.version_number, a.name AS agent_name "
                    "FROM agent_releases r "
                    "JOIN agent_versions v ON v.id = r.version_id "
                    "JOIN agents a ON a.id = r.agent_id" + where + " "
                    "ORDER BY r.created_at DESC LIMIT 100"
                ),
                params,
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "releases": [
            {
                "id": str(r.id),
                "agent_id": str(r.agent_id),
                "agent_name": r.agent_name,
                "version_id": str(r.version_id),
                "version_number": int(r.version_number or 0),
                "channel": r.channel,
                "traffic_pct": int(r.traffic_pct),
                "status": r.status,
                "health_score": round(float(r.health_score), 1) if r.health_score is not None else None,
                "promoted_at": r.promoted_at.isoformat() if r.promoted_at else None,
                "rolled_back_at": r.rolled_back_at.isoformat() if r.rolled_back_at else None,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
    }


async def release_detail(release_id: UUID) -> dict | None:
    row = await _release_row(release_id)
    if row is None:
        return None
    session = await get_async_session()
    try:
        events = (
            await session.execute(
                text(
                    "SELECT id, event_type, detail, created_at FROM release_events "
                    "WHERE release_id = :rid ORDER BY created_at"
                ),
                {"rid": release_id},
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "id": str(row.id),
        "agent_id": str(row.agent_id),
        "agent_name": row.agent_name,
        "version_id": str(row.version_id),
        "version_number": int(row.version_number or 0),
        "channel": row.channel,
        "traffic_pct": int(row.traffic_pct),
        "status": row.status,
        "health_score": round(float(row.health_score), 1) if row.health_score is not None else None,
        "promoted_by": str(row.promoted_by) if row.promoted_by else None,
        "created_at": row.created_at.isoformat(),
        "promoted_at": row.promoted_at.isoformat() if row.promoted_at else None,
        "rolled_back_at": row.rolled_back_at.isoformat() if row.rolled_back_at else None,
        "notes": row.notes,
        "events": [
            {"id": str(e.id), "event_type": e.event_type, "detail": e.detail, "created_at": e.created_at.isoformat()}
            for e in events
        ],
    }


async def releases_dashboard() -> dict:
    data = await list_releases()
    by_agent: dict[str, dict] = {}
    for r in data["releases"]:
        entry = by_agent.setdefault(
            r["agent_id"],
            {
                "agent_id": r["agent_id"],
                "agent_name": r["agent_name"],
                "releases": 0,
                "canary": None,
                "stable": None,
                "last_status": None,
            },
        )
        entry["releases"] += 1
        entry["last_status"] = r["status"]
        if r["channel"] == "canary":
            entry["canary"] = {"version": r["version_number"], "status": r["status"], "health": r["health_score"]}
        else:
            entry["stable"] = {"version": r["version_number"], "status": r["status"], "health": r["health_score"]}
    return {"agents": list(by_agent.values()), "total_releases": len(data["releases"])}
