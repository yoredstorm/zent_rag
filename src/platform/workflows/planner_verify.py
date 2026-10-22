# =============================================================================
# Agentic Workflow Planner — verificación de MATCH + contratos + políticas.
#
# Complementa validate_semantic_plan (forma/dependencias/permisos) con lo que
# solo puede comprobarse contra el snapshot de capacidades: matches, tipos de
# entrada/salida, aprobaciones críticas y durabilidad. Determinista; el LLM no
# participa en la decisión.
# =============================================================================
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from src.platform.workflows.architect_models import PlanIssue, PlanStep, SemanticPlan
from src.platform.workflows.capability_registry import CapabilitySnapshot

MODEL_CONFIG = ConfigDict(extra="forbid")

_CRITICAL_SIDE_EFFECTS = frozenset({"financial"})
_TERMINAL_TYPES = frozenset({"stop", "business_result", "notify"})


class CapabilityMatch(BaseModel):
    """Fila NECESIDAD → CANDIDATOS → SELECCIÓN del planner."""

    model_config = MODEL_CONFIG

    need: str = Field(min_length=1, max_length=300)
    capability_ref: str = Field(min_length=1, max_length=200)
    version: int | None = Field(default=None, ge=1, le=1_000_000)
    reason: str = Field(default="", max_length=400)
    availability: str | None = Field(default=None, max_length=40)
    bindings: list[str] = Field(default_factory=list, max_length=10)
    unresolved: list[str] = Field(default_factory=list, max_length=10)
    alternatives: list[str] = Field(default_factory=list, max_length=10)


class VerificationResult(BaseModel):
    model_config = MODEL_CONFIG

    issues: list[PlanIssue] = Field(default_factory=list)
    requires_durable_instance: bool = False
    matched_refs: list[str] = Field(default_factory=list)


def _issue(
    code: str,
    *,
    severity: str = "error",
    step_id: str | None = None,
    message: str,
    field: str | None = None,
    expected: str | None = None,
    received: str | None = None,
    alternatives: list[str] | None = None,
    action_required: str | None = None,
    requirement: str | None = None,
) -> PlanIssue:
    return PlanIssue(
        code=code,
        severity=severity,  # type: ignore[arg-type]
        step_id=step_id,
        message=message[:400],
        requirement=requirement,
        field=field,
        expected=(expected or "")[:400] or None,
        received=(received or "")[:400] or None,
        alternatives=alternatives or [],
        action_required=(action_required or "")[:400] or None,
    )


def _step_capability_ref(step: PlanStep) -> str | None:
    if step.type == "capability_call":
        return str(step.params.get("capability") or "").strip() or None
    if step.type == "integration_action":
        return str(step.params.get("action_id") or "").strip() or None
    if step.type == "agent_analysis":
        agent_id = str(step.params.get("agent_id") or "").strip()
        return f"agent.{agent_id}" if agent_id else None
    if step.type == "compensation":
        return str(
            step.params.get("capability")
            or step.params.get("action_id")
            or ""
        ).strip() or None
    return None


def _source_outputs(step: PlanStep, snapshot: CapabilitySnapshot) -> list[str] | None:
    """Campos de salida del paso (snapshot o schema de negocio del nodo)."""
    ref = _step_capability_ref(step)
    if ref:
        descriptor = snapshot.index().get(ref)
        if descriptor is None:
            return None
        properties = descriptor.output_schema.get("properties") or {}
        if not properties:
            return None
        return sorted(str(key) for key in properties.keys())
    if step.type == "wait":
        # El evento reanuda la instancia con payload dinámico; estos campos son
        # los que el runtime expone de forma estable.
        return [
            "message",
            "payload",
            "event_type",
            "correlation",
            "waiting",
            "port",
            "status",
            "payment_reference",
        ]
    if step.type == "trigger_conversation":
        return ["message", "conversation_id", "payload", "event_type"]
    if step.type == "state":
        return ["value", "ok", "removed", "merged", "appended"]
    mapping = {
        "business_query": "query_business_data",
        "knowledge_query": "kb_query",
        "decision": "condition",
        "agent_analysis": "llm",
        "notify": "notify",
        "business_result": "business_result",
        "filter": "filter",
    }
    node_type = mapping.get(step.type)
    if not node_type:
        return None
    try:
        from src.platform.workflows.parameters import node_business_schema

        schema = node_business_schema(node_type)
        if schema is None:
            return None
        fields = [str(item.key) for item in schema.outputs]
        return fields or None
    except Exception:  # noqa: BLE001 — schema opcional
        return None


