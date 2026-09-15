# =============================================================================
# Workflow Architect — Compilador determinístico (First delivery, brief §7).
#
# Semántica (pasos de negocio) → WorkflowGraph v2. El LLM nunca arma el grafo.
# Las referencias `input: {step, field}` se traducen a `{{nodes.<id>.output.*}}`.
# =============================================================================
from __future__ import annotations

import re
from typing import Any

from src.infrastructure.observability.logging_config import get_logger
from src.platform.workflows.architect_models import (
    ArchitectIntent,
    PlanInputRef,
    PlanIssue,
    PlanStep,
    SemanticPlan,
)

logger = get_logger(__name__)

_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9_-]+")
_OPERATION_HINTS: tuple[tuple[str, str], ...] = (
    ("contradic", "check_conflicts"),
    ("conflict", "check_conflicts"),
    ("compar", "compare"),
    ("versus", "compare"),
    ("investiga", "investigate"),
    ("evidencia", "find_evidence"),
    ("hecho", "extract_facts"),
    ("extrae", "extract_facts"),
)


def default_knowledge_operation(goal: str) -> str:
    text = str(goal or "").lower()
    for hint, operation in _OPERATION_HINTS:
        if hint in text:
            return operation
    return "answer"


def _node_id(step_id: str, used: set[str]) -> str:
    safe = _SAFE_ID_RE.sub("_", str(step_id)).strip("_") or "step"
    if safe[0].isdigit():
        safe = f"n_{safe}"
    candidate = safe[:60]
    suffix = 2
    while candidate in used:
        candidate = f"{safe[:56]}_{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def _ref(step_node_id: str, field: str) -> str:
    return f"{{{{nodes.{step_node_id}.output.{field}}}}}"


def _choose_agent(step: PlanStep, capabilities: dict[str, Any]) -> tuple[str, str, int]:
    from src.platform.workflows.architect_discovery import match_agents

    explicit = str(step.params.get("agent_id") or "").strip()
    agents = capabilities.get("agents") or []
    if explicit:
        for agent in agents:
            if str(agent.get("id")) == explicit:
                return str(agent["id"]), str(agent.get("name") or ""), 5
        return explicit, str(step.params.get("agent_name") or ""), 0
    matches = match_agents(f"{step.goal} {step.params.get('prompt') or ''}", capabilities)
    if matches:
        best = matches[0]
        return str(best["id"]), str(best.get("name") or ""), int(best.get("score") or 1)
    return "", "", 0


def _base_config(step: PlanStep) -> dict[str, Any]:
    params = dict(step.params or {})
    return params


