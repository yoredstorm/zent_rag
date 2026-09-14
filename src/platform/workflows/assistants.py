# =============================================================================
# Living Assistants — agentes como asistentes activos ligados a workflows
# (misión Integration Experience §21-§24, §30-§31).
#
# Solo lectura: cruza agentes + workflows + triggers + watchers + runs para
# mostrar "qué está vigilando este asistente y qué hizo". No crea otro runtime.
# =============================================================================
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.postgres.session import get_async_session
from src.platform.workflows.event_registry import business_name_for


def describe_when(
    trigger_type: str | None,
    trigger_config: dict[str, Any] | None,
    *,
    watcher_event_type: str | None = None,
) -> str:
    """Frase de negocio para 'CUANDO...' de una automatización."""
    if watcher_event_type:
        try:
            return business_name_for(watcher_event_type)
        except Exception:  # noqa: BLE001
            return watcher_event_type
    config = trigger_config or {}
    ttype = str(trigger_type or "")
    if ttype == "event":
        event_type = str(config.get("event_type") or "")
        return business_name_for(event_type) if event_type else "Cuando ocurra un evento"
    if ttype == "schedule":
        from src.platform.workflows.intent import PlanSchedule

        schedule = PlanSchedule.from_trigger_config(config)
        return schedule.describe() if schedule is not None else "Según programación"
    if ttype == "webhook":
        return "Cuando se reciba una señal externa"
    return "Cuando se ejecute manualmente"


