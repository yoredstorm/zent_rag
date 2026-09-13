# =============================================================================
# Workflow Readiness & Summary — checklist de negocio antes de publicar
# (misión §19) y descripción legible del flujo (misión §20).
#
# Solo lee el grafo + capabilities del tenant. No cambia el motor, no publica
# y nunca muestra un error de schema técnico como primer mensaje.
# =============================================================================
from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from src.platform.workflows.conditions import describe_condition_tree, normalize_rules

_REF_RE = re.compile(r"\{\{nodes\.([A-Za-z0-9_-]+)")
_TRIGGER_RE = re.compile(r"\{\{trigger\.")


def _node_list(graph: dict[str, Any]) -> list[dict[str, Any]]:
    return [n for n in (graph.get("nodes") or []) if isinstance(n, dict) and n.get("id")]


def _check(key: str, label: str, status: str, message: str, hint: str | None = None) -> dict[str, Any]:
    return {"key": key, "label": label, "status": status, "message": message, "hint": hint}


def _walk_rules_refs(rules: Any, found: set[str]) -> None:
    if not isinstance(rules, dict):
        return
    if rules.get("kind") == "condition":
        for match in _REF_RE.finditer(str(rules.get("field") or "")):
            found.add(match.group(1))
    for child in rules.get("children") or []:
        _walk_rules_refs(child, found)


