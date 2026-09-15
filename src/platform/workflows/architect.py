# =============================================================================
# Workflow Architect — orquestador (First delivery, brief §34).
#
# TEXT → ArchitectIntent → SemanticPlan → validation → WorkflowGraph draft.
# El LLM propone; el código valida y compila. Fallback heurístico sin LLM.
# =============================================================================
from __future__ import annotations

import json
import re
from typing import Any
from uuid import UUID

from src.infrastructure.observability.logging_config import get_logger
from src.platform.workflows.architect_clarifications import (
    build_clarifications,
    build_requirements,
)
from src.platform.workflows.architect_compiler import (
    compile_semantic_plan,
    default_knowledge_operation,
)
from src.platform.workflows.architect_discovery import (
    capability_digest,
    discover_capabilities,
)
from src.platform.workflows.architect_models import (
    ArchitectIntent,
    PlanAssumption,
    PlanStep,
    SemanticPlan,
)
from src.platform.workflows.architect_validator import validate_semantic_plan

logger = get_logger(__name__)

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)

INTENT_SYSTEM_PROMPT = """Eres el arquitecto de automatizaciones de Zent.
Convierte la petición del usuario en un ArchitectIntent JSON. Reglas:
- Responde SOLO con un objeto JSON, sin markdown.
- Shape:
{
  "goal": str,
  "trigger_intent": {"kind": "event"|"schedule"|"manual"|"webhook", "event_type": str|null,
                     "description": str|null},
  "inputs_needed": [str], "data_needs": [str], "knowledge_needs": [str],
  "reasoning_needs": [str], "conditions": [str], "actions": [str],
  "approval_needs": [str], "schedule": {"daily": "HH:MM", "timezone": str}|null,
  "output": [str], "constraints": [str],
  "uncertainties": [str], "missing_information": [str],
  "assumptions": [{"statement": str, "impact": "low"|"high", "needs_confirmation": bool}],
  "confidence": 0.0-1.0
}
- No inventes integraciones, agentes ni bases de conocimiento: si faltan, ponlos en
  "missing_information" y baja "confidence".
- "reasoning_needs": solo si hace falta criterio/interpretación; reglas simples no llevan agente.
"""

PLAN_SYSTEM_PROMPT = """Eres el arquitecto de automatizaciones de Zent.
Convierte el ArchitectIntent en un SemanticPlan JSON de pasos de NEGOCIO. Reglas:
- Responde SOLO con un objeto JSON, sin markdown. Sin ids de nodo, sin posiciones, sin {{...}}.
- Shape:
{
  "goal": str,
  "steps": [{
    "id": "t1", "type": "trigger_event"|"trigger_schedule"|"trigger_manual"|"business_query"|
            "knowledge_query"|"agent_analysis"|"decision"|"filter"|"for_each"|"join"|"merge"|
            "human_approval"|"notify"|"integration_action"|"business_result"|"stop",
    "goal": str, "depends_on": [str], "when": {"step": str, "outcome": true}|null,
    "inputs": [{"step": str, "field": str, "label": str|null}],
    "params": {}, "reason_summary": str, "optional": false
  }],
  "assumptions": [{"statement": str, "impact": "low"|"high", "needs_confirmation": bool}],
  "uncertainties": [str], "notes": [str]
}
- Un solo disparador. Cada paso declara de quién depende (depends_on).
- Usa un agente SOLO cuando haga falta criterio; si una regla simple alcanza, no lo pongas.
- knowledge_query: params.operation ∈ search|answer|find_evidence|extract_facts|compare|check_conflicts|investigate.
- decision: referencia al paso que decide en "inputs" (p. ej. agente → field "risk" o "requires_review").
- notify/integration_action solo con canales/acciones disponibles en el contexto.
"""


def _parse_json_object(text: str) -> dict[str, Any] | None:
    match = _JSON_OBJECT_RE.search(text or "")
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _resolve_provider(provider: Any = None) -> Any:
    if provider is not None:
        return provider
    from src.platform.workflows.copilot_v2 import _resolve_llm_provider

    return _resolve_llm_provider(None)


