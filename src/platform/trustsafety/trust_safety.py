# =============================================================================
# AI Trust & Safety Center — AUP con términos versionados y consentimiento,
# moderación de contenido con puntuación (block/warn) y panel de incidentes.
# =============================================================================
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# AUP (Política de Uso Aceptable)
# ---------------------------------------------------------------------------
async def get_terms() -> dict:
    session = await get_async_session()
    try:
        latest = (
            await session.execute(
                text(
                    "SELECT id, version, title, content, effective_at "
                    "FROM aup_terms ORDER BY version DESC LIMIT 1"
                )
            )
        ).fetchone()
        all_terms = (
            await session.execute(
                text("SELECT version, title, effective_at FROM aup_terms ORDER BY version")
            )
        ).fetchall()
    finally:
        await session.close()
    if latest is None:
        return {"latest": None, "versions": []}
    return {
        "latest": {
            "version": int(latest.version),
            "title": latest.title,
            "content": latest.content,
            "effective_at": latest.effective_at.isoformat(),
        },
        "versions": [
            {"version": int(r.version), "title": r.title, "effective_at": r.effective_at.isoformat()}
            for r in all_terms
        ],
    }


async def accept_terms(organization_id: UUID, terms_version: int, consented_by: UUID | None = None) -> dict:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO aup_consents (id, organization_id, terms_version, "
                    "consented_by, consented_at) "
                    "VALUES (gen_random_uuid(), :oid, :v, :by, NOW()) "
                    "ON CONFLICT (organization_id) DO UPDATE SET "
                    "terms_version = EXCLUDED.terms_version, "
                    "consented_by = EXCLUDED.consented_by, "
                    "consented_at = NOW() "
                    "RETURNING organization_id, terms_version, consented_at"
                ),
                {"oid": organization_id, "v": terms_version, "by": consented_by},
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    return {
        "organization_id": str(row.organization_id),
        "terms_version": int(row.terms_version),
        "consented_at": row.consented_at.isoformat(),
    }


async def consent_status(organization_id: UUID) -> dict:
    session = await get_async_session()
    try:
        consent = (
            await session.execute(
                text(
                    "SELECT terms_version, consented_at, consented_by "
                    "FROM aup_consents WHERE organization_id = :oid"
                ),
                {"oid": organization_id},
            )
        ).fetchone()
    finally:
        await session.close()
    latest = (await get_terms())["latest"]
    if consent is None or latest is None:
        return {
            "accepted": False,
            "latest_version": int(latest["version"]) if latest else None,
            "consented_version": None,
            "consented_at": None,
            "outdated": False,
        }
    return {
        "accepted": True,
        "latest_version": int(latest["version"]),
        "consented_version": int(consent.terms_version),
        "consented_at": consent.consented_at.isoformat(),
        "outdated": int(consent.terms_version) < int(latest["version"]),
    }


async def list_consents() -> dict:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT c.organization_id, c.terms_version, c.consented_by, "
                    "c.consented_at FROM aup_consents c ORDER BY c.consented_at DESC"
                )
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "consents": [
            {
                "organization_id": str(r.organization_id),
                "terms_version": int(r.terms_version),
                "consented_by": str(r.consented_by) if r.consented_by else None,
                "consented_at": r.consented_at.isoformat(),
            }
            for r in rows
        ]
    }


# ---------------------------------------------------------------------------
# Moderación de contenido con puntuación
# ---------------------------------------------------------------------------
def _rule_score(patterns: list, text_value: str) -> float:
    lowered = text_value.lower()
    hits = 0
    for pattern in patterns:
        p = str(pattern)
        try:
            if re.search(p, lowered):
                hits += 1
        except re.error:
            if p.lower() in lowered:
                hits += 1
    if not patterns:
        return 0.0
    return min(hits / len(patterns), 1.0)


