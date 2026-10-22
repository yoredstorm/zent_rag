# =============================================================================
# Workflow Architect — orquestador (First delivery, brief §34).
#
# TEXT → ArchitectIntent → SemanticPlan → validation → WorkflowGraph draft.
# El LLM propone; el código valida y compila. Fallback heurístico sin LLM.
# =============================================================================
from __future__ import annotations

import json
import re
import time
from typing import Any
from uuid import UUID

from pydantic import ValidationError

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
    PlanIssue,
    PlanStep,
    SemanticPlan,
)
from src.platform.workflows.architect_observability import (
    PLANNER_VERSION,
    STATE_BLOCKED,
    STATE_DRAFT_READY,
    ArchitectBlocked,
    PlanHashMismatch,
    build_blockers,
    design_state,
    elapsed_ms,
    fallback_payload,
    log_design,
    normalize_session_id,
    plan_hash,
    prompt_hash,
    provider_info,
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
  "schema_version": "2.0",
  "goal": str,
  "steps": [{
    "id": "t1", "type": "trigger_conversation"|"trigger_event"|"trigger_schedule"|"trigger_manual"|"business_query"|
            "knowledge_query"|"capability_call"|"agent_analysis"|"decision"|"filter"|"join"|"merge"|
            "human_approval"|"wait"|"state"|"loop"|"compensation"|"notify"|"integration_action"|
            "business_result"|"stop",
    "goal": str, "depends_on": [str], "when": {"step": str, "outcome": true}|null,
    "inputs": [{"step": str, "field": str, "label": str|null, "to": str|null}],
    "params": {}, "reason_summary": str, "optional": false,
    "retries": 0, "timeout_seconds": 60, "on_error": "fail"|"continue"|"stop",
    "contract_version": int|null, "outputs_expected": [str],
    "idempotency": "required"|"best_effort"|"none"
  }],
  "assumptions": [{"statement": str, "impact": "low"|"high", "needs_confirmation": bool}],
  "uncertainties": [str], "notes": [str]
}
- Un solo disparador. Cada paso declara de quién depende (depends_on).
- Máximo 15 pasos. No dupliques pasos de conversación, validación o confirmación:
  cada uno debe tener una responsabilidad distinta y un `id` estable.
- Patrones de negocio (úsalos como guía, no como texto a copiar):
  venta: trigger_conversation → agent_analysis → catalog.products.search
  (incluye price/stock de cada alternativa) → state(set cart_lines) →
  wait(message) → sales.cart.quote → human_approval → sales.order.create →
  payments.checkout.create → wait(payment) → sales.order.mark_paid →
  inventory.commit → notify.
  mentoría: trigger_manual/schedule → agent_analysis (nivel) → knowledge_query →
  business_result → state(progress) → wait/schedule.
  auditoría: trigger_event(document.uploaded) → knowledge_query/query_business_data →
  decision(differences) → human_approval → business_result.
  soporte: trigger_conversation → knowledge_query → agent_analysis →
  decision(resolved) → notify o human_approval (escalar).
  bienestar: trigger_conversation → agent_analysis (contención) → knowledge_query
  (recursos) → decision(crisis) → human_approval/derivación → conversation.send.
- No uses "for_each": el plan semántico no expresa cuerpos de iteración; divide el flujo en pasos.
- capability_call: params.capability debe ser una ref EXACTA de una capacidad que
  exista en el catálogo del tenant. Si no la has inspeccionado, búscala primero.
  params.inputs lleva valores literales. Para usar la salida de otro paso, agrega
  en "inputs" {"step": "<paso>", "field": "<campo de salida>", "to": "<campo de entrada>"}.
  Si la capacidad está NEEDS_CONFIGURATION, no la uses como si estuviera activa.
- loop: params.target = id de un paso anterior, params.max_iterations entre 1 y 100,
  params.exit_condition y params.state_dependencies cuando apliquen. El flujo debe
  ejecutarse como proceso durable; no lo uses para reemplazar una decisión.