def summarize_workflow(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Métricas legibles por workflow a partir de sus runs recientes."""
    total = len(runs)
    ok = sum(1 for run in runs if str(run.get("status")) in ("succeeded", "simulated"))
    last = runs[0]["started_at"] if runs else None
    return {
        "runs": total,
        "ok_runs": ok,
        "success_rate": round(ok / total * 100, 1) if total else None,
        "last_activity": last,
    }


def assistant_status(automations: list[dict[str, Any]]) -> str:
    """Healthy / needs_attention / paused derivado de workflows y fallos."""
    if not automations:
        return "idle"
    if all(str(a.get("status")) == "paused" for a in automations):
        return "paused"
    if any(str(a.get("status")) in ("error", "needs_attention") for a in automations):
        return "needs_attention"
    if any(int(a.get("failed_runs") or 0) > 0 for a in automations):
        return "needs_attention"
    return "healthy"


async def workflows_for_agent(
    session, organization_id: UUID, agent_id: UUID, *, limit: int = 500
) -> list[dict[str, Any]]:
    """Workflows cuyo grafo tiene un nodo llm asociado al agente."""
    workflow_rows = (
        await session.execute(
            text(
                "SELECT id, name, description, status, trigger_type, trigger_config, graph "
                "FROM workflows WHERE organization_id = :oid ORDER BY updated_at DESC LIMIT :lim"
            ),
            {"oid": organization_id, "lim": int(limit)},
        )
    ).fetchall()
    matched: list[dict[str, Any]] = []
    for row in workflow_rows:
        graph = row.graph if isinstance(row.graph, dict) else {}
        hits = 0
        for node in graph.get("nodes") or []:
            if not isinstance(node, dict) or node.get("type") != "llm":
                continue
            config = node.get("config") or {}
            if str(config.get("agent_id") or "") == str(agent_id):
                hits += 1
        if hits:
            matched.append(
                {
                    "workflow_id": str(row.id),
                    "name": row.name,
                    "description": row.description,
                    "status": row.status,
                    "trigger_type": row.trigger_type,
                    "trigger_config": row.trigger_config or {},
                    "agent_nodes": hits,
                }
            )
    return matched


async def agent_automations(organization_id: UUID, agent_id: UUID) -> dict[str, Any] | None:
    """Workflows, triggers, watchers y actividad de un agente. None si no existe."""
    session = await get_async_session()
    try:
        agent = (
            await session.execute(
                text(
                    "SELECT id, name, status FROM agents "
                    "WHERE id = :aid AND organization_id = :oid"
                ),
                {"aid": agent_id, "oid": organization_id},
            )
        ).fetchone()
        if agent is None:
            return None

        matched = await workflows_for_agent(session, organization_id, agent_id)
        matched_ids: list[UUID] = []
        for workflow in matched:
            try:
                matched_ids.append(UUID(str(workflow["workflow_id"])))
            except ValueError:
                continue

        triggers: dict[str, str] = {}
        if matched_ids:
            trigger_rows = (
                await session.execute(
                    text(
                        "SELECT workflow_id, event_type FROM workflow_event_triggers "
                        "WHERE organization_id = :oid AND workflow_id = ANY(:ids)"
                    ),
                    {"oid": organization_id, "ids": matched_ids},
                )
            ).fetchall()
            triggers = {str(r.workflow_id): r.event_type for r in trigger_rows}

        watchers: dict[str, str] = {}
        if matched_ids:
            try:
                watcher_rows = (
                    await session.execute(
                        text(
                            "SELECT id, workflow_id, event_type FROM workflow_watchers "
                            "WHERE organization_id = :oid AND workflow_id = ANY(:ids)"
                        ),
                        {"oid": organization_id, "ids": matched_ids},
                    )
                ).fetchall()
                watchers = {str(r.workflow_id): str(r.id) for r in watcher_rows}
            except Exception:  # noqa: BLE001 — base sin migración 110
                watchers = {}

        since = datetime.now(timezone.utc) - timedelta(days=7)
        runs_by_workflow: dict[str, list[dict[str, Any]]] = {str(w["workflow_id"]): [] for w in matched}
        actions_today = 0
        if matched_ids:
            run_rows = (
                await session.execute(
                    text(
                        "SELECT workflow_id, status, started_at FROM workflow_runs "
                        "WHERE organization_id = :oid AND workflow_id = ANY(:ids) "
                        "AND started_at >= :since ORDER BY started_at DESC LIMIT 500"
                    ),
                    {"oid": organization_id, "ids": matched_ids, "since": since},
                )
            ).fetchall()
            today = datetime.now(timezone.utc).date()
            for row in run_rows:
                key = str(row.workflow_id)
                runs_by_workflow.setdefault(key, []).append(
                    {
                        "status": row.status,
                        "started_at": row.started_at.isoformat() if row.started_at else None,
                    }
                )
                if row.started_at and row.started_at.date() == today:
                    actions_today += 1
    finally:
        await session.close()

    automations: list[dict[str, Any]] = []
    last_activity: str | None = None
    for workflow in matched:
        key = workflow["workflow_id"]
        stats = summarize_workflow(runs_by_workflow.get(key, []))
        failed = stats["runs"] - stats["ok_runs"] if stats["runs"] else 0
        when = describe_when(
            workflow["trigger_type"],
            workflow["trigger_config"],
            watcher_event_type=triggers.get(key),
        )
        automations.append(
            {
                **workflow,
                "when": when,
                "watcher_id": watchers.get(key),
                "runs_7d": stats["runs"],
                "failed_runs": failed,
                "success_rate": stats["success_rate"],
                "last_activity": stats["last_activity"],
            }
        )
        if stats["last_activity"] and (last_activity is None or stats["last_activity"] > last_activity):
            last_activity = stats["last_activity"]

    automations.sort(key=lambda a: str(a.get("last_activity") or ""), reverse=True)
    return {
        "assistant": {
            "id": str(agent.id),
            "name": agent.name,
            "status": agent.status,
        },
        "summary": {
            "automations": len(automations),
            "active": sum(1 for a in automations if a["status"] == "active"),
            "actions_today": actions_today,
            "last_activity": last_activity,
            "health": assistant_status(automations),
        },
        "automations": automations,
    }


__all__ = [
    "agent_automations",
    "assistant_status",
    "describe_when",
    "summarize_workflow",
    "workflows_for_agent",
]