def _target_inputs(
    step: PlanStep, snapshot: CapabilitySnapshot
) -> list[str] | None:
    if step.type == "capability_call":
        ref = str(step.params.get("capability") or "").strip()
        descriptor = snapshot.index().get(ref)
        if descriptor is None:
            return None
        properties = descriptor.input_schema.get("properties") or {}
        if not properties:
            return None
        return sorted(str(key) for key in properties.keys())
    if step.type == "integration_action":
        ref = str(step.params.get("action_id") or "").strip()
        descriptor = snapshot.index().get(ref)
        if descriptor is None:
            return None
        properties = descriptor.input_schema.get("properties") or {}
        if not properties:
            return None
        return sorted(str(key) for key in properties.keys())
    return None


def _ancestors(plan: SemanticPlan) -> dict[str, set[str]]:
    by_id = {step.id: step for step in plan.steps}
    out: dict[str, set[str]] = {}
    for step in plan.steps:
        found: set[str] = set()
        stack = list(step.depends_on)
        if step.when is not None:
            stack.append(step.when.step)
        while stack:
            current = stack.pop()
            if current in found:
                continue
            found.add(current)
            parent = by_id.get(current)
            if parent is not None:
                stack.extend(parent.depends_on)
                if parent.when is not None:
                    stack.append(parent.when.step)
        out[step.id] = found
    return out