- wait: declara params.preset, params.event_type, params.correlation (por ejemplo
  {"order_id": {"step": "crear", "field": "order_id"}}), timeout_seconds,
  on_timeout y expected_payload_schema. Si on_timeout="branch", agrega un paso con
  when {"step": "<wait>", "outcome": false} para el timeout. No bloquees un worker.
- state: params.op, params.path, params.value_type y, si viene de otro paso,
  params.source_reference {"step": str, "field": str}.
- compensation: params.target_step apunta a la capacidad/acción anterior;
  declara params.capability o params.action_id, inputs e idempotency="required".
  La rama de compensación debe terminar en stop(status="failed") o business_result.
- trigger_conversation inicia con conversation.message; no inventes otro evento.
- Usa un agente SOLO cuando haga falta criterio; si una regla simple alcanza, no lo pongas.
- knowledge_query: params.operation ∈ search|answer|find_evidence|extract_facts|compare|check_conflicts|investigate.
- decision: referencia al paso que decide en "inputs" (p. ej. agente → field "risk" o "requires_review").
- wait: proceso durable que espera un evento externo (params.preset ∈ message|payment|webhook|timer|human|signal;
  params.timeout_seconds; params.on_timeout ∈ branch|expire|fail|continue). El flujo corre como proceso vivo.
- state: estado durable del proceso (params.op ∈ get|set|merge|append|remove, params.path, params.value).
- notify/integration_action solo con canales/acciones disponibles en el contexto.
- Toda capacidad financiera o crítica (payments.*, sales.order.mark_paid,
  refunds, acciones con risk_level=critical) DEBE tener un paso human_approval
  ancestro antes de ejecutarse. Si falta, el plan se rechaza.
- Cada capability_call, integration_action y agent_analysis debe tener su fila
  en matches con la ref exacta y la razón. Sin match, el plan se rechaza.
- `when` solo puede apuntar a un paso `decision` o `wait` con dos resultados.
  No ramifiques directamente desde `agent_analysis`; agrega un `decision`.
- El plan debe terminar en `notify`, `business_result` o `stop`.
- No declares supuestos `impact=high` si la capacidad ya está AVAILABLE en la
  digest; usa `low` o pide clarificación.
- No conectes un array a un input escalar. Si `catalog.products.search` ya
  devuelve productos con precio, usa ese resultado; no llames
  `catalog.product.price` por cada ítem ni inventes un bucle.
- Campos de salida: `decision` expone `result` (no `outcome`); `wait` expone
  `message`, `status`, `port`, `payload`; `state` expone `value`. Usa esos
  nombres exactos en `inputs.field`.
