# =============================================================================
# Workflow Copilot V2 — lenguaje natural → WorkflowIntent → WorkflowPlan.
#
# Reutiliza el gateway LLM existente (LiteLLM + router + circuit breaker). Las
# heurísticas de copilot.py se conservan como fallback cuando el LLM no está
# disponible o devuelve algo inválido. El backend valida; el LLM propone.
# =============================================================================
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from src.infrastructure.observability.logging_config import get_logger
from src.platform.workflows.intent import (
    ConditionOperator,
    IntentValidationError,
    PlanAction,
    PlanCondition,
    PlanFieldRef,
    PlanSchedule,
    PlanTrigger,
    PlanValidationIssue,
    TriggerKind,
    WorkflowIntent,
    WorkflowPlan,
    intent_to_plan,
    normalize_operator,
    validate_plan,
)

logger = get_logger(__name__)

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)

INTENT_SYSTEM_PROMPT = """Eres el copiloto de automatizaciones de Zent.
Convierte la petición del usuario en un WorkflowIntent JSON. Reglas estrictas:
- Responde SOLO con un objeto JSON, sin markdown.
- Usa este shape:
{
  "name": str, "description": str|null,
  "trigger": {"kind": "event"|"schedule"|"webhook"|"manual",
              "event_type": str|null,
              "schedule": {"mode": "interval"|"daily"|"weekly"|"monthly"|"cron",
                           "every_minutes": int|null, "time": "HH:MM"|null,
                           "days": [0-6]|null, "day_of_month": int|null,
                           "timezone": str, "cron": str|null}|null,
              "description": str|null},
  "conditions": [{"field": {"source": str, "field": str, "label": str|null},
                  "operator": "eq"|"neq"|"gt"|"gte"|"lt"|"lte"|"contains"|"not_contains"|
                              "starts_with"|"ends_with"|"is_empty"|"not_empty"|"changed",
                  "value": any, "description": str|null}],
  "data_sources": [{"key": str, "kind": "database"|"knowledge_base"|"integration"|
                    "event"|"agent"|"unknown",
                    "label": str|null, "ref": str|null}],
  "actions": [{"kind": "notify"|"agent_analysis"|"marketplace_action"|"api_call"|
               "business_result"|"human_approval"|"stop",
               "description": str|null,
               "channel": "zent"|"email"|"slack"|"teams"|"whatsapp"|"webhook"|null,
               "recipients": [{"kind": "person"|"team"|"email"|"channel"|"webhook",
                               "value": str, "label": str|null}],
               "subject": str|null, "message": str|null, "action_id": str|null,
               "install_id": str|null, "params": {}}],
  "agents": [str], "schedule": null, "recipients": [],
  "questions": [str], "risk": "info"|"normal"|"elevated"|"critical",
  "estimated_cost": number|null, "confidence": 0.0-1.0
}
- No inventes integraciones, agentes ni knowledge bases: si faltan datos, agrega la
  pregunta a "questions" y baja "confidence".
- Usa nombres de negocio en español para name/description, y en "field.label" el
  nombre visible del dato.
- Los datos del evento usan source "Evento" y el campo en "field"; el operador
  debe ser canónico (gt, lt, eq, ...).
"""


@dataclass
class IntentExtraction:
    intent: WorkflowIntent
    source: str = "llm"  # llm | heuristics
    notes: list[str] = field(default_factory=list)


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
    match = _JSON_OBJECT_RE.search(text or "")
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _capability_hints(capabilities: dict[str, Any] | None) -> str:
    caps = capabilities or {}
    agents = sorted(
        {
            str(v.get("name"))
            for v in caps.get("agents", {}).values()
            if isinstance(v, dict) and v.get("name")
        }
    )
    # knowledge_bases indexa id→id y nombre→id; mostramos solo los nombres reales.
    kb_names = [k for k, v in caps.get("knowledge_bases", {}).items() if k != v]
    events = caps.get("event_types") or []
    actions = (
        sorted({v.get("display_name") or k for k, v in caps.get("actions", {}).items()})
        if caps.get("actions")
        else []
    )
    parts = []
    if agents:
        parts.append(f"Agentes disponibles: {', '.join(agents[:20])}.")
    if kb_names:
        parts.append(f"Knowledge bases: {', '.join(kb_names[:20])}.")
    if events:
        parts.append(f"Eventos disponibles: {', '.join(events[:20])}.")
    if actions:
        parts.append(f"Acciones instaladas: {', '.join(actions[:20])}.")
    return "\n".join(parts)