def verify_plan(
    plan: SemanticPlan,
    matches: list[CapabilityMatch],
    snapshot: CapabilitySnapshot,
) -> VerificationResult:
    """Comprueba contratos, matches, aprobaciones y durabilidad."""
    issues: list[PlanIssue] = []
    index = snapshot.index()
    by_id = {step.id: step for step in plan.steps}
    match_by_ref = {str(match.capability_ref): match for match in matches}
    matched_refs: list[str] = []

    # 1) MATCH: toda capacidad/agente usado tiene una fila con justificación.
    for step in plan.steps:
        ref = _step_capability_ref(step)
        if not ref:
            continue
        matched_refs.append(ref)
        match = match_by_ref.get(ref)
        if match is None:
            issues.append(
                _issue(
                    "plan.missing_match",
                    step_id=step.id,
                    message=f"«{step.goal}» usa {ref} sin justificar la selección.",
                    field="matches.capability_ref",
                    expected=f"match para {ref}",
                    received="sin match",
                    action_required="Agrega la fila de match con necesidad y motivo.",
                )
            )
            continue
        descriptor = index.get(ref)
        if descriptor is None:
            issues.append(
                _issue(
                    "capability.unknown",
                    step_id=step.id,
                    message=f"La capacidad {ref} no existe en el catálogo del tenant.",
                    field="capability_ref",
                    expected="ref del snapshot",
                    received=ref,
                    action_required="Busca una capacidad existente o resuelve la dependencia.",
                )
            )
            continue
        if match.version is not None and match.version != descriptor.version:
            issues.append(
                _issue(
                    "match.version_mismatch",
                    severity="warning",
                    step_id=step.id,
                    message=(
                        f"El match de {ref} declara v{match.version} pero el catálogo "
                        f"tiene v{descriptor.version}."
                    ),
                    field="matches.version",
                    expected=str(descriptor.version),
                    received=str(match.version),
                    action_required="Actualiza la versión o vuelve a inspeccionar.",
                )
            )
        if not descriptor.availability.executable:
            requirements = [f"capability:{ref}", *match.unresolved]
            issues.append(
                _issue(
                    "capability.unavailable",
                    step_id=step.id,
                    message=(
                        f"La capacidad {ref} no está ejecutable "
                        f"({descriptor.availability.status})."
                    ),
                    field="matches.capability_ref",
                    expected="AVAILABLE + executable",
                    received=descriptor.availability.status,
                    alternatives=list(descriptor.metadata.get("provider_alternatives") or [])[:5],
                    action_required="Conecta el proveedor/binding o elige una alternativa.",
                    requirement=requirements[0],
                )
            )
        alternatives = list(descriptor.metadata.get("provider_alternatives") or [])
        if alternatives and not match.alternatives:
            issues.append(
                _issue(
                    "match.alternatives_missing",
                    severity="warning",
                    step_id=step.id,
                    message=(
                        f"Hay {len(alternatives)} proveedor(es) equivalente(s) para {ref}; "
                        "el match no registra alternativas."
                    ),
                    field="matches.alternatives",
                    expected="lista de alternativas consideradas",
                    received="[]",
                    alternatives=alternatives[:5],
                    action_required="Inspecciona y registra las alternativas antes de elegir.",
                )
            )

    # 2) Tipos de entrada/salida entre pasos.
    for step in plan.steps:
        target_inputs = _target_inputs(step, snapshot)
        literal_keys = set((step.params.get("inputs") or {}).keys()) if isinstance(
            step.params.get("inputs"), dict
        ) else set()
        if target_inputs is not None:
            unknown = sorted(
                key for key in literal_keys if target_inputs and key not in target_inputs
            )
            if unknown:
                issues.append(
                    _issue(
                        "contract.input_unknown",
                        step_id=step.id,
                        message=f"«{step.goal}» envía campos que el contrato no acepta: {', '.join(unknown[:5])}.",
                        field="params.inputs",
                        expected=", ".join(target_inputs[:12]) or "sin inputs",
                        received=", ".join(unknown[:5]),
                        alternatives=target_inputs[:8],
                        action_required="Usa los campos del input_schema inspeccionado.",
                    )
                )
        for input_ref in step.inputs:
            source = by_id.get(input_ref.step)
            if source is None:
                issues.append(
                    _issue(
                        "contract.source_missing",
                        step_id=step.id,
                        message=f"«{step.goal}» referencia un paso inexistente ({input_ref.step}).",
                        field="inputs.step",
                        expected="paso existente",
                        received=input_ref.step,
                        action_required="Corrige la referencia.",
                    )
                )
                continue
            outputs = _source_outputs(source, snapshot)
            if outputs is None:
                issues.append(
                    _issue(
                        "contract.output_unverified",
                        severity="warning",
                        step_id=step.id,
                        message=(
                            f"No pude verificar el campo «{input_ref.field}» de "
                            f"«{source.goal}» (sin contrato de salida)."
                        ),
                        field="inputs.field",
                        expected="contrato de salida",
                        received=input_ref.field,
                        action_required="Inspecciona el nodo o usa una capacidad con contrato.",
                    )
                )
            elif input_ref.field != "output" and input_ref.field not in outputs:
                issues.append(
                    _issue(
                        "contract.output_unknown",
                        step_id=step.id,
                        message=(
                            f"«{step.goal}» usa «{input_ref.field}» de «{source.goal}», "
                            "pero ese campo no está en su salida."
                        ),
                        field="inputs.field",
                        expected=", ".join(outputs[:12]) or "sin campos",
                        received=input_ref.field,
                        alternatives=outputs[:8],
                        action_required="Elige un campo de salida del contrato.",
                    )
                )
            if target_inputs:
                target_field = input_ref.to or input_ref.field
                if target_field not in target_inputs:
                    issues.append(
                        _issue(
                            "contract.input_unknown",
                            step_id=step.id,
                            message=(
                                f"«{step.goal}» intenta llenar «{target_field}», que no "
                                "existe en el contrato de entrada."
                            ),
                            field="inputs.to",
                            expected=", ".join(target_inputs[:12]),
                            received=target_field,
                            alternatives=target_inputs[:8],
                            action_required="Usa un campo de entrada permitido.",
                        )
                    )

    # 3) Aprobaciones para acciones críticas/financieras.
    ancestors = _ancestors(plan)
    approvals = {
        step.id for step in plan.steps if step.type == "human_approval"
    }
    for step in plan.steps:
        ref = _step_capability_ref(step)
        if not ref:
            continue
        descriptor = index.get(ref)
        if descriptor is None:
            continue
        critical = (
            descriptor.risk_level == "critical"
            or bool(_CRITICAL_SIDE_EFFECTS & set(descriptor.side_effects))
            or bool(descriptor.metadata.get("requires_approval"))
        )
        if critical and not (ancestors.get(step.id, set()) & approvals) and step.id not in approvals:
            issues.append(
                _issue(
                    "approval.critical_action",
                    step_id=step.id,
                    message=(
                        f"«{step.goal}» ejecuta una acción crítica/financiera sin "
                        "aprobación humana previa."
                    ),
                    field="depends_on",
                    expected="human_approval ancestro",
                    received="sin aprobación",
                    alternatives=["agregar human_approval antes del paso"],
                    action_required="Inserta una aprobación humana antes de la acción.",
                    requirement="approval:human",
                )
            )

    # 4) Durabilidad y ramas de timeout.
    requires_durable = any(step.type in ("wait", "loop", "state") for step in plan.steps)
    if requires_durable:
        issues.append(
            _issue(
                "runtime.requires_instance",
                severity="warning",
                message=(
                    "El plan usa WAIT/LOOP/estado durable: debe iniciarse como "
                    "WorkflowInstance para sobrevivir a la espera."
                ),
                field="runtime",
                expected="proceso durable",
                received="run simple",
                action_required="Inicia el flujo como proceso durable.",
            )
        )
    for step in plan.steps:
        if step.type == "wait" and str(step.params.get("on_timeout") or "") == "branch":
            has_branch = any(
                other.when is not None
                and other.when.step == step.id
                and other.when.outcome is False
                for other in plan.steps
            )
            if not has_branch:
                issues.append(
                    _issue(
                        "wait.timeout_branch_missing",
                        step_id=step.id,
                        message=f"«{step.goal}» no tiene rama para el timeout.",
                        field="params.on_timeout",
                        expected="paso con when outcome=false",
                        received="sin rama",
                        alternatives=["agregar rama de timeout", "usar expire/fail/continue"],
                        action_required="Agrega la rama o cambia la política.",
                    )
                )
        if step.type == "loop":
            target = str(step.params.get("target") or "")
            if target and target not in by_id:
                issues.append(
                    _issue(
                        "loop.unknown_target",
                        step_id=step.id,
                        message=f"«{step.goal}» vuelve a un paso inexistente ({target}).",
                        field="params.target",
                        expected="paso del plan",
                        received=target,
                        action_required="Corrige el target.",
                    )
                )
            elif target in by_id:
                target_step = by_id[target]
                order = {item.id: index for index, item in enumerate(plan.steps)}
                if order.get(target, 0) >= order.get(step.id, 0):
                    issues.append(
                        _issue(
                            "loop.target_order",
                            severity="error",
                            step_id=step.id,
                            message=f"«{step.goal}» debe volver a un paso anterior.",
                            field="params.target",
                            expected="paso anterior al loop",
                            received=target,
                            action_required="Mueve el loop después del cuerpo o corrige el target.",
                        )
                    )
                if target_step.type.startswith("trigger_") or target_step.type in (
                    "loop",
                    "stop",
                    "business_result",
                ):
                    issues.append(
                        _issue(
                            "loop.invalid_target",
                            severity="error",
                            step_id=step.id,
                            message=(
                                f"«{step.goal}» no puede repetir un paso "
                                f"{target_step.type}."
                            ),
                            field="params.target",
                            expected="paso de trabajo repetible",
                            received=target_step.type,
                            action_required="Elige el inicio del cuerpo del loop.",
                        )
                    )

    # 5) Cierre: al menos una salida de negocio o parada.
    if not any(step.type in _TERMINAL_TYPES for step in plan.steps):
        issues.append(
            _issue(
                "plan.no_terminal",
                severity="warning",
                message="El plan no declara un aviso, resultado o parada final.",
                field="steps",
                expected="notify|business_result|stop",
                received="sin salida",
                action_required="Agrega una salida explícita.",
            )
        )
    return VerificationResult(
        issues=issues,
        requires_durable_instance=requires_durable,
        matched_refs=sorted(set(matched_refs)),
    )


__all__ = [
    "CapabilityMatch",
    "VerificationResult",
    "verify_plan",
]
