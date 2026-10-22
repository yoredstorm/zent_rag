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
from src.platform.workflows.architect_models import PlanStep, SemanticPlan, WhenClause

logger = get_logger(__name__)

MODEL_CONFIG = ConfigDict(extra="forbid")

PATCH_OP_KINDS = (
    "set_param",
    "set_trigger",
    "set_schedule",
    "set_condition",
    "set_policy",
    "set_outputs",
    "replace_agent",
    "replace_capability",
    "remove_step",
    "add_step",
)

POLICY_FIELDS = ("retries", "timeout_seconds", "on_error", "idempotency")

#: Un patch conversacional no puede tocar seguridad ni secretos. El binding
#: físico y las credenciales se configuran fuera del plan portable.
SENSITIVE_KEY_PARTS = (
    "credential",
    "secret",
    "password",
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "private_key",
    "access_token",
    "refresh_token",
    "permission",
    "permissions",
    "role_id",
    "tenant_id",
    "organization_id",
    "provider",
    "binding_id",
)


class SensitivePatchError(ValueError):
    """El patch intentó modificar seguridad, credenciales o bindings."""


def _reject_sensitive(value: Any, *, path: str = "patch") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).lower()
            if any(part in normalized for part in SENSITIVE_KEY_PARTS):
                raise SensitivePatchError(
                    f"El cambio «{path}.{key}» toca credenciales, permisos o bindings; "
                    "configúralo en Integraciones/Mapping Studio, no por conversación."
                )
            _reject_sensitive(item, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_sensitive(item, path=f"{path}[{index}]")

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
{"operations": [{"kind": "set_param"|"set_trigger"|"set_schedule"|"set_condition"|
                 "set_policy"|"set_outputs"|"replace_agent"|"replace_capability"|
                 "remove_step"|"add_step",
                 "step_id": str|null, "key": str|null, "value": any,
                 "params": {}, "step": {}|null, "reason": str}],
 "summary": str}
- set_param: cambia un parámetro de un paso (umbral, mensaje, operación...).
- set_trigger/set_schedule: ajusta el disparador (p. ej. solo lunes a viernes).
- set_condition: cambia la rama de un paso; value/params = {"step":"id","outcome":true}.
- set_policy: cambia retries, timeout_seconds, on_error o idempotency (nivel superior del paso).
- set_outputs: cambia outputs_expected del paso (lista de campos).
- replace_agent: cambia el agente de un paso de análisis.
- replace_capability: sustituye la capacidad lógica y, opcionalmente, sus inputs
  (params = {"inputs": {...}}). No incluyas credenciales ni ids físicos.
- remove_step: quita un paso por id (p. ej. la aprobación).
- add_step: agrega un paso semántico nuevo (puede ser wait, loop, approval, capability_call).
No inventes pasos existentes; no cambies el grafo, credenciales, permisos ni refs físicas.
Conserva los pasos y requisitos que el usuario no pidió cambiar."""


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
        _reject_sensitive(op.params, path=f"operations.{op.kind}.params")
        _reject_sensitive(op.value, path=f"operations.{op.kind}.value")
        _reject_sensitive(op.step, path=f"operations.{op.kind}.step")
        if op.kind == "set_param" and op.key:
            _reject_sensitive({op.key: op.value}, path=f"operations.{op.kind}")
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
        elif op.kind == "set_condition":
            position = index(op.step_id or "")
            if position is None:
                notes.append(f"No encontré el paso de decisión ({op.step_id}).")
                continue
            candidate = op.value if isinstance(op.value, dict) else op.params
            if isinstance(candidate, dict) and isinstance(candidate.get("when"), dict):
                candidate = candidate["when"]
            try:
                when = WhenClause.model_validate(candidate)
            except Exception as exc:  # noqa: BLE001
                notes.append(f"La condición no es válida: {str(exc)[:120]}")
                continue
            if when.step == steps[position].id:
                notes.append("Una condición no puede depender del mismo paso.")
                continue
            steps[position] = steps[position].model_copy(update={"when": when})
            notes.append(f"Ajusté la condición de «{steps[position].goal}».")
        elif op.kind == "set_policy":
            position = index(op.step_id or "")
            if position is None:
                notes.append(f"No encontré el paso para su política ({op.step_id}).")
                continue
            updates: dict[str, Any] = {}
            params = dict(op.params or {})
            if op.key in POLICY_FIELDS:
                params[op.key] = op.value
            for key in POLICY_FIELDS:
                if key in params:
                    updates[key] = params[key]
            if not updates:
                notes.append("set_policy sin retries/timeout/on_error/idempotency.")
                continue
            try:
                steps[position] = PlanStep.model_validate(
                    {**steps[position].model_dump(mode="python"), **updates}
                )
            except Exception as exc:  # noqa: BLE001
                notes.append(f"La política no es válida: {str(exc)[:120]}")
                continue
            notes.append(f"Actualicé la política de «{steps[position].goal}».")
        elif op.kind == "set_outputs":
            position = index(op.step_id or "")
            if position is None:
                notes.append(f"No encontré el paso para sus salidas ({op.step_id}).")
                continue
            candidate = op.value if op.value is not None else op.params.get("outputs_expected")
            if not isinstance(candidate, list):
                notes.append("set_outputs necesita una lista de campos.")
                continue
            try:
                steps[position] = PlanStep.model_validate(
                    {
                        **steps[position].model_dump(mode="python"),
                        "outputs_expected": [str(item) for item in candidate],
                    }
                )
            except Exception as exc:  # noqa: BLE001
                notes.append(f"Las salidas no son válidas: {str(exc)[:120]}")
                continue
            notes.append(f"Actualicé las salidas de «{steps[position].goal}».")
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
        elif op.kind == "replace_capability":
            position = index(op.step_id or "")
            if position is None:
                notes.append(f"No encontré el paso de capacidad ({op.step_id}).")
                continue
            capability = op.value or (op.params or {}).get("capability")
            if not capability or not str(capability).strip():
                notes.append("replace_capability necesita una capacidad lógica.")
                continue
            params = dict(steps[position].params or {})
            params["capability"] = str(capability).strip()
            inputs = (op.params or {}).get("inputs")
            if isinstance(inputs, dict):
                params["inputs"] = {**dict(params.get("inputs") or {}), **inputs}
            steps[position] = steps[position].model_copy(update={"params": params})
            notes.append(f"Sustituí la capacidad de «{steps[position].goal}».")
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

    # Un patch corrige pasos, no reemplaza el objetivo del proceso. Cambiar el
    # goal por el summary hacía que «cambia el título» renombrara todo el plan.
    applied = plan.model_copy(update={"steps": steps, "goal": plan.goal})
    return applied, notes


def _plain(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_plain(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    return value


def semantic_plan_diff(before: SemanticPlan, after: SemanticPlan) -> dict[str, Any]:
    """Diff semántico estable para mostrar antes/después y guardar en revisiones."""
    before_steps = {step.id: step for step in before.steps}
    after_steps = {step.id: step for step in after.steps}
    fields = (
        "type",
        "goal",
        "depends_on",
        "when",
        "inputs",
        "params",
        "reason_summary",
        "optional",
        "retries",
        "timeout_seconds",
        "on_error",
        "contract_version",
        "outputs_expected",
        "idempotency",
    )
    added = [
        {"step_id": step_id, "type": step.type, "goal": step.goal}
        for step_id, step in after_steps.items()
        if step_id not in before_steps
    ]
    removed = [
        {"step_id": step_id, "type": step.type, "goal": step.goal}
        for step_id, step in before_steps.items()
        if step_id not in after_steps
    ]
    modified: list[dict[str, Any]] = []
    for step_id in sorted(set(before_steps) & set(after_steps)):
        old = before_steps[step_id]
        new = after_steps[step_id]
        changes: dict[str, Any] = {}
        for field in fields:
            old_value = _plain(getattr(old, field))
            new_value = _plain(getattr(new, field))
            if old_value != new_value:
                changes[field] = {"before": old_value, "after": new_value}
        if changes:
            modified.append({"step_id": step_id, "fields": changes})
    return {
        "added": added,
        "removed": removed,
        "modified": modified,
        "goal_changed": (
            {"before": before.goal, "after": after.goal}
            if before.goal != after.goal
            else None
        ),
        "summary": (
            f"{len(added)} agregado(s), {len(removed)} quitado(s), "
            f"{len(modified)} modificado(s)"
        ),
    }


def _parse_json_object(text: str) -> dict[str, Any] | None:
    from src.platform.workflows.json_output import parse_json_object

    return parse_json_object(text)


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
    "SensitivePatchError",
    "apply_semantic_patch",
    "propose_plan_patch",
    "semantic_plan_diff",
]
