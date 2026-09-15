# =============================================================================
# Workflow Architect — patching conversacional (Fase 7, brief §15/§25).
#
# SemanticPlanPatch: cambios sobre el plan semántico (no sobre el grafo).
# Determinístico al aplicar; el LLM solo propone el patch. Nunca publica.
# =============================================================================
from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from src.infrastructure.observability.logging_config import get_logger
from src.platform.workflows.architect_models import PlanStep, SemanticPlan

logger = get_logger(__name__)

MODEL_CONFIG = ConfigDict(extra="forbid")

PATCH_OP_KINDS = (
    "set_param",
    "set_trigger",
    "set_schedule",
    "remove_step",
    "replace_agent",
    "add_step",
)

JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


class PlanPatchOp(BaseModel):
    """Operación de patch. Todo referenciado por `step_id` semántico."""

    model_config = MODEL_CONFIG

    kind: Literal[PATCH_OP_KINDS]
    step_id: str | None = Field(default=None, max_length=80)
    step_type: str | None = Field(default=None, max_length=40)
    key: str | None = Field(default=None, max_length=80)
    value: Any = None
    params: dict[str, Any] = Field(default_factory=dict)
    step: dict[str, Any] | None = None
    reason: str = Field(default="", max_length=300)


class SemanticPlanPatch(BaseModel):
    model_config = MODEL_CONFIG

    operations: list[PlanPatchOp] = Field(min_length=1, max_length=20)
    summary: str = Field(default="", max_length=400)
    assumptions: list[dict[str, Any]] = Field(default_factory=list, max_length=5)


PATCH_SYSTEM_PROMPT = """Eres el arquitecto de automatizaciones de Zent.
El usuario pide un cambio sobre un plan ya existente. Devuelve SOLO un JSON:
{"operations": [{"kind": "set_param"|"set_trigger"|"set_schedule"|"remove_step"|
                 "replace_agent"|"add_step",
                 "step_id": str|null, "key": str|null, "value": any,
                 "params": {}, "step": {}|null, "reason": str}],
 "summary": str}
- set_param: cambia un parámetro de un paso (umbral, mensaje, operación...).
- set_trigger/set_schedule: ajusta el disparador (p. ej. solo lunes a viernes).
- remove_step: quita un paso por id (p. ej. la aprobación).
- replace_agent: cambia el agente de un paso de análisis.
- add_step: agrega un paso semántico nuevo.
No inventes pasos que no existan al editar; no cambies el grafo ni refs."""


def _find_step(plan: SemanticPlan, step_id: str | None) -> PlanStep | None:
    if not step_id:
        return None
    for step in plan.steps:
        if step.id == step_id:
            return step
    return None


def apply_semantic_patch(plan: SemanticPlan, patch: SemanticPlanPatch) -> tuple[SemanticPlan, list[str]]:
    """Aplica el patch al plan y reescribe dependencias. Devuelve (plan, notas)."""
    steps: list[PlanStep] = [step.model_copy(deep=True) for step in plan.steps]
    notes: list[str] = []

    def index(step_id: str) -> int | None:
        for position, step in enumerate(steps):
            if step.id == step_id:
                return position
        return None

    for op in patch.operations:
        if op.kind == "set_param" and op.step_id and op.key:
            position = index(op.step_id)
            if position is None:
                notes.append(f"No encontré el paso {op.step_id}; ignoré «{op.key}».")
                continue
            params = dict(steps[position].params or {})
            params[op.key] = op.value
            steps[position] = steps[position].model_copy(update={"params": params})
        elif op.kind == "set_trigger":
            trigger = next((step for step in steps if step.type.startswith("trigger_")), None)
            if trigger is None:
                notes.append("El plan no tiene disparador; no pude ajustarlo.")
                continue
            params = dict(trigger.params or {})
            params.update(op.params or {})
            if op.value is not None and op.key:
                params[op.key] = op.value
            steps[index(trigger.id) or 0] = trigger.model_copy(update={"params": params})
        elif op.kind == "set_schedule":
            position = index(op.step_id or "") if op.step_id else None
            if position is None:
                position = next(
                    (pos for pos, step in enumerate(steps) if step.type == "trigger_schedule"),
                    None,
                )
            if position is None:
                notes.append("El plan no tiene un disparador por programación.")
                continue
            params = dict(steps[position].params or {})
            params.update(op.params or {})
            if op.value is not None:
                params["daily"] = op.value
            steps[position] = steps[position].model_copy(update={"params": params})
        elif op.kind == "remove_step":
            position = index(op.step_id or "")
            if position is None and op.step_type:
                position = next(
                    (pos for pos, step in enumerate(steps) if step.type == op.step_type), None
                )
            if position is None:
                notes.append(f"No encontré el paso a quitar ({op.step_id or op.step_type}).")
                continue
            removed = steps.pop(position)
            notes.append(f"Quité «{removed.goal}».")
            for pos, step in enumerate(steps):
                depends = [dep for dep in step.depends_on if dep != removed.id]
                if removed.id in step.depends_on:
                    depends.extend(dep for dep in removed.depends_on if dep not in depends)
                update: dict[str, Any] = {}
                if depends != step.depends_on:
                    update["depends_on"] = depends
                if step.when is not None and step.when.step == removed.id:
                    if removed.type == "decision":
                        update["when"] = None
                    else:
                        update["when"] = None
                if update:
                    steps[pos] = step.model_copy(update=update)
        elif op.kind == "replace_agent":
            position = index(op.step_id or "")
            if position is None:
                notes.append(f"No encontré el paso de análisis ({op.step_id}).")
                continue
            params = dict(steps[position].params or {})
            if op.value:
                params["agent_id"] = str(op.value)
                params.pop("agent_name", None)
            params.update(op.params or {})
            steps[position] = steps[position].model_copy(update={"params": params})
        elif op.kind == "add_step":
            if not op.step:
                notes.append("add_step sin definición de paso; ignorado.")
                continue
            try:
                new_step = PlanStep.model_validate(op.step)
            except Exception as exc:  # noqa: BLE001 — patch inválido se reporta
                notes.append(f"El paso nuevo no es válido: {str(exc)[:120]}")
                continue
            steps.append(new_step)
            notes.append(f"Agregué «{new_step.goal}».")

    goal = patch.summary.strip() or plan.goal
    applied = plan.model_copy(update={"steps": steps, "goal": goal})
    return applied, notes


def _parse_json_object(text: str) -> dict[str, Any] | None:
    match = JSON_OBJECT_RE.search(text or "")
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


async def propose_plan_patch(
    plan: SemanticPlan,
    instruction: str,
    *,
    provider: Any,
    model: str | None = None,
) -> SemanticPlanPatch:
    """El LLM propone el patch; el caller lo aplica y re-valida."""
    prompt = (
        "Plan actual:\n"
        + json.dumps(plan.model_dump(mode="json"), ensure_ascii=False)
        + f"\n\nCambio pedido por el usuario:\n{instruction}"
    )
    response = await provider.generate(
        prompt=prompt,
        system_prompt=PATCH_SYSTEM_PROMPT,
        model=model,
        temperature=0.0,
        max_tokens=1200,
    )
    content = getattr(response, "content", None)
    if content is None and isinstance(response, dict):
        content = response.get("content")
    data = _parse_json_object(str(content or ""))
    if data is None:
        raise ValueError("el LLM no devolvió un patch JSON válido")
    return SemanticPlanPatch.model_validate(data)


__all__ = [
    "PATCH_OP_KINDS",
    "PlanPatchOp",
    "SemanticPlanPatch",
    "apply_semantic_patch",
    "propose_plan_patch",
]
