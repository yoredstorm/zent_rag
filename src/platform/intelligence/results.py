# =============================================================================
# Phase 32C — Business Results (resultados de negocio normalizados)
#
# Un solo objeto BusinessResult se renderiza en dashboard, workflow, agente,
# email, API y perfil de cliente. Importancia (INFO..CRITICAL) decide la
# superficie de notificación (Zent Insights / in-app) sin spam.
# =============================================================================
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

SECTIONS = ("needs_attention", "opportunities", "reports", "completed", "verification", "other")
IMPORTANCE = ("INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL")

# Importancia mínima que dispara notificación in-app (Zent Insights badge).
NOTIFY_FROM = "HIGH"


class BusinessResultError(ValueError):
    pass


@dataclass
class BusinessResult:
    id: UUID = field(default_factory=uuid4)
    title: str = ""
    summary: str | None = None
    section: str = "reports"
    importance: str = "INFO"
    metrics: dict[str, Any] = field(default_factory=dict)
    insights: list[str] = field(default_factory=list)
    entities: list[dict[str, Any]] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    actions_taken: list[str] = field(default_factory=list)
    actions_available: list[str] = field(default_factory=list)
    workflow_id: UUID | None = None
    workflow_run_id: UUID | None = None
    agent_run_id: UUID | None = None
    correlation_id: str | None = None
    source: str = "workflow"
    freshness_seconds: int = 0
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def fingerprint(self) -> str:
        """Huella para dedupe de resultados repetidos (mismo día/scope)."""
        day = self.generated_at.strftime("%Y-%m-%d")
        raw = json.dumps(
            [self.title, self.section, day, self.correlation_id or ""],
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def save_result(
    organization_id: UUID,
    result: BusinessResult,
    *,
    workspace_id: UUID | None = None,
    notify: bool = True,
) -> dict:
    """Persiste el BusinessResult; notifica in-app si importancia ≥ NOTIFY_FROM."""
    section = result.section if result.section in SECTIONS else "other"
    importance = result.importance if result.importance in IMPORTANCE else "INFO"
    if not result.title.strip():
        raise BusinessResultError("title requerido")
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO business_results "
                "(id, organization_id, workspace_id, title, summary, section, importance, "
                "metrics, insights, entities, recommendations, evidence, actions_taken, "
                "actions_available, workflow_id, workflow_run_id, agent_run_id, "
                "correlation_id, fingerprint, source, generated_at, freshness_seconds) "
                "VALUES (:id, :oid, :ws, :title, :summary, :section, :importance, "
                "CAST(:metrics AS jsonb), CAST(:insights AS jsonb), CAST(:entities AS jsonb), "
                "CAST(:recs AS jsonb), CAST(:evidence AS jsonb), CAST(:at AS jsonb), "
                "CAST(:aa AS jsonb), :wid, :rid, :arid, :corr, :fp, :src, :gen, :fresh)"
            ),
            {
                "id": result.id,
                "oid": organization_id,
                "ws": workspace_id,
                "title": result.title[:180],
                "summary": result.summary,
                "section": section,
                "importance": importance,
                "metrics": json.dumps(result.metrics or {}),
                "insights": json.dumps(result.insights or []),
                "entities": json.dumps(result.entities or []),
                "recs": json.dumps(result.recommendations or []),
                "evidence": json.dumps(result.evidence or []),
                "at": json.dumps(result.actions_taken or []),
                "aa": json.dumps(result.actions_available or []),
                "wid": result.workflow_id,
                "rid": result.workflow_run_id,
                "arid": result.agent_run_id,
                "corr": (result.correlation_id or "")[:128],
                "fp": result.fingerprint[:64],
                "src": result.source[:80],
                "gen": result.generated_at,
                "fresh": int(result.freshness_seconds or 0),
            },
        )
        await session.commit()
    finally:
        await session.close()

    notified = False
    if notify and importance in ("HIGH", "CRITICAL"):
        notified = await _notify_inapp(organization_id, workspace_id, result)
    return {
        "result_id": str(result.id),
        "importance": importance,
        "section": section,
        "notified": notified,
    }


async def _notify_inapp(
    organization_id: UUID,
    workspace_id: UUID | None,
    result: BusinessResult,
) -> bool:
    try:
        from src.platform.notifyv2.notifications import notify

        sent = await notify(
            organization_id=organization_id,
            event_type="intelligence.result",
            title=f"[{result.importance}] {result.title}",
            body=(result.summary or "")[:300] or "Nuevo resultado de inteligencia",
            data={
                "result_id": str(result.id),
                "section": result.section,
                "importance": result.importance,
                "workflow_id": str(result.workflow_id) if result.workflow_id else None,
                "run_id": str(result.workflow_run_id) if result.workflow_run_id else None,
            },
            channels={"in_app"},
        )
        return bool(sent and sent.get("in_app"))
    except Exception:  # noqa: BLE001
        return False