"""


def _parse_json_object(text: str) -> dict[str, Any] | None:
    from src.platform.workflows.json_output import parse_json_object

    return parse_json_object(text)


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
    system = (
        INTENT_SYSTEM_PROMPT
        + "\nCapacidades del tenant:\n"
        + capability_digest(capabilities, query=prompt)
    )
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
    query = " ".join(
        item for item in (intent.goal, intent.raw_prompt or "") if item
    )
    system = (
        PLAN_SYSTEM_PROMPT
        + "\nCapacidades del tenant:\n"
        + capability_digest(capabilities, query=query)
    )
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
        uncertainties=[str(item)[:400] for item in (draft.questions or [])][:10],
        notes=["Plan generado con reglas (sin LLM); revísalo antes de publicar."],
    )


_PREVIEW_KIND_BY_TYPE: dict[str, str] = {
    "trigger_conversation": "when",
    "trigger_event": "when",
    "trigger_schedule": "when",
    "trigger_manual": "when",
    "business_query": "get",
    "knowledge_query": "consult",
    "capability_call": "then",
    "agent_analysis": "analyze",
    "decision": "if",
    "filter": "get",
    "for_each": "then",
    "join": "then",
    "merge": "then",
    "human_approval": "then",
    "state": "then",
    "loop": "then",
    "compensation": "then",
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
        if step.type == "trigger_conversation":
            text = "Cuando el cliente inicie o responda una conversación."
        elif step.type == "trigger_event":
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
        elif step.type == "capability_call":
            text = f"Ejecutar {step.params.get('capability') or 'una capacidad'}: {step.goal}"
        elif step.type == "loop":
            text = f"Volver a un paso anterior (máx. {step.params.get('max_iterations') or 20} veces)."
        elif step.type == "compensation":
            text = (
                f"Si falla {step.params.get('target_step') or 'la acción'}, "
                f"compensar con {step.params.get('capability') or step.params.get('action_id') or 'una acción'}."
            )
        elif step.type == "notify":
            text = f"Avisar por {step.params.get('channel') or 'Zent'}: {step.goal}"
        elif step.type == "human_approval":
            text = f"Pedir aprobación humana: {step.params.get('action') or step.goal}"
        preview.append({"kind": kind, "step_id": step.id, "text": text})
    return preview


def _apply_preferred_agent(
    plan: SemanticPlan,
    capabilities: dict[str, Any],
    preferred_agent_id: str | None,
) -> tuple[SemanticPlan, list[PlanIssue]]:
    """Asocia el asistente elegido a los pasos de IA que no fijaron uno.

    Solo actúa si el agente realmente existe para el tenant; si no, devuelve un
    warning para que la UI lo muestre (nunca inventa un agente).
    """
    agent_id = str(preferred_agent_id or "").strip()
    if not agent_id:
        return plan, []
    agents = {
        str(agent.get("id")): agent for agent in (capabilities.get("agents") or [])
    }
    if agent_id not in agents:
        return plan, [
            PlanIssue(
                code="plan.preferred_agent_unavailable",
                severity="warning",
                message=(
                    "El asistente elegido no está disponible en este espacio; "
                    "elige uno antes de publicar."
                ),
                requirement="agents",
            )
        ]
    changed = False
    steps: list[PlanStep] = []
    for step in plan.steps:
        if step.type == "agent_analysis" and not str(step.params.get("agent_id") or "").strip():
            steps.append(
                step.model_copy(
                    update={
                        "params": {
                            **step.params,
                            "agent_id": agent_id,
                            "agent_name": str(agents[agent_id].get("name") or ""),
                        }
                    }
                )
            )
            changed = True
        else:
            steps.append(step)
    if not changed:
        return plan, []
    return plan.model_copy(update={"steps": steps}), []


def _trigger_config_for_cost(plan: SemanticPlan) -> dict[str, Any]:
    for step in plan.steps:
        if step.type == "trigger_conversation":
            return {"event_type": str(step.params.get("event_type") or "conversation.message")}
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
    session_id: str | None = None,
    plan_hash_value: str | None = None,
    actor_id: UUID | None = None,
    proposed_patch: dict[str, Any] | None = None,
    proposed_source: str = "llm",
    preview_only: bool = False,
) -> dict[str, Any]:
    """Patch conversacional: aplica sobre el plan, re-valida y recompila.

    `proposed_patch` permite aplicar un diff ya previsualizado y confirmado sin
    volver a llamar al modelo ni confiar en el grafo del cliente.
    """
    from src.platform.workflows.architect_patch import (
        SemanticPlanPatch,
        apply_semantic_patch,
        propose_plan_patch,
        semantic_plan_diff,
    )

    session = normalize_session_id(session_id)
    started = time.monotonic()
    phases: list[dict[str, Any]] = []
    semantic_plan = SemanticPlan.model_validate(plan)
    if plan_hash_value and plan_hash(semantic_plan) != plan_hash_value:
        raise PlanHashMismatch(
            "El plan cambió desde que abriste la edición; vuelve a interpretar antes de aplicar el cambio."
        )
    not_found_reason: str | None = None
    phase_started = time.monotonic()
    if capabilities is None:
        capabilities = await discover_capabilities(
            organization_id, workspace_id=workspace_id, permissions=permissions
        )
    phases.append({"name": "discovery", "duration_ms": elapsed_ms(phase_started)})

    notes: list[str] = []
    source = "llm"
    resolved = None
    patch = None
    fallback: dict[str, Any] | None = None
    phase_started = time.monotonic()
    if proposed_patch is not None:
        try:
            patch = SemanticPlanPatch.model_validate(proposed_patch)
            notes.append("Cambio confirmado desde la previsualización.")
            source = "heuristics" if proposed_source == "heuristics" else "llm"
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"patch confirmado inválido: {str(exc)[:200]}") from exc
    else:
        try:
            resolved = _resolve_provider(provider)
            patch = await propose_plan_patch(
                semantic_plan, instruction, provider=resolved, model=model
            )
        except Exception as exc:  # noqa: BLE001 — fallback determinístico
            logger.info(
                "architect patch: fallback",
                error_type=type(exc).__name__,
                session_id=session,
            )
            patch = heuristic_plan_patch(instruction, semantic_plan)
            source = "heuristics"
            if patch is None:
                not_found_reason = (
                    "No pude interpretar el cambio; prueba «cambia el umbral a 50000», "
                    "«quita la aprobación» o «solo lunes a viernes»."
                )
            else:
                fallback = {
                    "used": True,
                    "reason_code": _fallback_reason(exc),
                    "limitations": [
                        "El cambio se interpretó con reglas determinísticas; revisa el resultado.",
                    ],
                    "requires_review": True,
                    "publishable": False,
                    "preserved_requirement": instruction[:600],
                }
    if not_found_reason is not None:
        raise ValueError(not_found_reason)
    phases.append({"name": "patching", "duration_ms": elapsed_ms(phase_started)})

    updated, notes = apply_semantic_patch(semantic_plan, patch)
    semantic_diff = semantic_plan_diff(semantic_plan, updated)
    phase_started = time.monotonic()
    issues = validate_semantic_plan(updated, capabilities, permissions=permissions)
    phases.append({"name": "validation", "duration_ms": elapsed_ms(phase_started)})

    graph: dict[str, Any] | None = None
    steps_map: dict[str, str] = {}
    cost: dict[str, Any] | None = None
    if not any(issue.severity == "error" for issue in issues):
        phase_started = time.monotonic()
        graph, steps_map, compile_issues = _compile_validated(updated, capabilities)
        issues = [*issues, *compile_issues]
        phases.append({"name": "compilation", "duration_ms": elapsed_ms(phase_started)})
        if graph is not None:
            try:
                from src.platform.workflows.capabilities import cost_estimate

                cost = await cost_estimate(
                    organization_id, graph, _trigger_config_for_cost(updated)
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("architect patch cost failed", error=str(exc)[:150])

    if not preview_only:
        try:
            from src.platform.workflows.architect_metrics import record_revision

            record_revision()
        except Exception as exc:  # noqa: BLE001
            logger.warning("architect revision metric failed", error=str(exc)[:150])

    clarifications = build_clarifications(updated, issues)
    requirements = build_requirements(issues)
    readiness = _readiness(graph, capabilities) if graph is not None else None
    state = design_state(
        graph=graph,
        issues=issues,
        clarifications=clarifications,
        requirements=requirements,
        readiness=readiness,
        # Un patch heurístico mantiene la revisión humana, pero no convierte
        # todo el plan en "no listo": el usuario pidió un cambio concreto.
        fallback_used=False,
    )
    blockers = build_blockers(issues=issues, requirements=requirements, readiness=readiness)
    planner = _planner_payload(resolved, model, source)
    log_design(
        "architect.patch",
        session_id=session,
        organization_id=str(organization_id),
        workspace_id=str(workspace_id) if workspace_id else None,
        actor_id=str(actor_id) if actor_id else None,
        planner=planner,
        state=state,
        phases=phases,
        total_duration_ms=elapsed_ms(started),
        issue_codes=[issue.code for issue in issues],
        requirements=[item.get("requirement") for item in requirements],
        fallback_used=bool(fallback),
        instruction_chars=len(instruction or ""),
    )
    return {
        "session_id": session,
        "state": state,
        "planner": planner,
        "phases": phases,
        "fallback": fallback,
        "plan_hash": plan_hash(updated),
        "publishable": state == STATE_DRAFT_READY,
        "blockers": blockers,
        "capability_snapshot": capabilities.get("capability_snapshot"),
        "source": source,
        "plan": updated.model_dump(mode="json"),
        "patch": patch.model_dump(mode="json"),
        "diff": semantic_diff,
        "patch_confirmed": proposed_patch is not None,
        "issues": [issue.model_dump(mode="json") for issue in issues],
        "preview": semantic_preview(updated),
        "graph": graph,
        "steps_map": steps_map,
        "cost": cost,
        "clarifications": clarifications,
        "requirements": requirements,
        "readiness": readiness,
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

    raw_actions = capabilities.get("actions") or {}
    if isinstance(raw_actions, dict):
        actions = {str(key): value for key, value in raw_actions.items()}
    else:
        actions = {
            str(action.get("action_id")): action
            for action in raw_actions
            if isinstance(action, dict)
        }
    caps = {
        "agents": {
            str(agent["id"]): str(agent.get("name") or "")
            for agent in capabilities.get("agents") or []
        },
        "knowledge_bases": {
            str(kb): str(kb) for kb in capabilities.get("knowledge_bases") or []
        },
        "actions": actions,
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


def _compile_validated(
    plan: SemanticPlan,
    capabilities: dict[str, Any],
    *,
    intent: ArchitectIntent | None = None,
) -> tuple[dict[str, Any] | None, dict[str, str], list[PlanIssue]]:
    """Compila y valida el grafo. Nunca devuelve un grafo que `validate_graph` rechace."""
    from src.platform.workflows.ir import WorkflowGraph, WorkflowGraphError, validate_graph

    compiled = compile_semantic_plan(plan, capabilities, intent=intent)
    graph = compiled["graph"]
    extra: list[PlanIssue] = []
    try:
        validate_graph(WorkflowGraph.from_dict(graph))
    except (WorkflowGraphError, KeyError, TypeError, ValueError) as exc:
        logger.warning("architect compiled an invalid graph", error=str(exc)[:200])
        extra.append(
            PlanIssue(
                code="compile.invalid_graph",
                severity="error",
                message=f"No pude armar un flujo válido: {str(exc)[:240]}",
            )
        )
        graph = None
    return graph, compiled["steps_map"], [*compiled["issues"], *extra]


def _graph_trigger(graph: dict[str, Any] | None) -> tuple[str, dict[str, Any]]:
    for node in (graph or {}).get("nodes") or []:
        node_type = str(node.get("type") or "")
        if node_type == "trigger_schedule":
            return "schedule", dict(node.get("config") or {})
        if node_type == "trigger_event":
            return "event", dict(node.get("config") or {})
    return "webhook", {}


def _fallback_reason(exc: Exception) -> str:
    text_ = f"{type(exc).__name__}: {exc}".lower()
    if isinstance(exc, ValidationError) or "json" in text_ or "valid" in text_:
        return "invalid_llm_response"
    return "llm_unavailable"


def _planner_payload(provider: Any, model: str | None, source: str) -> dict[str, Any]:
    return {"version": PLANNER_VERSION, **provider_info(provider, model), "source": source}


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
        if step.type == "trigger_conversation":
            expectation = "Recibiría el mensaje del cliente en la conversación."
        elif step.type == "trigger_event":
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
        elif step.type == "capability_call":
            capability = str(step.params.get("capability") or "la capacidad")
            expectation = f"Ejecutaría {capability} (sin efectos en la vista previa)."
        elif step.type == "loop":
            expectation = "Volvería al paso indicado, dentro del límite configurado."
        elif step.type == "compensation":
            expectation = "Si la acción protegida falla, ejecutaría la compensación configurada."
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
    session_id: str | None = None,
    actor_id: UUID | None = None,
    preferred_agent_id: str | None = None,
) -> dict[str, Any]:
    """Pipeline completo (sin persistir): intent → plan → validación → grafo.

    Devuelve el contrato canónico del Workflow Architect: estado del proceso,
    planner, fases, fallback informado, bloqueos y hash del plan.
    """
    session = normalize_session_id(session_id)
    started = time.monotonic()
    phases: list[dict[str, Any]] = []
    phase_started = time.monotonic()
    if capabilities is None:
        capabilities = await discover_capabilities(
            organization_id, workspace_id=workspace_id, permissions=permissions
        )
    phases.append({"name": "discovery", "duration_ms": elapsed_ms(phase_started)})

    source = "llm"
    intent: ArchitectIntent | None = None
    plan: SemanticPlan | None = None
    notes: list[str] = []
    fallback: dict[str, Any] | None = None
    resolved: Any = None
    phase_started = time.monotonic()
    try:
        resolved = _resolve_provider(provider)
        intent = await extract_intent_with_architect(
            prompt, capabilities=capabilities, provider=resolved, model=model
        )
        phases.append({"name": "intent", "duration_ms": elapsed_ms(phase_started)})
        phase_started = time.monotonic()
        plan = await extract_plan_with_architect(
            intent, capabilities=capabilities, provider=resolved, model=model
        )
        phases.append({"name": "planning", "duration_ms": elapsed_ms(phase_started)})
    except Exception as exc:  # noqa: BLE001 — fallback determinístico informado
        reason = _fallback_reason(exc)
        logger.info(
            "architect: fallback heurístico",
            reason_code=reason,
            error_type=type(exc).__name__,
            session_id=session,
        )
        source = "heuristics"
        intent = None
        plan = heuristic_semantic_plan(prompt)
        notes.append(
            "No pude usar el modelo; armé un borrador con reglas. "
            "Revisa los pasos y confírmalo antes de publicar."
        )
        fallback = fallback_payload(reason, prompt)
        phases.append({"name": "planning", "duration_ms": elapsed_ms(phase_started)})

    preferred_issues: list[PlanIssue] = []
    if preferred_agent_id:
        plan, preferred_issues = _apply_preferred_agent(
            plan, capabilities, preferred_agent_id
        )

    phase_started = time.monotonic()
    issues = [
        *preferred_issues,
        *validate_semantic_plan(plan, capabilities, permissions=permissions),
    ]
    phases.append({"name": "validation", "duration_ms": elapsed_ms(phase_started)})

    graph: dict[str, Any] | None = None
    steps_map: dict[str, str] = {}
    cost: dict[str, Any] | None = None
    if not any(issue.severity == "error" for issue in issues):
        phase_started = time.monotonic()
        graph, steps_map, compile_issues = _compile_validated(
            plan, capabilities, intent=intent
        )
        issues = [*issues, *compile_issues]
        phases.append({"name": "compilation", "duration_ms": elapsed_ms(phase_started)})
        if graph is not None:
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
    phase_started = time.monotonic()
    clarifications = build_clarifications(plan, issues, intent=intent)
    requirements = build_requirements(issues)
    readiness = _readiness(graph, capabilities) if graph is not None else None
    simulation = simulation_plan(plan) if graph is not None else None
    phases.append({"name": "readiness", "duration_ms": elapsed_ms(phase_started)})

    state = design_state(
        graph=graph,
        issues=issues,
        clarifications=clarifications,
        requirements=requirements,
        readiness=readiness,
        fallback_used=source == "heuristics",
    )
    blockers = build_blockers(issues=issues, requirements=requirements, readiness=readiness)
    planner = _planner_payload(resolved, model, source)
    publishable = state == STATE_DRAFT_READY and fallback is None

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

    log_design(
        "architect.plan",
        session_id=session,
        organization_id=str(organization_id),
        workspace_id=str(workspace_id) if workspace_id else None,
        actor_id=str(actor_id) if actor_id else None,
        planner=planner,
        state=state,
        phases=phases,
        total_duration_ms=elapsed_ms(started),
        issue_codes=[issue.code for issue in issues],
        requirements=[item.get("requirement") for item in requirements],
        fallback_used=bool(fallback),
        fallback_reason=fallback.get("reason_code") if fallback else None,
        graph_nodes=len(graph.get("nodes") or []) if graph else 0,
        prompt_hash=prompt_hash(prompt),
        prompt_chars=len(prompt or ""),
    )
    return {
        "session_id": session,
        "state": state,
        "planner": planner,
        "phases": phases,
        "fallback": fallback,
        "plan_hash": plan_hash(plan),
        "publishable": publishable,
        "blockers": blockers,
        "capability_snapshot": capabilities.get("capability_snapshot"),
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


async def save_architect_draft(
    organization_id: UUID,
    plan_payload: dict[str, Any],
    *,
    workspace_id: UUID | None = None,
    permissions: frozenset[str] | None = None,
    name: str | None = None,
    description: str | None = None,
    editor_state: dict[str, Any] | None = None,
    session_id: str | None = None,
    plan_hash_value: str | None = None,
    capability_snapshot_hash: str | None = None,
    source: str = "llm",
    actor_id: UUID | None = None,
) -> dict[str, Any]:
    """Persiste un borrador re-validando TODO en el servidor.

    El portal no envía el grafo: envía el plan. El backend vuelve a descubrir
    capacidades, valida, compila y valida el grafo antes de guardar. Nunca
    activa el workflow ni confía en la validación de React.
    """
    from src.platform.workflows.capability_registry import (
        CapabilitySnapshotStale,
        build_capability_snapshot,
        refs_for_plan,
        verify_snapshot,
    )
    from src.platform.workflows.engine import create_workflow

    session = normalize_session_id(session_id)
    started = time.monotonic()
    plan = SemanticPlan.model_validate(plan_payload)
    if plan_hash_value and plan_hash(plan) != plan_hash_value:
        raise PlanHashMismatch(
            "El plan cambió desde que se mostró la vista previa; vuelve a interpretarlo antes de guardar."
        )

    fresh_snapshot = None
    if capability_snapshot_hash:
        try:
            fresh_snapshot = await build_capability_snapshot(
                organization_id,
                workspace_id,
                permissions=permissions,
                force_refresh=True,
            )
        except Exception as exc:  # noqa: BLE001 — sin snapshot se revalida igual
            logger.warning(
                "architect draft snapshot refresh failed", error=str(exc)[:180]
            )
        if fresh_snapshot is not None:
            check = verify_snapshot(
                capability_snapshot_hash, fresh_snapshot, refs_for_plan(plan)
            )
            if not check.get("valid"):
                log_design(
                    "architect.draft.stale_snapshot",
                    session_id=session,
                    organization_id=str(organization_id),
                    snapshot_hash=capability_snapshot_hash,
                    changed_refs=check.get("changed_refs"),
                    reason=check.get("reason"),
                )
                raise CapabilitySnapshotStale(
                    list(check.get("changed_refs") or []),
                    str(check.get("reason") or "stale_snapshot"),
                )

    phase_started = time.monotonic()
    capabilities = await discover_capabilities(
        organization_id,
        workspace_id=workspace_id,
        permissions=permissions,
        snapshot=fresh_snapshot,
    )
    discovery_ms = elapsed_ms(phase_started)

    phase_started = time.monotonic()
    issues = validate_semantic_plan(plan, capabilities, permissions=permissions)
    validation_ms = elapsed_ms(phase_started)

    graph: dict[str, Any] | None = None
    steps_map: dict[str, str] = {}
    if not any(issue.severity == "error" for issue in issues):
        phase_started = time.monotonic()
        graph, steps_map, compile_issues = _compile_validated(plan, capabilities)
        issues = [*issues, *compile_issues]
        compilation_ms = elapsed_ms(phase_started)
    else:
        compilation_ms = 0

    clarifications = build_clarifications(plan, issues)
    requirements = build_requirements(issues)
    readiness = _readiness(graph, capabilities) if graph is not None else None
    state = design_state(
        graph=graph,
        issues=issues,
        clarifications=clarifications,
        requirements=requirements,
        readiness=readiness,
        fallback_used=False,
    )
    blockers = build_blockers(issues=issues, requirements=requirements, readiness=readiness)
    normalized_source = "heuristics" if str(source) == "heuristics" else "llm"

    if graph is None or state == STATE_BLOCKED:
        log_design(
            "architect.draft.blocked",
            session_id=session,
            organization_id=str(organization_id),
            workspace_id=str(workspace_id) if workspace_id else None,
            state=state,
            issue_codes=[issue.code for issue in issues],
            requirements=[item.get("requirement") for item in requirements],
        )
        raise ArchitectBlocked(
            state=state,
            issues=[issue.model_dump(mode="json") for issue in issues],
            requirements=requirements,
            clarifications=clarifications,
            session_id=session,
        )

    trigger_type, trigger_config = _graph_trigger(graph)
    graph["metadata"] = {
        **(graph.get("metadata") or {}),
        "architect": True,
        "architect_state": state,
        "architect_source": normalized_source,
        "architect_session_id": session,
        "planner_version": PLANNER_VERSION,
        "architect_blockers": [item.get("code") for item in blockers],
    }
    resolved_editor_state = {
        **(editor_state or {}),
        "architect": {
            "session_id": session,
            "state": state,
            "source": normalized_source,
            "planner_version": PLANNER_VERSION,
            "requirements": [item.get("requirement") for item in requirements],
        },
    }
    draft_name = (name or plan.goal or "Automatización")[:150]
    draft_description = description or plan.goal
    workflow = await create_workflow(
        organization_id,
        draft_name,
        trigger_type,
        trigger_config,
        [],
        draft_description,
        actor_id,
        resolved_editor_state,
        workspace_id=workspace_id,
        graph=graph,
        workflow_version=2,
    )
    log_design(
        "architect.draft.saved",
        session_id=session,
        organization_id=str(organization_id),
        workspace_id=str(workspace_id) if workspace_id else None,
        actor_id=str(actor_id) if actor_id else None,
        workflow_id=workflow.get("workflow_id"),
        state=state,
        source=normalized_source,
        planner_version=PLANNER_VERSION,
        capability_snapshot_hash=(
            fresh_snapshot.snapshot_hash
            if fresh_snapshot is not None
            else (capabilities.get("capability_snapshot") or {}).get("snapshot_hash")
        ),
        phases={
            "discovery": discovery_ms,
            "validation": validation_ms,
            "compilation": compilation_ms,
        },
        issue_codes=[issue.code for issue in issues],
        requirements=[item.get("requirement") for item in requirements],
        graph_nodes=len(graph.get("nodes") or []),
        plan_hash=plan_hash(plan),
    )
    return {
        **workflow,
        "state": state,
        "session_id": session,
        "plan_hash": plan_hash(plan),
        "requirements": requirements,
        "readiness": readiness,
        "blockers": blockers,
        "capability_snapshot": (
            fresh_snapshot.summary() if fresh_snapshot is not None else capabilities.get("capability_snapshot")
        ),
        "publishable": state == STATE_DRAFT_READY and normalized_source == "llm",
        "source": normalized_source,
    }


__all__ = [
    "extract_intent_with_architect",
    "extract_plan_with_architect",
    "heuristic_plan_patch",
    "heuristic_semantic_plan",
    "patch_workflow_plan",
    "plan_workflow",
    "save_architect_draft",
    "semantic_preview",
    "simulation_plan",
]