async def list_moderation_rules(organization_id: UUID | None = None) -> dict:
    session = await get_async_session()
    try:
        params: dict = {}
        where = ""
        if organization_id:
            where = " WHERE organization_id = :oid OR organization_id IS NULL"
            params["oid"] = organization_id
        rows = (
            await session.execute(
                text(
                    "SELECT id, organization_id, name, category, patterns, min_score, "
                    "action, enabled, created_at FROM content_moderation_rules"
                    + where
                    + " ORDER BY organization_id NULLS FIRST, created_at"
                ),
                params,
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "rules": [
            {
                "id": str(r.id),
                "organization_id": str(r.organization_id) if r.organization_id else None,
                "name": r.name,
                "category": r.category,
                "patterns": r.patterns,
                "min_score": float(r.min_score),
                "action": r.action,
                "enabled": bool(r.enabled),
            }
            for r in rows
        ]
    }


async def create_moderation_rule(
    name: str,
    category: str,
    patterns: list,
    min_score: float = 0.6,
    action: str = "block",
    organization_id: UUID | None = None,
) -> dict:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO content_moderation_rules (id, organization_id, name, "
                    "category, patterns, min_score, action) "
                    "VALUES (gen_random_uuid(), :oid, :name, :cat, :patterns, :ms, :action) "
                    "RETURNING id, name, category, min_score, action"
                ),
                {
                    "oid": organization_id,
                    "name": name[:120],
                    "cat": category[:40],
                    "patterns": __import__("json").dumps(patterns or []),
                    "ms": min_score,
                    "action": action[:10],
                },
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    return {
        "id": str(row.id),
        "name": row.name,
        "category": row.category,
        "min_score": float(row.min_score),
        "action": row.action,
    }


async def toggle_moderation_rule(rule_id: UUID, enabled: bool) -> bool:
    session = await get_async_session()
    try:
        result = await session.execute(
            text("UPDATE content_moderation_rules SET enabled = :e WHERE id = :rid"),
            {"e": enabled, "rid": rule_id},
        )
        await session.commit()
        return result.rowcount > 0
    finally:
        await session.close()


async def delete_moderation_rule(rule_id: UUID) -> bool:
    session = await get_async_session()
    try:
        result = await session.execute(
            text("DELETE FROM content_moderation_rules WHERE id = :rid"),
            {"rid": rule_id},
        )
        await session.commit()
        return result.rowcount > 0
    finally:
        await session.close()


async def _create_incident(
    organization_id: UUID,
    direction: str,
    rule_id: UUID | None,
    rule_name: str,
    score: float,
    snippet: str,
    action: str,
) -> UUID:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO safety_incidents (id, organization_id, direction, "
                    "rule_id, rule_name, score, snippet, action) "
                    "VALUES (gen_random_uuid(), :oid, :dir, :rid, :rname, :score, "
                    ":snippet, :action) RETURNING id"
                ),
                {
                    "oid": organization_id,
                    "dir": direction[:10],
                    "rid": rule_id,
                    "rname": rule_name[:120],
                    "score": round(score, 4),
                    "snippet": snippet[:300],
                    "action": action[:10],
                },
            )
        ).fetchone()
        await session.commit()
        return row.id
    finally:
        await session.close()


async def moderate_text(
    organization_id: UUID,
    text_value: str,
    direction: str = "input",
) -> dict:
    """Aplica las reglas habilitadas (globales + de la org) y registra
    incidentes. Devuelve {blocked, warnings, incidents}."""
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id, name, category, patterns, min_score, action "
                    "FROM content_moderation_rules WHERE enabled "
                    "AND (organization_id IS NULL OR organization_id = :oid) "
                    "ORDER BY organization_id NULLS FIRST"
                ),
                {"oid": organization_id},
            )
        ).fetchall()
    finally:
        await session.close()
    blocked = False
    warnings: list[dict] = []
    incidents: list[str] = []
    for row in rows:
        score = _rule_score(row.patterns or [], text_value)
        if score < float(row.min_score):
            continue
        violation = {
            "rule_id": str(row.id),
            "rule_name": row.name,
            "category": row.category,
            "score": round(score, 3),
            "action": row.action,
        }
        incident_id = await _create_incident(
            organization_id,
            direction,
            row.id,
            row.name,
            score,
            text_value,
            row.action,
        )
        incidents.append(str(incident_id))
        if row.action == "block":
            blocked = True
        else:
            warnings.append(violation)
    return {"blocked": blocked, "warnings": warnings, "incidents": incidents}


