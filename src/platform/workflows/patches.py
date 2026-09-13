# =============================================================================
# Workflow Semantic Patches — edición por lenguaje natural (misión §21).
#
# El LLM propone `SemanticWorkflowPatch`; el backend valida cada operación
# contra el grafo real, genera un diff legible y solo aplica tras confirmación.
# Nunca regenera el workflow completo ni publica cambios.
# =============================================================================
from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from src.platform.workflows.intent import (
    PatchOperation,
    PlanRecipient,
    PlanSchedule,
    SemanticWorkflowPatch,
)

PATCH_SYSTEM_PROMPT = """Eres el copiloto de Zent para editar automatizaciones existentes.
Devuelve SOLO un JSON SemanticWorkflowPatch, sin markdown:
{
  "summary": str,
  "operations": [
    {"op": "set_value", "target": "<node_id>",
     "value": {"path": "config.<key>", "value": any}, "description": str|null},
    {"op": "change_channel", "target": "<node_id>", "value": "zent"|"email"|"webhook"},
    {"op": "add_recipient", "target": "<node_id>",
     "value": {"kind": "person"|"team"|"email"|"webhook", "value": str, "label": str|null}},
    {"op": "remove_recipient", "target": "<node_id>", "value": "<label o value>"},
    {"op": "change_schedule", "target": "<node_id>",
     "value": {"mode": "interval"|"daily"|"weekly"|"monthly"|"cron", "time": "HH:MM",
               "days": [0-6], "day_of_month": int, "every_minutes": int, "timezone": str, "cron": str}},
    {"op": "replace_agent", "target": "<node_id>",
     "value": {"agent_id": str|null, "agent_name": str|null}},
    {"op": "rename", "target": "workflow", "value": "<nuevo nombre>"}
  ],
  "confidence": 0.0-1.0,
  "questions": [str]
}
- Usa los ids de nodo exactos del grafo recibido (no inventes).
- NO regeneres el workflow completo: solo las operaciones del cambio pedido.
- Si el pedido es ambiguo, no inventes: agrégalo a "questions" con confianza baja.
"""