def _step_config(
    step: PlanStep,
    *,
    capabilities: dict[str, Any],
    steps_map: dict[str, str],
    step_by_id: dict[str, PlanStep],
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """Devuelve (node_type, config, ports)."""
    params = _base_config(step)
    node_type = step.type
    if step.type == "trigger_event":
        return (
            "trigger_event",
            {
                "event_type": str(params.get("event_type") or "workflow.run"),
                "filters": params.get("filters") or {},
            },
            {"inputs": [], "outputs": ["out"]},
        )
    if step.type == "trigger_schedule":
        schedule = params.get("schedule") if isinstance(params.get("schedule"), dict) else params
        return ("trigger_schedule", dict(schedule or {}), {"inputs": [], "outputs": ["out"]})
    if step.type == "trigger_manual":
        return ("trigger_webhook", {}, {"inputs": [], "outputs": ["out"]})
    if step.type == "business_query":
        return (
            "query_business_data",
            {"ask": str(params.get("ask") or step.goal)[:500]},
            {"inputs": ["in"], "outputs": ["out"]},
        )
    if step.type == "knowledge_query":
        known = capabilities.get("knowledge_bases") or []
        operation = str(params.get("operation") or default_knowledge_operation(step.goal))
        config: dict[str, Any] = {
            "operation": operation,
            "query": str(params.get("query") or step.goal)[:500],
            "limit": int(params.get("limit") or 5),
        }
        kb_id = str(params.get("knowledge_base_id") or (known[0] if known else ""))
        if kb_id:
            config["knowledge_base_id"] = kb_id
        if params.get("compare_left"):
            config["compare_left"] = str(params["compare_left"])
        if params.get("compare_right"):
            config["compare_right"] = str(params["compare_right"])
        if params.get("subject"):
            config["subject"] = str(params["subject"])
        return ("kb_query", config, {"inputs": ["in"], "outputs": ["out"]})
    if step.type == "agent_analysis":
        agent_id, agent_name, _score = _choose_agent(step, capabilities)
        selectors: list[str] = []
        for ref in step.inputs:
            source_node = steps_map.get(ref.step)
            if not source_node:
                continue
            source_step = step_by_id.get(ref.step)
            source_type = source_step.type if source_step else ""
            if source_type == "knowledge_query":
                selectors.append(f"knowledge:{source_node}")
                selectors.append("evidence")
                selectors.append("claims")
            elif source_type == "business_query":
                selectors.append(f"data:{source_node}")
        seen: set[str] = set()
        selectors = [item for item in selectors if not (item in seen or seen.add(item))]
        config = {
            "agent_id": agent_id,
            "agent_name": agent_name,
            "prompt": str(params.get("prompt") or step.goal)[:1000],
            "output_type": str(params.get("output_type") or "text"),
        }
        if selectors:
            config["context_mode"] = "manual"
            config["context_selectors"] = selectors
        else:
            config["context_mode"] = "auto"
        return ("llm", config, {"inputs": ["in"], "outputs": ["out"]})
    if step.type == "decision":
        rule = _decision_rule(step, steps_map)
        return ("condition", rule, {"inputs": ["in"], "outputs": ["out", "then", "else"]})
    if step.type == "human_approval":
        return (
            "human_approval",
            {
                "action": str(params.get("action") or step.goal)[:120],
                "expires_minutes": int(params.get("expires_minutes") or 1440),
            },
            {"inputs": ["in"], "outputs": ["out"]},
        )
    if step.type == "notify":
        return (
            "notify",
            {
                "channel": str(params.get("channel") or "in_app"),
                "title": str(params.get("title") or step.goal)[:200],
                "message": str(params.get("message") or step.goal)[:800],
                "recipients": params.get("recipients") or [],
            },
            {"inputs": ["in"], "outputs": ["out"]},
        )
    if step.type == "integration_action":
        action_id = str(params.get("action_id") or "")
        install_id = str(params.get("install_id") or "")
        if not install_id and action_id:
            for action in capabilities.get("actions") or []:
                if str(action.get("action_id")) == action_id:
                    install_id = str(action.get("install_id") or "")
                    break
        return (
            "marketplace_action",
            {
                "install_id": install_id,
                "action_id": action_id,
                "inputs": params.get("inputs") or {},
                "purpose": str(params.get("purpose") or "workflow architect")[:200],
            },
            {"inputs": ["in"], "outputs": ["out"]},
        )
    if step.type == "business_result":
        return (
            "business_result",
            {
                "title": str(params.get("title") or step.goal)[:200],
                "section": str(params.get("section") or "reports"),
                "importance": str(params.get("importance") or "INFO"),
            },
            {"inputs": ["in"], "outputs": ["out"]},
        )
    if step.type == "filter":
        items_ref = _input_ref(step, steps_map, default_field="rows")
        return (
            "filter",
            {
                "items": items_ref,
                "conditions": params.get("conditions") or [],
                "op": str(params.get("op") or "and"),
            },
            {"inputs": ["in"], "outputs": ["out"]},
        )
    if step.type == "for_each":
        return (
            "for_each",
            {
                "collection": _input_ref(step, steps_map, default_field="rows"),
                "max_iterations": int(params.get("max_iterations") or 50),
                "expected_items": params.get("expected_items"),
            },
            {"inputs": ["in"], "outputs": ["out", "done"]},
        )
    if step.type == "join":
        return ("join", {}, {"inputs": ["in"], "outputs": ["out"]})
    if step.type == "merge":
        return (
            "merge",
            {"strategy": str(params.get("strategy") or "first_available")},
            {"inputs": ["in"], "outputs": ["out"]},
        )
    if step.type == "stop":
        return (
            "stop",
            {
                "status": str(params.get("status") or "success"),
                "message": str(params.get("message") or ""),
            },
            {"inputs": ["in"], "outputs": ["out"]},
        )
    return node_type, {}, {"inputs": ["in"], "outputs": ["out"]}


def _decision_rule(step: PlanStep, steps_map: dict[str, str]) -> dict[str, Any]:
    params = step.params or {}
    if step.inputs:
        ref = step.inputs[0]
        node_id = steps_map.get(ref.step)
        if node_id:
            field = ref.field if ref.field != "output" else "result"
            return {
                "field": _ref(node_id, field),
                "operator": str(params.get("operator") or "=="),
                "value": params.get("value", True),
            }
    field = str(params.get("field") or "trigger.message")
    return {
        "field": field,
        "operator": str(params.get("operator") or "=="),
        "value": params.get("value", True),
    }


def _input_ref(step: PlanStep, steps_map: dict[str, str], *, default_field: str) -> str:
    if step.inputs:
        ref: PlanInputRef = step.inputs[0]
        node_id = steps_map.get(ref.step)
        if node_id:
            field = ref.field if ref.field != "output" else default_field
            return _ref(node_id, field)
    return f"{{{{trigger.{default_field}}}}}"


def compile_semantic_plan(
    plan: SemanticPlan,
    capabilities: dict[str, Any],
    *,
    intent: ArchitectIntent | None = None,
) -> dict[str, Any]:
    """Compila el plan semántico a WorkflowGraph v2 (determinístico)."""
    issues: list[PlanIssue] = []
    step_by_id = {step.id: step for step in plan.steps}

    used: set[str] = set()
    steps_map: dict[str, str] = {}
    node_types: dict[str, str] = {}
    for step in plan.steps:
        node_id = _node_id(step.id, used)
        steps_map[step.id] = node_id

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    levels: dict[str, int] = {}

    for step in plan.steps:
        node_id = steps_map[step.id]
        node_type, config, ports = _step_config(
            step,
            capabilities=capabilities,
            steps_map=steps_map,
            step_by_id=step_by_id,
        )
        node_types[step.id] = node_type
        input_ports = [{"name": "in", "type": "json"}] if "in" in ports["inputs"] else []
        output_ports = []
        for port in ports["outputs"]:
            port_type = "boolean" if (node_type == "condition" and port == "out") else "json"
            output_ports.append({"name": port, "type": port_type})
        nodes.append(
            {
                "id": node_id,
                "type": node_type,
                "label": str(step.params.get("label") or step.goal)[:80],
                "position": {"x": 0, "y": 0},
                "config": config,
                "input_ports": input_ports,
                "output_ports": output_ports,
                "retry_policy": {"max_attempts": 1},
                "timeout_ms": 60_000,
                "error_policy": "fail",
                "metadata": {
                    "architect": {
                        "step_id": step.id,
                        "reason": (step.reason_summary or step.goal)[:400],
                    }
                },
            }
        )

    trigger_step = next(
        (step for step in plan.steps if step.type.startswith("trigger_")), plan.steps[0]
    )
    entrypoints = [steps_map[trigger_step.id]]
    edge_index = 0
    for step in plan.steps:
        if step.id == trigger_step.id and not step.depends_on:
            continue
        sources = list(step.depends_on)
        if step.when is not None and step.when.step not in sources:
            sources.append(step.when.step)
        if not sources:
            sources = [trigger_step.id]
            issues.append(
                PlanIssue(
                    code="compile.implicit_trigger",
                    severity="warning",
                    step_id=step.id,
                    message=f"«{step.goal}» no declara de quién depende; se conectó al disparador.",
                )
            )
        for source_id in sources:
            source_node = steps_map.get(source_id)
            if not source_node:
                continue
            from_port = "out"
            if step.when is not None and step.when.step == source_id:
                from_port = "then" if step.when.outcome else "else"
            edge_index += 1
            edges.append(
                {
                    "id": f"e{edge_index}",
                    "from_node": source_node,
                    "from_port": from_port,
                    "to_node": steps_map[step.id],
                    "to_port": "in",
                }
            )
        levels[step.id] = 1 + max((levels.get(source, 0) for source in sources), default=0)

    per_level: dict[int, int] = {}
    for node in nodes:
        step_id = node["metadata"]["architect"]["step_id"]
        level = levels.get(step_id, 0)
        index = per_level.get(level, 0)
        per_level[level] = index + 1
        node["position"] = {"x": 120 + level * 300, "y": 80 + index * 140}

    graph = {
        "workflow_version": 2,
        "nodes": nodes,
        "edges": edges,
        "variables": {},
        "entrypoints": entrypoints,
        "metadata": {"architect": True, "goal": plan.goal},
    }
    return {
        "graph": graph,
        "steps_map": steps_map,
        "node_types": node_types,
        "issues": issues,
    }


__all__ = ["compile_semantic_plan", "default_knowledge_operation"]