# ---------------------------------------------------------------------------
# Panel de incidentes
# ---------------------------------------------------------------------------
async def list_incidents(
    organization_id: UUID | None = None,
    status: str | None = None,
    direction: str | None = None,
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
        if status:
            where.append("status = :status")
            params["status"] = status
        if direction:
            where.append("direction = :direction")
            params["direction"] = direction
        rows = (
            await session.execute(
                text(
                    "SELECT id, organization_id, direction, rule_id, rule_name, score, "
                    "snippet, action, status, resolved_by, resolved_at, resolution_note, "
                    "created_at FROM safety_incidents WHERE "
                    + " AND ".join(where)
                    + " ORDER BY created_at DESC LIMIT :limit"
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
                "direction": r.direction,
                "rule_id": str(r.rule_id) if r.rule_id else None,
                "rule_name": r.rule_name,
                "score": round(float(r.score), 3),
                "snippet": r.snippet,
                "action": r.action,
                "status": r.status,
                "resolved_by": str(r.resolved_by) if r.resolved_by else None,
                "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
                "resolution_note": r.resolution_note,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
        "count": len(rows),
    }


async def resolve_incident(incident_id: UUID, note: str, resolved_by: UUID | None = None) -> bool:
    session = await get_async_session()
    try:
        result = await session.execute(
            text(
                "UPDATE safety_incidents SET status = 'resolved', resolved_by = :by, "
                "resolved_at = NOW(), resolution_note = :note "
                "WHERE id = :iid AND status = 'open'"
            ),
            {"by": resolved_by, "note": note[:500], "iid": incident_id},
        )
        await session.commit()
        return result.rowcount > 0
    finally:
        await session.close()


async def dismiss_incident(incident_id: UUID, note: str | None = None) -> bool:
    session = await get_async_session()
    try:
        result = await session.execute(
            text(
                "UPDATE safety_incidents SET status = 'dismissed', "
                "resolution_note = COALESCE(:note, resolution_note), resolved_at = NOW() "
                "WHERE id = :iid AND status = 'open'"
            ),
            {"note": (note or "")[:500], "iid": incident_id},
        )
        await session.commit()
        return result.rowcount > 0
    finally:
        await session.close()


# ---------------------------------------------------------------------------
# Dashboard de confianza
# ---------------------------------------------------------------------------
async def trust_dashboard(hours: int = 24) -> dict:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    session = await get_async_session()
    try:
        by_rule = (
            await session.execute(
                text(
                    "SELECT rule_name, direction, action, "
                    "COUNT(*) AS total, "
                    "COUNT(*) FILTER (WHERE status = 'resolved') AS resolved, "
                    "COUNT(*) FILTER (WHERE status = 'dismissed') AS dismissed, "
                    "AVG(score) AS avg_score "
                    "FROM safety_incidents WHERE created_at >= :since "
                    "GROUP BY rule_name, direction, action ORDER BY total DESC"
                ),
                {"since": since},
            )
        ).fetchall()
        queries = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM usage_events WHERE created_at >= :since"
                ),
                {"since": since},
            )
        ).scalar()
        totals = (
            await session.execute(
                text(
                    "SELECT "
                    "COUNT(*) FILTER (WHERE action = 'block') AS blocked, "
                    "COUNT(*) FILTER (WHERE action = 'warn') AS warned, "
                    "COUNT(*) FILTER (WHERE direction = 'input') AS inputs, "
                    "COUNT(*) FILTER (WHERE direction = 'output') AS outputs "
                    "FROM safety_incidents WHERE created_at >= :since"
                ),
                {"since": since},
            )
        ).fetchone()
    finally:
        await session.close()
    rules = [
        {
            "rule_name": r.rule_name,
            "direction": r.direction,
            "action": r.action,
            "total": int(r.total),
            "resolved": int(r.resolved),
            "dismissed": int(r.dismissed),
            "resolution_rate": round(int(r.resolved) / int(r.total), 3) if int(r.total) else 0.0,
            "avg_score": round(float(r.avg_score), 3),
        }
        for r in by_rule
    ]
    blocked = int(totals.blocked)
    return {
        "window_hours": hours,
        "queries": int(queries),
        "blocked": blocked,
        "warned": int(totals.warned),
        "inputs": int(totals.inputs),
        "outputs": int(totals.outputs),
        "block_rate": round(blocked / int(queries), 4) if int(queries) else 0.0,
        "by_rule": rules,
        "count": len(rules),
    }