# ---------------------------------------------------------------------------
# Fingerprint / vista semántica
# ---------------------------------------------------------------------------
def graph_fingerprint(graph_dict: dict[str, Any]) -> str:
    canonical = json.dumps(graph_dict or {}, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def semantic_view(graph_dict: dict[str, Any]) -> list[dict[str, Any]]:
    """Vista compacta del grafo para el LLM: ids reales + negocio visible."""
    from src.platform.workflows.conditions import describe_condition_tree, normalize_rules

    nodes: list[dict[str, Any]] = []
    for node in graph_dict.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        config = node.get("config") or {}
        entry: dict[str, Any] = {
            "id": str(node.get("id")),
            "type": str(node.get("type")),
            "label": str(node.get("label") or ""),
        }
        if node.get("type") == "condition":
            entry["condition"] = describe_condition_tree(normalize_rules(config) or {})
        if node.get("type") == "notify":
            entry["channel"] = config.get("channel")
            entry["title"] = config.get("title")
            entry["recipients"] = config.get("recipients")
        if node.get("type") == "llm":
            entry["agent"] = config.get("agent_name") or config.get("agent_id")
            entry["prompt"] = config.get("prompt")
        if node.get("type") == "trigger_schedule":
            entry["schedule"] = config.get("schedule")
        nodes.append(entry)
    return nodes


# ---------------------------------------------------------------------------
# Validación + aplicación
# ---------------------------------------------------------------------------
_SUPPORTED_OPS = {
    "set_value",
    "set_field",
    "change_channel",
    "add_recipient",
    "remove_recipient",
    "change_schedule",
    "rename",
    "replace_agent",
}


def _issue(code: str, message: str, *, severity: str = "error", field: str | None = None) -> dict[str, Any]:
    return {"code": code, "severity": severity, "message": message, "hint": None, "field": field}


def _node_map(graph_dict: dict[str, Any]) -> dict[str, dict]:
    return {
        str(node["id"]): node
        for node in graph_dict.get("nodes") or []
        if isinstance(node, dict) and node.get("id")
    }


def _set_path(container: dict[str, Any], path: str, value: Any) -> Any:
    """Escribe `path` (con notación de puntos) y devuelve el valor anterior."""
    parts = [p for p in str(path).split(".") if p]
    if not parts:
        return None
    previous: Any
    cur: Any = container
    for part in parts[:-1]:
        if not isinstance(cur, dict):
            return None
        cur = cur.setdefault(part, {})
    if isinstance(cur, dict):
        previous = cur.get(parts[-1])
        cur[parts[-1]] = value
        return previous
    return None


def validate_patch(
    graph_dict: dict[str, Any],
    patch: SemanticWorkflowPatch,
    capabilities: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Valida operaciones contra el grafo real. Devuelve issues con severidad."""
    caps = capabilities or {}
    nodes = _node_map(graph_dict)
    issues: list[dict[str, Any]] = []
    for index, operation in enumerate(patch.operations):
        field = f"operations.{index}"
        if operation.op not in _SUPPORTED_OPS:
            issues.append(_issue("patch.op_unsupported", f"Todavía no sé aplicar «{operation.op}».", field=field))
            continue
        target = str(operation.target or "")
        node_id = target
        if operation.op == "set_field":
            parts = target.split(".")
            if len(parts) < 4 or parts[0] != "nodes" or parts[2] != "config":
                issues.append(
                    _issue(
                        "patch.field_shape",
                        "Para editar un campo usa target \"nodes.<id>.config.<campo>\".",
                        field=field,
                    )
                )
                continue
            node_id = parts[1]
        if operation.op == "rename":
            if not str(operation.value or "").strip():
                issues.append(_issue("patch.empty_name", "El nuevo nombre no puede estar vacío.", field=field))
            continue
        node = nodes.get(node_id)
        if node is None:
            issues.append(_issue("patch.node_missing", f"No encontré el paso «{target}» en el flujo.", field=field))
            continue
        node_type = str(node.get("type") or "")
        if operation.op in ("change_channel", "add_recipient", "remove_recipient") and node_type != "notify":
            issues.append(_issue("patch.node_not_notify", "Ese cambio solo aplica a un paso «Avisar».", field=field))
            continue
        if operation.op == "change_channel":
            channel = str(operation.value or "")
            if channel not in ("zent", "in_app", "email", "webhook"):
                issues.append(
                    _issue(
                        "patch.channel_unavailable",
                        f"El canal «{channel}» no está disponible en este flujo.",
                        field=field,
                    )
                )
        if operation.op in ("add_recipient", "remove_recipient"):
            if operation.op == "add_recipient":
                try:
                    PlanRecipient.model_validate(operation.value)
                except Exception as exc:  # noqa: BLE001
                    issues.append(_issue("patch.recipient_invalid", f"Destinatario inválido: {exc}", field=field))
        if operation.op == "change_schedule":
            if node_type not in ("trigger_schedule",):
                issues.append(
                    _issue(
                        "patch.node_not_schedule",
                        "Ese cambio solo aplica al paso de programación.",
                        field=field,
                    )
                )
                continue
            try:
                PlanSchedule.model_validate(operation.value)
            except Exception as exc:  # noqa: BLE001
                issues.append(_issue("patch.schedule_invalid", f"Programación inválida: {exc}", field=field))
        if operation.op == "replace_agent":
            value = operation.value or {}
            if not value.get("agent_id") and not value.get("agent_name"):
                issues.append(_issue("patch.agent_required", "Indica el agente que debe analizar.", field=field))
            elif caps.get("agents"):
                resolved = caps["agents"].get(str(value.get("agent_id") or "")) or caps["agents"].get(
                    str(value.get("agent_name") or "").lower()
                )
                if resolved is None:
                    missing = value.get("agent_name") or value.get("agent_id")
                    issues.append(
                        _issue(
                            "patch.agent_unknown",
                            f"No encontré el agente «{missing}».",
                            field=field,
                        )
                    )
        if operation.op in ("set_value", "set_field"):
            value = operation.value
            if operation.op == "set_value":
                if not isinstance(value, dict) or not value.get("path"):
                    issues.append(
                        _issue(
                            "patch.value_shape",
                            "La operación set_value necesita {path, value}.",
                            field=field,
                        )
                    )
                    continue
                if str(value["path"]).startswith("config.rules") or str(value["path"]) == "config.field":
                    issues.append(
                        _issue(
                            "patch.condition_use_op",
                            "Para cambiar una condición usa el constructor de condiciones; "
                            "este cambio necesita revisión técnica.",
                            field=field,
                        )
                    )
    return issues


def apply_patch(
    graph_dict: dict[str, Any],
    patch: SemanticWorkflowPatch,
    capabilities: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Aplica el patch validado. Devuelve grafo nuevo + diff + issues."""
    issues = validate_patch(graph_dict, patch, capabilities)
    errors = [i for i in issues if i["severity"] == "error"]
    if errors:
        return {"graph": graph_dict, "diff": [], "issues": issues}

    graph = json.loads(json.dumps(graph_dict))
    nodes = _node_map(graph)
    diff: list[dict[str, Any]] = []

    for operation in patch.operations:
        target = str(operation.target or "")
        node_id = target
        if operation.op == "set_field" and target.startswith("nodes."):
            parts = target.split(".")
            if len(parts) >= 4:
                node_id = parts[1]
        if operation.op == "rename":
            before = graph.get("metadata", {}).get("display_name")
            graph.setdefault("metadata", {})["display_name"] = operation.value
            diff.append(
                {
                    "op": "rename",
                    "node_id": None,
                    "label": "Nombre",
                    "before": before,
                    "after": operation.value,
                    "description": operation.description or "Cambiar el nombre",
                }
            )
            continue
        node = nodes.get(node_id)
        if node is None:
            continue
        config = node.setdefault("config", {})
        if operation.op == "change_channel":
            engine_channel = "in_app" if operation.value == "zent" else operation.value
            before = config.get("channel")
            diff.append(
                _diff_entry("change_channel", target, node, "Canal", before, engine_channel, operation)
            )
            config["channel"] = engine_channel
        elif operation.op == "add_recipient":
            recipient = PlanRecipient.model_validate(operation.value).model_dump(mode="json")
            recipients = list(config.get("recipients") or [])
            already = any(
                r.get("value") == recipient["value"] and r.get("kind") == recipient["kind"]
                for r in recipients
            )
            if not already:
                recipients.append(recipient)
                config["recipients"] = recipients
                diff.append(
                    _diff_entry(
                        "add_recipient",
                        target,
                        node,
                        "Destinatarios",
                        None,
                        recipient.get("label") or recipient["value"],
                        operation,
                    )
                )
        elif operation.op == "remove_recipient":
            wanted = str(operation.value or "")
            recipients = list(config.get("recipients") or [])
            remaining = [
                r
                for r in recipients
                if str(r.get("label") or "") != wanted and str(r.get("value") or "") != wanted
            ]
            if len(remaining) != len(recipients):
                config["recipients"] = remaining
                diff.append(_diff_entry("remove_recipient", target, node, "Destinatarios", wanted, None, operation))
        elif operation.op == "change_schedule":
            schedule = PlanSchedule.model_validate(operation.value)
            diff.append(
                _diff_entry(
                    "change_schedule",
                    target,
                    node,
                    "Programación",
                    config.get("schedule"),
                    schedule.model_dump(mode="json"),
                    operation,
                )
            )
            config["schedule"] = schedule.model_dump(mode="json")
        elif operation.op == "replace_agent":
            value = operation.value or {}
            previous = config.get("agent_name") or config.get("agent_id")
            diff.append(
                _diff_entry(
                    "replace_agent",
                    target,
                    node,
                    "Agente",
                    previous,
                    value.get("agent_name") or value.get("agent_id"),
                    operation,
                )
            )
            config["agent_id"] = value.get("agent_id") or ""
            config["agent_name"] = value.get("agent_name") or ""
        else:  # set_value / set_field
            if operation.op == "set_value":
                path = str((operation.value or {}).get("path") or "")
                value = (operation.value or {}).get("value")
            else:
                path = str(operation.target or "")
                value = operation.value
            if path.startswith("config."):
                path = path[len("config."):]
            elif path.startswith("nodes."):
                path = path.split(".config.", 1)[1] if ".config." in path else path
            before = _set_path(config, path, value)
            diff.append(_diff_entry(operation.op, target, node, path, before, value, operation))
    return {"graph": graph, "diff": diff, "issues": issues}


def _diff_entry(
    op: str,
    node_id: str,
    node: dict[str, Any],
    label: str,
    before: Any,
    after: Any,
    operation: PatchOperation,
) -> dict[str, Any]:
    return {
        "op": op,
        "node_id": node_id,
        "node_label": node.get("label") or node.get("type"),
        "label": label,
        "before": before,
        "after": after,
        "description": operation.description or label,
    }


# ---------------------------------------------------------------------------
# Pipeline NL → patch
# ---------------------------------------------------------------------------
def _resolve_llm_provider(provider: Any = None) -> Any:
    if provider is not None:
        return provider
    from src.api.deps import get_llm_provider

    try:
        from src.api.main import app

        override = app.dependency_overrides.get(get_llm_provider)
        if override is not None:
            return override()
    except Exception:  # noqa: BLE001
        pass
    return get_llm_provider()


def _parse_json_object(text: str) -> dict[str, Any] | None:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


async def propose_patch(
    organization_id: UUID,
    workflow_id: UUID,
    prompt: str,
    *,
    provider: Any = None,
) -> dict[str, Any] | None:
    """NL → SemanticWorkflowPatch validado + diff. None si el workflow no existe."""
    from src.platform.workflows.engine import get_workflow
    from src.platform.workflows.plan_compiler import load_capabilities

    workflow = await get_workflow(organization_id, workflow_id)
    if workflow is None:
        return None
    graph_dict = workflow.get("graph") or {}
    capabilities = await load_capabilities(organization_id)

    view = semantic_view(graph_dict)
    user_prompt = (
        f"Flujo actual (JSON de nodos): {json.dumps(view, ensure_ascii=False)}\n"
        f"Petición del usuario: {prompt}"
    )
    provider = _resolve_llm_provider(provider)
    response = await provider.generate(
        prompt=user_prompt,
        temperature=0.0,
        max_tokens=1200,
        system_prompt=PATCH_SYSTEM_PROMPT,
    )
    content = getattr(response, "content", None)
    if content is None and isinstance(response, dict):
        content = response.get("content")
    data = _parse_json_object(str(content or ""))
    if data is None:
        return {
            "patch": None,
            "diff": [],
            "issues": [
                _issue(
                    "patch.parse",
                    "No pude interpretar el cambio; describe qué quieres ajustar.",
                    severity="error",
                )
            ],
            "base_graph_hash": graph_fingerprint(graph_dict),
            "summary": None,
            "questions": [],
        }
    patch = SemanticWorkflowPatch.model_validate(data)
    result = apply_patch(graph_dict, patch, capabilities)
    return {
        "patch": patch.model_dump(mode="json"),
        "diff": result["diff"],
        "issues": result["issues"],
        "base_graph_hash": graph_fingerprint(graph_dict),
        "summary": patch.summary,
        "questions": patch.questions,
        "confidence": patch.confidence,
    }


async def apply_workflow_patch(
    organization_id: UUID,
    workflow_id: UUID,
    patch_payload: dict[str, Any],
    *,
    base_graph_hash: str | None = None,
) -> dict[str, Any] | None:
    """Aplica el patch confirmado y persiste el grafo (sin activar)."""
    from src.platform.workflows.engine import get_workflow, update_workflow
    from src.platform.workflows.plan_compiler import load_capabilities

    workflow = await get_workflow(organization_id, workflow_id)
    if workflow is None:
        return None
    graph_dict = workflow.get("graph") or {}
    current_hash = graph_fingerprint(graph_dict)
    if base_graph_hash and base_graph_hash != current_hash:
        return {
            "status": "conflict",
            "message": "El flujo cambió desde que viste el diff. Vuelve a pedir el cambio.",
        }
    patch = SemanticWorkflowPatch.model_validate(patch_payload)
    capabilities = await load_capabilities(organization_id)
    result = apply_patch(graph_dict, patch, capabilities)
    errors = [i for i in result["issues"] if i["severity"] == "error"]
    if errors:
        return {"status": "invalid", "issues": result["issues"], "diff": result["diff"]}
    updated = await update_workflow(
        organization_id,
        workflow_id,
        graph=result["graph"],
        workflow_version=2,
    )
    if updated is None:
        return None
    return {
        "status": "applied",
        "diff": result["diff"],
        "issues": result["issues"],
        "base_graph_hash": current_hash,
        "new_graph_hash": graph_fingerprint(result["graph"]),
    }


__all__ = [
    "PATCH_SYSTEM_PROMPT",
    "apply_patch",
    "apply_workflow_patch",
    "graph_fingerprint",
    "propose_patch",
    "semantic_view",
    "validate_patch",
]