async def extract_intent_with_llm(
    prompt: str,
    provider: Any,
    *,
    model: str | None = None,
    capabilities: dict[str, Any] | None = None,
) -> WorkflowIntent:
    hints = _capability_hints(capabilities)
    from src.platform.workflows.node_catalog import planner_hints

    catalog_block = planner_hints(capabilities)
    system = INTENT_SYSTEM_PROMPT
    if hints:
        system += f"\nContexto del tenant:\n{hints}\n"
    if catalog_block:
        system += f"\n{catalog_block}\n"
    response = await provider.generate(
        prompt=prompt,
        model=model,
        temperature=0.0,
        max_tokens=1600,
        system_prompt=system,
    )
    content = getattr(response, "content", None)
    if content is None and isinstance(response, dict):
        content = response.get("content")
    data = _parse_json_object(str(content or ""))
    if data is None:
        raise ValueError("el LLM no devolvió un JSON de intent válido")
    return WorkflowIntent.model_validate(data)


def heuristic_intent(prompt: str) -> WorkflowIntent:
    """Fallback determinístico basado en las heurísticas existentes."""
    from src.platform.workflows.copilot import build_draft

    draft = build_draft(prompt)
    trigger_config = draft.trigger_config or {}

    schedule = PlanSchedule.from_trigger_config(trigger_config)
    if draft.trigger_type == "schedule" and schedule is None:
        schedule = PlanSchedule(mode="daily", time="18:00", timezone="America/Lima")
    if draft.trigger_type == "event":
        trigger = PlanTrigger(kind=TriggerKind.event, event_type=trigger_config.get("event_type"))
    elif draft.trigger_type == "webhook":
        trigger = PlanTrigger(kind=TriggerKind.webhook)
    else:
        trigger = PlanTrigger(kind=TriggerKind.schedule, schedule=schedule)

    conditions: list[PlanCondition] = []
    actions: list[PlanAction] = []
    agents: list[str] = []

    def walk(steps: list[dict]) -> None:
        for step in steps or []:
            if not isinstance(step, dict):
                continue
            step_type = str(step.get("type") or "")
            config = step.get("config") or {}
            if step_type == "condition" and not conditions:
                field = str(config.get("field") or "")
                source = "Evento" if field.startswith("trigger.") else "datos"
                key = field.split(".")[-1] if field else "valor"
                try:
                    operator = normalize_operator(str(config.get("operator") or "=="))
                except ValueError:
                    operator = ConditionOperator.eq
                conditions.append(
                    PlanCondition(
                        field=PlanFieldRef(source=source, field=key, label=key.capitalize()),
                        operator=operator,
                        value=config.get("value"),
                    )
                )
            elif step_type == "llm":
                agents.append("Agente a elegir")
            elif step_type == "notify":
                actions.append(
                    PlanAction(
                        kind="notify",
                        channel="email" if str(config.get("channel")) == "email" else "zent",
                        subject=str(config.get("title") or draft.name),
                        message=str(config.get("message") or draft.name),
                    )
                )
            for branch in ("then", "else"):
                walk(step.get(branch) or [])

    walk(draft.steps)
    if not actions:
        actions.append(
            PlanAction(
                kind="notify",
                channel="zent",
                subject=draft.name,
                message=f"Resultado de {draft.name}",
                description="Avisar el resultado",
            )
        )

    return WorkflowIntent(
        name=draft.name,
        description=f"Borrador generado a partir de: {prompt[:200]}",
        trigger=trigger,
        schedule=schedule if trigger.kind == TriggerKind.schedule else None,
        conditions=conditions,
        actions=actions,
        agents=agents,
        questions=list(draft.questions),
        confidence=0.35,
        raw_prompt=prompt,
        risk="normal",
    )