async def _generate_json(
    provider: Any, *, system: str, prompt: str, model: str | None, max_tokens: int
) -> dict[str, Any]:
    response = await provider.generate(
        prompt=prompt,
        system_prompt=system,
        model=model,
        temperature=0.0,
        max_tokens=max_tokens,
    )
    content = getattr(response, "content", None)
    if content is None and isinstance(response, dict):
        content = response.get("content")
    data = _parse_json_object(str(content or ""))
    if data is None:
        raise ValueError("el LLM no devolvió un JSON válido")
    return data


async def extract_intent_with_architect(
    prompt: str,
    *,
    capabilities: dict[str, Any],
    provider: Any,
    model: str | None = None,
) -> ArchitectIntent:
    system = INTENT_SYSTEM_PROMPT + "\nCapacidades del tenant:\n" + capability_digest(capabilities)
    data = await _generate_json(
        provider, system=system, prompt=prompt, model=model, max_tokens=1200
    )
    data.setdefault("raw_prompt", prompt[:2000])
    return ArchitectIntent.model_validate(data)


async def extract_plan_with_architect(
    intent: ArchitectIntent,
    *,
    capabilities: dict[str, Any],
    provider: Any,
    model: str | None = None,
) -> SemanticPlan:
    system = PLAN_SYSTEM_PROMPT + "\nCapacidades del tenant:\n" + capability_digest(capabilities)
    prompt = (
        "ArchitectIntent:\n"
        + json.dumps(intent.model_dump(mode="json"), ensure_ascii=False)
        + "\n\nPlanifica los pasos de negocio."
    )
    data = await _generate_json(
        provider, system=system, prompt=prompt, model=model, max_tokens=2000
    )
    if not data.get("goal"):
        data["goal"] = intent.goal
    return SemanticPlan.model_validate(data)


def _legacy_step_to_plan(step_type: str, config: dict[str, Any], step_id: str) -> PlanStep | None:
    if step_type == "query_business_data":
        return PlanStep(
            type="business_query",
            id=step_id,
            goal="Consultar datos de negocio",
            params={"ask": config.get("ask")},
        )
    if step_type == "kb_query":
        return PlanStep(
            type="knowledge_query",
            id=step_id,
            goal="Consultar conocimiento",
            params={
                "operation": config.get("operation") or default_knowledge_operation(str(config.get("query") or "")),
                "query": config.get("query"),
            },
        )
    if step_type == "llm":
        return PlanStep(
            type="agent_analysis",
            id=step_id,
            goal="Analizar la situación",
            params={"prompt": config.get("prompt"), "output_type": config.get("output_type") or "text"},
        )
    if step_type == "condition":
        return PlanStep(
            type="decision",
            id=step_id,
            goal="Tomar una decisión",
            params={
                "field": config.get("field"),
                "operator": config.get("operator") or "==",
                "value": config.get("value", True),
            },
        )
    if step_type == "notify":
        return PlanStep(
            type="notify",
            id=step_id,
            goal="Avisar",
            params={"channel": "in_app", "title": config.get("title"), "message": config.get("message")},
        )
    if step_type == "marketplace_action":
        return PlanStep(
            type="integration_action",
            id=step_id,
            goal="Usar integración",
            params={
                "action_id": config.get("action_id"),
                "install_id": config.get("install_id"),
                "inputs": config.get("inputs") or {},
            },
        )
    if step_type == "business_result":
        return PlanStep(
            type="business_result",
            id=step_id,
            goal="Publicar resultado",
            params={"title": config.get("title")},
        )
    return None


