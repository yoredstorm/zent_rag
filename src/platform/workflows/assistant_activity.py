# =============================================================================
# Living Assistants — actividad business-friendly (misión §27-§28).
#
# Deriva del historial real (workflow_runs + workflow_run_steps) un feed en
# lenguaje de negocio. Los detalles técnicos (run_id, node_id, latencia,
# error, correlación) viajan aparte: la UI los muestra sólo a pedido.
# =============================================================================
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.postgres.session import get_async_session

# Tipos internos que no aportan a la historia de negocio.
SKIP_NODE_TYPES = {
    "set_variable", "stop", "end", "join", "merge", "filter",
    "trigger_manual", "trigger_webhook", "trigger_schedule", "trigger_event", "trigger",
}

_TRIGGER_PHRASE = {
    "schedule": "según su programación",
    "event": "al ocurrir un evento",
    "webhook": "al recibir una señal externa",
    "manual": "de forma manual",
    "watcher": "al detectar un cambio",
}

_KIND_LABEL = {
    "llm": "análisis",
    "marketplace_action": "integración",
    "api_call": "api",
    "notify": "notificación",
    "condition": "condición",
    "business_result": "resultado",
    "query_business_data": "consulta",
    "kb_query": "conocimiento",
    "human_approval": "aprobación",
    "for_each": "recorrido",
}


def _text_of(output: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = output.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())[:240]
    return None


def _step_item(
    step: Any,
    *,
    run_id: str,
    correlation_id: str | None,
    action_labels: dict[str, str],
) -> dict[str, Any] | None:
    node_type = str(step.node_type or step.step_type or "")
    if not node_type or node_type in SKIP_NODE_TYPES:
        return None
    output = step.output if isinstance(step.output, dict) else {}
    config = step.input if isinstance(step.input, dict) else {}
    at = step.completed_at or step.started_at
    title = ""
    detail: str | None = None

    if node_type == "llm":
        title = "El agente analizó la información"
        detail = _text_of(output, "text", "answer", "message")
    elif node_type == "marketplace_action":
        action_id = str(config.get("action_id") or "")
        label = action_labels.get(action_id) or action_id or "una integración"
        title = f"Consultó {label}"
        detail = _text_of(output, "summary") or None
    elif node_type == "api_call":
        title = "Consultó una API externa"
    elif node_type == "notify":
        title = "Envió una notificación"
        detail = _text_of(output, "title", "message", "text") or _text_of(
            config, "title", "message"
        )
    elif node_type == "condition":
        passed = output.get("passed") if "passed" in output else output.get("result")
        if passed is None:
            title = "Evaluó una condición"
        else:
            title = "La condición se cumplió" if passed else "La condición no se cumplió"
    elif node_type == "business_result":
        title = "Publicó un resultado"
        detail = _text_of(output, "title") or _text_of(config, "title")
    elif node_type == "query_business_data":
        title = "Consultó datos de negocio"
        detail = _text_of(output, "answer", "text")
    elif node_type == "kb_query":
        title = "Consultó el conocimiento de la empresa"
    elif node_type == "human_approval":
        title = "Pidió una aprobación humana"
    elif node_type == "for_each":
        title = "Recorrió una lista de elementos"
    else:
        title = f"Ejecutó {node_type.replace('_', ' ')}"

    if str(step.status) == "failed" or step.error:
        title = f"Falló un paso: {title.lower()}"
    return {
        "kind": _KIND_LABEL.get(node_type, node_type),
        "node_type": node_type,
        "title": title,
        "detail": detail,
        "at": at.isoformat() if at else None,
        "status": str(step.status or ""),
        "tech": {
            "run_id": run_id,
            "node_id": step.node_id,
            "node_type": node_type,
            "status": str(step.status or ""),
            "duration_ms": int(step.duration_ms or 0),
            "retries": int(step.retries or 0),
            "error": step.error,
            "correlation_id": correlation_id,
        },
    }