def readiness_checks(
    graph: dict[str, Any],
    capabilities: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    caps = capabilities or {}
    nodes = _node_list(graph)
    node_ids = {str(n["id"]) for n in nodes}
    types = [str(n.get("type")) for n in nodes]
    checks: list[dict[str, Any]] = []

    # 1) Trigger
    if any(t.startswith("trigger_") for t in types):
        checks.append(_check("trigger", "Inicio del flujo", "ok", "El flujo tiene un disparador."))
    else:
        checks.append(
            _check(
                "trigger",
                "Inicio del flujo",
                "error",
                "Falta definir cuándo empieza el flujo.",
                "Agrega un disparador.",
            )
        )

    # 2) Datos
    data_issues: list[str] = []
    for node in nodes:
        config = node.get("config") or {}
        if node.get("type") == "query_business_data" and not str(config.get("ask") or "").strip():
            data_issues.append(f"{node.get('label') or node['id']}: falta la pregunta a los datos.")
        if node.get("type") == "kb_query":
            kb_id = str(config.get("knowledge_base_id") or "")
            if not kb_id:
                data_issues.append(f"{node.get('label') or node['id']}: falta elegir la base de conocimiento.")
            elif caps.get("knowledge_bases") and kb_id not in caps["knowledge_bases"]:
                # el índice incluye ids y nombres; probar por id directo
                if kb_id.lower() not in caps["knowledge_bases"]:
                    data_issues.append(f"{node.get('label') or node['id']}: la base de conocimiento no existe.")
            if not str(config.get("query") or "").strip():
                data_issues.append(f"{node.get('label') or node['id']}: falta la búsqueda en la base.")
    if data_issues:
        checks.append(_check("data", "Datos", "warning", data_issues[0], "Completa los pasos de datos."))
    else:
        checks.append(_check("data", "Datos", "ok", "Los pasos de datos están completos."))

    # 3) Condiciones (referencias a nodos existentes)
    missing_refs: set[str] = set()
    condition_count = 0
    for node in nodes:
        config = node.get("config") or {}
        rules = normalize_rules(config)
        if rules:
            condition_count += 1
            refs: set[str] = set()
            _walk_rules_refs(rules, refs)
            missing_refs.update(ref for ref in refs if ref not in node_ids)
    if missing_refs:
        checks.append(
            _check(
                "conditions",
                "Condiciones",
                "error",
                f"No encontramos el dato de salida de {', '.join(sorted(missing_refs))}.",
                "Elige de nuevo el dato en el constructor de condiciones.",
            )
        )
    elif condition_count:
        checks.append(_check("conditions", "Condiciones", "ok", f"{condition_count} condición(es) configuradas."))
    else:
        checks.append(_check("conditions", "Condiciones", "ok", "El flujo no necesita condiciones."))

    # 4) Agentes
    agent_issues: list[str] = []
    for node in nodes:
        if node.get("type") != "llm":
            continue
        config = node.get("config") or {}
        agent_id = str(config.get("agent_id") or "")
        if not agent_id:
            agent_issues.append(f"{node.get('label') or node['id']}: falta elegir el agente.")
        elif caps.get("agents") and agent_id not in caps["agents"]:
            agent_issues.append(f"{node.get('label') or node['id']}: el agente ya no está disponible.")
    if agent_issues:
        checks.append(_check("agents", "Agentes", "warning", agent_issues[0], "Elige un agente activo."))
    else:
        checks.append(_check("agents", "Agentes", "ok", "Los agentes están listos."))

    # 5) Destinatarios / capacidades de salida
    output_issues: list[str] = []
    output_errors: list[str] = []
    for node in nodes:
        node_type = str(node.get("type"))
        config = node.get("config") or {}
        label = node.get("label") or node["id"]
        if node_type == "notify":
            channel = str(config.get("channel") or "in_app")
            if channel == "email" and not config.get("recipients"):
                output_issues.append(f"{label}: falta elegir a quién avisar.")
            if channel in ("slack", "teams", "whatsapp"):
                output_errors.append(
                    f"{label}: necesitas conectar {channel.capitalize()} para usar esta acción."
                )
        if node_type == "marketplace_action":
            action_id = str(config.get("action_id") or "")
            if not action_id:
                output_errors.append(f"{label}: falta elegir la acción de la integración.")
            elif caps.get("actions") and action_id not in caps["actions"]:
                output_errors.append(f"{label}: la acción {action_id} no está instalada.")
        if node_type == "api_call" and not str(config.get("url") or "").strip():
            output_errors.append(f"{label}: la llamada API necesita una dirección.")
    if output_errors:
        checks.append(_check("outputs", "Salidas", "error", output_errors[0], "Revisa los pasos de salida."))
    elif output_issues:
        checks.append(_check("outputs", "Salidas", "warning", output_issues[0], "Completa los destinatarios."))
    else:
        checks.append(_check("outputs", "Salidas", "ok", "Los avisos y acciones están completos."))

    return checks


async def workflow_readiness(
    organization_id: UUID,
    workflow_id: UUID,
    *,
    workspace_id: UUID | None = None,
) -> dict[str, Any] | None:
    from src.platform.workflows.engine import get_workflow
    from src.platform.workflows.ir import LegacyWorkflowAdapter
    from src.platform.workflows.plan_compiler import load_capabilities

    workflow = await get_workflow(organization_id, workflow_id)
    if workflow is None:
        return None
    graph = workflow.get("graph")
    if not graph:
        adapted = LegacyWorkflowAdapter.steps_to_graph(
            workflow.get("steps") or [],
            workflow.get("trigger_type") or "webhook",
            workflow.get("trigger_config") or {},
        )
        graph = adapted.to_dict()
    capabilities = await load_capabilities(organization_id, workspace_id)
    checks = readiness_checks(graph, capabilities)
    errors = [c for c in checks if c["status"] == "error"]
    warnings = [c for c in checks if c["status"] == "warning"]
    return {
        "workflow_id": str(workflow_id),
        "status": workflow.get("status"),
        "ready": not errors,
        "checks": checks,
        "errors": len(errors),
        "warnings": len(warnings),
    }


# ---------------------------------------------------------------------------
# Resumen legible (misión §20)
# ---------------------------------------------------------------------------
_CHANNEL_LABELS = {
    "in_app": "Zent",
    "zent": "Zent",
    "email": "correo",
    "webhook": "webhook",
    "slack": "Slack",
    "teams": "Microsoft Teams",
    "whatsapp": "WhatsApp",
}


def graph_summary(graph: dict[str, Any]) -> dict[str, Any]:
    nodes = _node_list(graph)
    steps: list[str] = []
    when = "se reciba la señal"
    for node in nodes:
        node_type = str(node.get("type"))
        config = node.get("config") or {}
        if node_type == "trigger_schedule":
            schedule = config.get("schedule")
            when = _schedule_text(schedule) if schedule else "según la programación"
        elif node_type == "trigger_event":
            when = f"ocurra {config.get('event_type') or 'un evento'}"
        elif node_type == "condition":
            text = describe_condition_tree(normalize_rules(config) or {})
            if text:
                steps.append(f"si {text}")
        elif node_type == "llm":
            who = str(config.get("agent_name") or "un agente")
            what = str(config.get("prompt") or "analice la situación")
            steps.append(f"pedir a {who} que {what}")
        elif node_type == "notify":
            channel = _CHANNEL_LABELS.get(str(config.get("channel") or "in_app"), "Zent")
            recipients = config.get("recipients") or []
            target = ", ".join(str(r.get("label") or r.get("value")) for r in recipients if isinstance(r, dict))
            steps.append(f"avisar por {channel}" + (f" a {target}" if target else ""))
        elif node_type == "marketplace_action":
            steps.append(f"usar la acción {config.get('action_id') or 'de integración'}")
        elif node_type == "human_approval":
            steps.append("pedir aprobación humana")
        elif node_type == "business_result":
            steps.append(f"publicar «{config.get('title') or 'el resultado'}»")
        elif node_type == "stop":
            steps.append("detener el flujo")
    if not steps:
        steps.append("ejecutar el flujo configurado")
    text = f"Cuando {when}, Zent {', '.join(steps)}."
    return {"when": when, "steps": steps, "text": text}


def _schedule_text(schedule: dict[str, Any] | None) -> str:
    from src.platform.workflows.intent import PlanSchedule

    if not isinstance(schedule, dict):
        return "según la programación"
    try:
        return PlanSchedule.model_validate(schedule).describe()
    except Exception:  # noqa: BLE001
        return "según la programación"


async def workflow_summary(
    organization_id: UUID,
    workflow_id: UUID,
) -> dict[str, Any] | None:
    from src.platform.workflows.engine import get_workflow
    from src.platform.workflows.ir import LegacyWorkflowAdapter

    workflow = await get_workflow(organization_id, workflow_id)
    if workflow is None:
        return None
    graph = workflow.get("graph")
    if not graph:
        adapted = LegacyWorkflowAdapter.steps_to_graph(
            workflow.get("steps") or [],
            workflow.get("trigger_type") or "webhook",
            workflow.get("trigger_config") or {},
        )
        graph = adapted.to_dict()
    summary = graph_summary(graph)
    summary["workflow_id"] = str(workflow_id)
    summary["name"] = workflow.get("name")
    return summary


__all__ = [
    "graph_summary",
    "readiness_checks",
    "workflow_readiness",
    "workflow_summary",
]