def heuristic_semantic_plan(prompt: str) -> SemanticPlan:
    """Fallback determinístico (legacy `build_draft`) mapeado a plan semántico."""
    from src.platform.workflows.copilot import build_draft

    draft = build_draft(prompt)
    trigger_config = draft.trigger_config or {}
    steps: list[PlanStep] = []
    counter = 0

    def next_id() -> str:
        nonlocal counter
        counter += 1
        return f"s{counter}"

    if draft.trigger_type == "event":
        steps.append(
            PlanStep(
                id=next_id(),
                type="trigger_event",
                goal=draft.name,
                params={
                    "event_type": str(trigger_config.get("event_type") or "workflow.run"),
                    "filters": trigger_config.get("filters") or {},
                },
                reason_summary="El pedido reacciona a un evento del negocio.",
            )
        )
    elif draft.trigger_type == "schedule":
        schedule = trigger_config if trigger_config else {"every_minutes": 60}
        steps.append(
            PlanStep(
                id=next_id(),
                type="trigger_schedule",
                goal=draft.name,
                params=dict(schedule),
                reason_summary="El pedido pide una frecuencia.",
            )
        )
    else:
        steps.append(
            PlanStep(id=next_id(), type="trigger_manual", goal=draft.name, reason_summary="Inicio manual.")
        )

    previous = steps[0].id
    for raw in draft.steps or []:
        step_type = str((raw or {}).get("type") or "")
        config = (raw or {}).get("config") or {}
        mapped = _legacy_step_to_plan(step_type, config, next_id())
        if mapped is None:
            continue
        mapped = mapped.model_copy(update={"depends_on": [previous]})
        steps.append(mapped)
        previous = mapped.id
    assumptions = [
        PlanAssumption(statement="Usaremos el espacio de trabajo actual.", impact="low"),
    ]
    if draft.questions:
        assumptions.append(
            PlanAssumption(
                statement="Hay datos por confirmar: " + "; ".join(draft.questions[:3]),
                impact="high",
                needs_confirmation=True,
            )
        )
    return SemanticPlan(
        goal=draft.name,
        steps=steps,
        assumptions=assumptions,
        notes=["Plan generado con reglas (sin LLM); revísalo antes de publicar."],
    )


_PREVIEW_KIND_BY_TYPE: dict[str, str] = {
    "trigger_event": "when",
    "trigger_schedule": "when",
    "trigger_manual": "when",
    "business_query": "get",
    "knowledge_query": "consult",
    "agent_analysis": "analyze",
    "decision": "if",
    "filter": "get",
    "for_each": "then",
    "join": "then",
    "merge": "then",
    "human_approval": "then",
    "notify": "after",
    "integration_action": "then",
    "business_result": "after",
    "stop": "then",
}


def semantic_preview(plan: SemanticPlan) -> list[dict[str, str]]:
    """Preview de negocio: qué entendí, en orden (brief §14)."""
    preview: list[dict[str, str]] = []
    for step in plan.steps:
        kind = _PREVIEW_KIND_BY_TYPE.get(step.type, "then")
        text = step.goal
        if step.type == "trigger_event":
            event_type = str(step.params.get("event_type") or "un evento")
            text = f"Cuando ocurra «{event_type}»."
        elif step.type == "trigger_schedule":
            schedule = step.params or {}
            if schedule.get("daily"):
                daily = schedule["daily"]
                time = daily.get("time") if isinstance(daily, dict) else str(daily)
                text = f"Programado todos los días a las {time}."
            elif schedule.get("every_minutes"):
                text = f"Cada {schedule['every_minutes']} minutos."
            else:
                text = "Según la programación configurada."
        elif step.type == "agent_analysis":
            agent_name = str(step.params.get("agent_name") or "")
            text = f"Analizar con {agent_name or 'un agente'}: {step.goal}"
        elif step.type == "notify":
            text = f"Avisar por {step.params.get('channel') or 'Zent'}: {step.goal}"
        elif step.type == "human_approval":
            text = f"Pedir aprobación humana: {step.params.get('action') or step.goal}"
        preview.append({"kind": kind, "step_id": step.id, "text": text})
    return preview


def _trigger_config_for_cost(plan: SemanticPlan) -> dict[str, Any]:
    for step in plan.steps:
        if step.type == "trigger_event":
            return {"event_type": str(step.params.get("event_type") or "")}
        if step.type == "trigger_schedule":
            schedule = step.params or {}
            daily = schedule.get("daily")
            if isinstance(daily, dict):
                schedule = {**schedule, "daily": daily.get("time")}
            return dict(schedule)
    return {}