def _row(r) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "title": r.title,
        "summary": r.summary,
        "section": r.section,
        "importance": r.importance,
        "metrics": r.metrics or {},
        "insights": r.insights or [],
        "entities": r.entities or [],
        "recommendations": r.recommendations or [],
        "evidence": r.evidence or [],
        "actions_taken": r.actions_taken or [],
        "actions_available": r.actions_available or [],
        "workflow_id": str(r.workflow_id) if r.workflow_id else None,
        "workflow_run_id": str(r.workflow_run_id) if r.workflow_run_id else None,
        "agent_run_id": str(r.agent_run_id) if r.agent_run_id else None,
        "correlation_id": r.correlation_id,
        "fingerprint": r.fingerprint,
        "source": r.source,
        "generated_at": r.generated_at.isoformat(),
        "freshness_seconds": int(r.freshness_seconds or 0),
    }


async def list_results(
    organization_id: UUID,
    *,
    workspace_id: UUID | None = None,
    section: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    limit: int = 50,
    since_minutes: int | None = None,
) -> dict:
    from sqlalchemy import text as _text

    session = await get_async_session()
    try:
        sql = (
            "SELECT id, title, summary, section, importance, metrics, insights, entities, "
            "recommendations, evidence, actions_taken, actions_available, workflow_id, "
            "workflow_run_id, agent_run_id, correlation_id, fingerprint, source, "
            "generated_at, freshness_seconds "
            "FROM business_results WHERE organization_id = :oid"
        )
        params: dict[str, Any] = {"oid": organization_id, "lim": min(int(limit), 200)}
        if workspace_id is not None:
            sql += " AND (workspace_id = :ws OR workspace_id IS NULL)"
            params["ws"] = workspace_id
        if section:
            sql += " AND section = :section"
            params["section"] = section
        if since_minutes:
            sql += " AND generated_at > NOW() - make_interval(mins => :mins)"
            params["mins"] = int(since_minutes)
        rows = (
            await session.execute(_text(sql + " ORDER BY generated_at DESC LIMIT :lim"), params)
        ).fetchall()
        counts = (
            await session.execute(
                _text(
                    "SELECT section, COUNT(*) AS n, MAX(generated_at) AS last "
                    "FROM business_results WHERE organization_id = :oid "
                    "GROUP BY section"
                ),
                {"oid": organization_id},
            )
        ).fetchall()
    finally:
        await session.close()
    results = [_row(r) for r in rows]
    if entity_type and entity_id:
        results = [
            r
            for r in results
            if any(
                e.get("entity_type") == entity_type and str(e.get("entity_id")) == entity_id
                for e in r["entities"]
            )
        ]
    return {
        "results": results,
        "sections": {
            c.section: {"count": int(c.n), "last": c.last.isoformat() if c.last else None}
            for c in counts
        },
    }


async def get_result(organization_id: UUID, result_id: UUID) -> dict | None:
    from sqlalchemy import text as _text

    session = await get_async_session()
    try:
        row = (
            await session.execute(
                _text(
                    "SELECT id, title, summary, section, importance, metrics, insights, entities, "
                    "recommendations, evidence, actions_taken, actions_available, workflow_id, "
                    "workflow_run_id, agent_run_id, correlation_id, fingerprint, source, "
                    "generated_at, freshness_seconds "
                    "FROM business_results WHERE id = :rid AND organization_id = :oid"
                ),
                {"rid": result_id, "oid": organization_id},
            )
        ).fetchone()
    finally:
        await session.close()
    return _row(row) if row else None


def importance_from(**signals: Any) -> str:
    """Heurística de importancia (INFO..CRITICAL) basada en señales del resultado."""
    if signals.get("critical") or int(signals.get("changed_pct", 0) or 0) >= 50:
        return "CRITICAL"
    if signals.get("anomaly") or int(signals.get("changed_pct", 0) or 0) >= 20:
        return "HIGH"
    if signals.get("warn") or int(signals.get("changed_pct", 0) or 0) >= 10:
        return "MEDIUM"
    return "INFO"


def freshness_of(retrieved_at: datetime | None, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    if retrieved_at is None:
        return 0
    if retrieved_at.tzinfo is None:
        retrieved_at = retrieved_at.replace(tzinfo=timezone.utc)
    return max(0, int((now - retrieved_at).total_seconds()))