async def propose_workflow(
    organization_id: UUID,
    prompt: str,
    *,
    workspace_id: UUID | None = None,
    provider: Any = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Pipeline NL → Intent → validación → Plan. No compila ni persiste."""
    from src.platform.workflows.plan_compiler import load_capabilities, plan_summary

    capabilities = await load_capabilities(organization_id, workspace_id)
    source = "llm"
    notes: list[str] = []
    try:
        intent = await extract_intent_with_llm(
            prompt, _resolve_llm_provider(provider), model=model, capabilities=capabilities
        )
    except Exception as exc:  # noqa: BLE001 — fallback determinístico
        logger.info("copilot v2: fallback heurístico", error=str(exc)[:200])
        intent = heuristic_intent(prompt)
        source = "heuristics"
        notes.append("No pude usar el modelo; armé un borrador con reglas. Revísalo.")

    try:
        plan = intent_to_plan(intent)
    except IntentValidationError as exc:
        # Intent incompleto: se devuelve para preguntar, sin plan compilable.
        return {
            "intent": intent.model_dump(mode="json"),
            "plan": None,
            "summary": None,
            "questions": [*intent.questions, str(exc)],
            "issues": [
                PlanValidationIssue(
                    code="intent.incomplete",
                    severity="error",
                    message=str(exc),
                ).model_dump(mode="json")
            ],
            "confidence": intent.confidence,
            "source": source,
            "notes": notes,
            "capabilities": _capability_names(capabilities),
            "must_review": True,
        }

    issues = validate_plan(plan)
    return {
        "intent": intent.model_dump(mode="json"),
        "plan": plan.model_dump(mode="json"),
        "summary": plan_summary(plan).to_dict(),
        "questions": plan.questions,
        "issues": [i.model_dump(mode="json") for i in issues],
        "confidence": intent.confidence,
        "source": source,
        "notes": notes,
        "capabilities": _capability_names(capabilities),
        "must_review": True,
    }


def _capability_names(capabilities: dict[str, Any]) -> dict[str, Any]:
    return {
        "agents": sorted({v["name"] for v in capabilities.get("agents", {}).values() if isinstance(v, dict)}),
        "knowledge_bases": sorted(
            k for k, v in capabilities.get("knowledge_bases", {}).items() if k != v
        ),
        "actions": sorted(
            {
                str(v.get("action_id"))
                for v in capabilities.get("actions", {}).values()
                if isinstance(v, dict)
            }
        ),
        "event_types": list(capabilities.get("event_types") or []),
    }


async def compile_proposal(
    organization_id: UUID,
    plan_payload: dict[str, Any],
    *,
    workspace_id: UUID | None = None,
) -> dict[str, Any]:
    """Compila un Plan (ya validado por el usuario) al Graph IR. No persiste."""
    from src.platform.workflows.plan_compiler import (
        compile_plan_for_org,
        compiled_plan_payload,
    )

    plan = WorkflowPlan.model_validate(plan_payload)
    compiled = await compile_plan_for_org(organization_id, plan, workspace_id)
    payload = compiled_plan_payload(compiled)
    payload["plan"] = plan.model_dump(mode="json")
    return payload


__all__ = [
    "INTENT_SYSTEM_PROMPT",
    "IntentExtraction",
    "compile_proposal",
    "extract_intent_with_llm",
    "heuristic_intent",
    "propose_workflow",
]