async def patch_workflow_plan(
    organization_id: UUID,
    plan: dict[str, Any],
    instruction: str,
    *,
    workspace_id: UUID | None = None,
    permissions: frozenset[str] | None = None,
    provider: Any = None,
    model: str | None = None,
    capabilities: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Patch conversacional: aplica sobre el plan, re-valida y recompila."""
    from src.platform.workflows.architect_patch import (
        apply_semantic_patch,
        propose_plan_patch,
    )

    semantic_plan = SemanticPlan.model_validate(plan)
    if capabilities is None:
        capabilities = await discover_capabilities(
            organization_id, workspace_id=workspace_id, permissions=permissions
        )
    notes: list[str] = []
    source = "llm"
    try:
        resolved = _resolve_provider(provider)
        patch = await propose_plan_patch(
            semantic_plan, instruction, provider=resolved, model=model
        )
    except Exception as exc:  # noqa: BLE001 — fallback determinístico
        logger.info("architect patch: fallback", error=str(exc)[:200])
        patch = heuristic_plan_patch(instruction, semantic_plan)
        source = "heuristics"
        if patch is None:
            raise ValueError(
                "No pude interpretar el cambio; prueba «cambia el umbral a 50000», "
                "«quita la aprobación» o «solo lunes a viernes»."
            ) from exc
    updated, notes = apply_semantic_patch(semantic_plan, patch)
    issues = validate_semantic_plan(updated, capabilities, permissions=permissions)
    graph: dict[str, Any] | None = None
    cost: dict[str, Any] | None = None
    if not any(issue.severity == "error" for issue in issues):
        compiled = compile_semantic_plan(updated, capabilities)
        graph = compiled["graph"]
        issues = [*issues, *compiled["issues"]]
        try:
            from src.platform.workflows.capabilities import cost_estimate

            cost = await cost_estimate(organization_id, graph, _trigger_config_for_cost(updated))
        except Exception as exc:  # noqa: BLE001
            logger.warning("architect patch cost failed", error=str(exc)[:150])
    try:
        from src.platform.workflows.architect_metrics import record_revision

        record_revision()
    except Exception as exc:  # noqa: BLE001
        logger.warning("architect revision metric failed", error=str(exc)[:150])
    clarifications = build_clarifications(updated, issues)
    return {
        "source": source,
        "plan": updated.model_dump(mode="json"),
        "patch": patch.model_dump(mode="json"),
        "issues": [issue.model_dump(mode="json") for issue in issues],
        "preview": semantic_preview(updated),
        "graph": graph,
        "cost": cost,
        "clarifications": clarifications,
        "requirements": build_requirements(issues),
        "readiness": _readiness(graph, capabilities) if graph is not None else None,
        "simulation": simulation_plan(updated) if graph is not None else None,
        "notes": notes,
    }


def heuristic_plan_patch(instruction: str, plan: SemanticPlan) -> Any:
    """Patch determinístico para cambios comunes (sin LLM)."""
    from src.platform.workflows.architect_patch import PlanPatchOp, SemanticPlanPatch

    text = str(instruction or "").lower()
    operations: list[PlanPatchOp] = []
    approval = next((step for step in plan.steps if step.type == "human_approval"), None)
    if approval is not None and (
        "quita" in text and "aprob" in text or "sin aprobacion" in text or "sin aprobación" in text
    ):
        operations.append(
            PlanPatchOp(kind="remove_step", step_id=approval.id, reason="Quitar la aprobación")
        )
    decision = next((step for step in plan.steps if step.type == "decision"), None)
    threshold = re.search(r"(\d[\d.,]{2,})", text)
    if decision is not None and threshold and ("umbral" in text or "mayor" in text or "sobre" in text):
        raw = threshold.group(1).replace(".", "").replace(",", "")
        try:
            value: Any = float(raw) if "." in raw else int(raw)
        except ValueError:
            value = threshold.group(1)
        operations.append(
            PlanPatchOp(
                kind="set_param",
                step_id=decision.id,
                key="value",
                value=value,
                reason=f"Umbral {value}",
            )
        )
    if "lunes a viernes" in text and any(step.type == "trigger_schedule" for step in plan.steps):
        operations.append(
            PlanPatchOp(
                kind="set_schedule",
                params={
                    "weekly": {"days": [0, 1, 2, 3, 4], "time": "08:00"},
                    "daily": None,
                },
                reason="Solo días hábiles",
            )
        )
    if not operations:
        return None
    return SemanticPlanPatch(operations=operations, summary=instruction[:200])


def _readiness(graph: dict[str, Any], capabilities: dict[str, Any]) -> dict[str, Any]:
    """Readiness de negocio del grafo compilado (brief §26)."""
    from src.platform.workflows.readiness import readiness_checks

    caps = {
        "agents": {
            str(agent["id"]): str(agent.get("name") or "")
            for agent in capabilities.get("agents") or []
        },
        "knowledge_bases": {
            str(kb): str(kb) for kb in capabilities.get("knowledge_bases") or []
        },
        "actions": {
            str(action.get("action_id")): action
            for action in capabilities.get("actions") or []
        },
    }
    checks = readiness_checks(graph, caps)
    return {
        "ready": not [check for check in checks if check.get("status") == "error"],
        "checks": checks,
        "passed": len([check for check in checks if check.get("status") == "ok"]),
        "warnings": len([check for check in checks if check.get("status") == "warning"]),
        "errors": len([check for check in checks if check.get("status") == "error"]),
        "total": len(checks),
    }


_KNOWLEDGE_SIMULATION: dict[str, str] = {
    "answer": "Respondería citando los fragmentos encontrados.",
    "find_evidence": "Devolvería evidencia localizable para la afirmación.",
    "compare": "Compararía ambos lados y listaría diferencias.",
    "check_conflicts": "Buscaría contradicciones entre claims.",
    "extract_facts": "Extraería hechos propuestos con su evidencia.",
    "investigate": "Investigaría con el presupuesto definido.",
    "search": "Buscaría fragmentos relevantes.",
}


def simulation_plan(plan: SemanticPlan) -> list[dict[str, str]]:
    """Vista previa de ejecución sin efectos (brief §23)."""
    entries: list[dict[str, str]] = []
    for step in plan.steps:
        if step.type == "trigger_event":
            expectation = (
                f"Recibiría un ejemplo del evento «{step.params.get('event_type') or 'evento'}»."
            )
        elif step.type == "trigger_schedule":
            expectation = "Se ejecutaría según la programación."
        elif step.type == "trigger_manual":
            expectation = "Inicio manual."
        elif step.type == "business_query":
            expectation = "Consulta OK: filas de ejemplo (sin SQL real en la vista previa)."
        elif step.type == "knowledge_query":
            operation = str(step.params.get("operation") or "search")
            expectation = _KNOWLEDGE_SIMULATION.get(operation, "Buscaría conocimiento.")
        elif step.type == "agent_analysis":
            agent_name = str(step.params.get("agent_name") or "el agente")
            expectation = f"{agent_name} respondería una conclusión (sin efecto real)."
        elif step.type == "decision":
            expectation = "Evaluaría la regla y elegiría una rama."
        elif step.type == "human_approval":
            expectation = "Se pediría aprobación; nunca se aprueba solo."
        elif step.type == "notify":
            expectation = "Aviso simulado (sin envío)."
        elif step.type == "integration_action":
            expectation = "Acción simulada (sin efectos externos)."
        elif step.type == "business_result":
            expectation = "Resultado simulado (nada se publica)."
        elif step.type == "filter":
            expectation = "Filtraría la lista de ejemplo."
        elif step.type == "for_each":
            expectation = "Repetiría por cada elemento de ejemplo."
        elif step.type == "join":
            expectation = "Esperaría ambas ramas."
        elif step.type == "merge":
            expectation = "Elegiría la primera rama disponible."
        elif step.type == "stop":
            expectation = "Terminaría el flujo."
        else:
            expectation = "Se ejecutaría el paso."
        entries.append(
            {"step_id": step.id, "goal": step.goal, "expectation": expectation, "effects": "none"}
        )
    return entries


async def plan_workflow(
    organization_id: UUID,
    prompt: str,
    *,
    workspace_id: UUID | None = None,
    permissions: frozenset[str] | None = None,
    provider: Any = None,
    model: str | None = None,
    capabilities: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Pipeline completo (sin persistir): intent → plan → validación → grafo."""
    if capabilities is None:
        capabilities = await discover_capabilities(
            organization_id, workspace_id=workspace_id, permissions=permissions
        )
    source = "llm"
    intent: ArchitectIntent | None = None
    plan: SemanticPlan | None = None
    notes: list[str] = []
    try:
        resolved = _resolve_provider(provider)
        intent = await extract_intent_with_architect(
            prompt, capabilities=capabilities, provider=resolved, model=model
        )
        plan = await extract_plan_with_architect(
            intent, capabilities=capabilities, provider=resolved, model=model
        )
    except Exception as exc:  # noqa: BLE001 — fallback determinístico
        logger.info("architect: fallback heurístico", error=str(exc)[:200])
        source = "heuristics"
        intent = None
        plan = heuristic_semantic_plan(prompt)
        notes.append("No pude usar el modelo; armé un plan con reglas. Revísalo.")

    issues = validate_semantic_plan(plan, capabilities, permissions=permissions)
    graph: dict[str, Any] | None = None
    steps_map: dict[str, str] = {}
    cost: dict[str, Any] | None = None
    if not any(issue.severity == "error" for issue in issues):
        compiled = compile_semantic_plan(plan, capabilities, intent=intent)
        graph = compiled["graph"]
        steps_map = compiled["steps_map"]
        issues = [*issues, *compiled["issues"]]
        try:
            from src.platform.workflows.capabilities import cost_estimate

            cost = await cost_estimate(
                organization_id, graph, _trigger_config_for_cost(plan)
            )
        except Exception as exc:  # noqa: BLE001 — costo best-effort
            logger.warning("architect cost estimate failed", error=str(exc)[:200])

    questions = [
        issue.message
        for issue in issues
        if issue.severity == "warning" and issue.code.startswith(("missing.", "assumption."))
    ]
    clarifications = build_clarifications(plan, issues, intent=intent)
    requirements = build_requirements(issues)
    readiness = _readiness(graph, capabilities) if graph is not None else None
    simulation = simulation_plan(plan) if graph is not None else None
    has_agent = any(step.type == "agent_analysis" for step in plan.steps)
    unnecessary_agent = bool(has_agent and intent is not None and not intent.reasoning_needs)
    try:
        from src.platform.workflows.architect_metrics import record_plan_outcome

        record_plan_outcome(
            valid=not any(issue.severity == "error" for issue in issues),
            compiled=graph is not None,
            clarifications=len(clarifications),
            requirements=len(requirements),
            unnecessary_agent=unnecessary_agent,
        )
    except Exception as exc:  # noqa: BLE001 — métricas no rompen el plan
        logger.warning("architect metrics failed", error=str(exc)[:150])
    return {
        "source": source,
        "intent": intent.model_dump(mode="json") if intent is not None else None,
        "plan": plan.model_dump(mode="json"),
        "issues": [issue.model_dump(mode="json") for issue in issues],
        "preview": semantic_preview(plan),
        "graph": graph,
        "steps_map": steps_map,
        "cost": cost,
        "assumptions": [assumption.model_dump(mode="json") for assumption in plan.assumptions],
        "questions": questions,
        "clarifications": clarifications,
        "requirements": requirements,
        "readiness": readiness,
        "simulation": simulation,
        "notes": notes,
    }


__all__ = [
    "extract_intent_with_architect",
    "extract_plan_with_architect",
    "heuristic_plan_patch",
    "heuristic_semantic_plan",
    "patch_workflow_plan",
    "plan_workflow",
    "semantic_preview",
    "simulation_plan",
]