async def agent_activity(
    organization_id: UUID,
    agent_id: UUID,
    *,
    limit: int = 40,
    runs_limit: int = 12,
) -> dict[str, Any] | None:
    """Feed de actividad del asistente. None si el agente no existe."""
    from src.platform.workflows.assistants import workflows_for_agent

    session = await get_async_session()
    try:
        agent = (
            await session.execute(
                text("SELECT id, name, status FROM agents WHERE id = :aid AND organization_id = :oid"),
                {"aid": agent_id, "oid": organization_id},
            )
        ).fetchone()
        if agent is None:
            return None
        matched = await workflows_for_agent(session, organization_id, agent_id)
        workflow_names = {w["workflow_id"]: w["name"] for w in matched}
        workflow_triggers = {w["workflow_id"]: w.get("trigger_type") for w in matched}
        workflow_ids: list[UUID] = []
        for workflow in matched:
            try:
                workflow_ids.append(UUID(str(workflow["workflow_id"])))
            except ValueError:
                continue

        runs: list[Any] = []
        steps: list[Any] = []
        if workflow_ids:
            runs = (
                await session.execute(
                    text(
                        "SELECT id, workflow_id, status, trigger, started_at, completed_at, "
                        "duration_ms, error, correlation_id "
                        "FROM workflow_runs WHERE organization_id = :oid "
                        "AND workflow_id = ANY(:ids) ORDER BY started_at DESC LIMIT :lim"
                    ),
                    {"oid": organization_id, "ids": workflow_ids, "lim": int(runs_limit)},
                )
            ).fetchall()
            if runs:
                steps = (
                    await session.execute(
                        text(
                            "SELECT run_id, node_id, node_type, step_type, status, input, output, "
                            "error, duration_ms, retries, started_at, completed_at "
                            "FROM workflow_run_steps WHERE run_id = ANY(:rids) "
                            "ORDER BY step_index NULLS LAST, started_at NULLS LAST LIMIT 500"
                        ),
                        {"rids": [r.id for r in runs]},
                    )
                ).fetchall()

        action_ids = {
            str((s.input or {}).get("action_id"))
            for s in steps
            if isinstance(s.input, dict) and (s.input or {}).get("action_id")
        }
        action_labels: dict[str, str] = {}
        if action_ids:
            rows = (
                await session.execute(
                    text(
                        "SELECT action_id, display_name FROM integration_actions "
                        "WHERE action_id = ANY(:ids)"
                    ),
                    {"ids": sorted(action_ids)},
                )
            ).fetchall()
            action_labels = {str(r.action_id): str(r.display_name) for r in rows}
    finally:
        await session.close()

    items: list[dict[str, Any]] = []
    by_run: dict[str, list[Any]] = {}
    for step in steps:
        by_run.setdefault(str(step.run_id), []).append(step)
    for run in runs:
        run_key = str(run.id)
        trigger = _TRIGGER_PHRASE.get(str(run.trigger), "automáticamente")
        items.append(
            {
                "kind": "run",
                "title": f'Se inició "{workflow_names.get(run_key, "una automatización")}" ({trigger})',
                "detail": (
                    f"Terminó con error: {str(run.error)[:160]}"
                    if str(run.status) == "failed" and run.error
                    else None
                ),
                "at": run.started_at.isoformat() if run.started_at else None,
                "status": str(run.status),
                "tech": {
                    "run_id": run_key,
                    "workflow_id": str(run.workflow_id),
                    "trigger": run.trigger,
                    "status": str(run.status),
                    "duration_ms": int(run.duration_ms or 0),
                    "correlation_id": run.correlation_id,
                },
            }
        )
        for step in by_run.get(run_key, []):
            item = _step_item(
                step,
                run_id=run_key,
                correlation_id=run.correlation_id,
                action_labels=action_labels,
            )
            if item:
                items.append(item)
            if len(items) >= max(1, int(limit)):
                break
        if len(items) >= max(1, int(limit)):
            break

    items = [item for item in items if item.get("at")]
    items.sort(key=lambda item: str(item.get("at")), reverse=True)
    return {
        "assistant": {"id": str(agent.id), "name": agent.name, "status": agent.status},
        "items": items[: max(1, int(limit))],
        "run_count": len(runs),
        "automation_count": len(matched),
        "trigger_types": sorted({str(t) for t in workflow_triggers.values() if t}),
    }


__all__ = ["agent_activity", "SKIP_NODE_TYPES"]
