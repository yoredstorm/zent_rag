# =============================================================================
# Workflow Architect — Plan Validator (First delivery, brief §8).
#
# Valida el plan semántico ANTES de compilar: disponibilidad, permisos,
# dependencias, ciclos, inputs, requisitos de integración y riesgo/costo.
# Nunca otorga permisos; solo reporta.
# =============================================================================
from __future__ import annotations

from typing import Any

from src.platform.workflows.architect_discovery import match_agents, requirement_message
from src.platform.workflows.architect_models import (
    KNOWLEDGE_OPERATIONS,
    TRIGGER_STEP_TYPES,
    PlanIssue,
    SemanticPlan,
)

_SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


def _has_cycle(plan: SemanticPlan) -> list[str] | None:
    by_id = {step.id: step for step in plan.steps}
    state: dict[str, int] = {}

    def visit(step_id: str, path: list[str]) -> list[str] | None:
        if step_id in path:
            return path[path.index(step_id):] + [step_id]
        if state.get(step_id) == 2:
            return None
        state[step_id] = 1
        step = by_id.get(step_id)
        if step is not None:
            deps = list(step.depends_on)
            if step.when is not None:
                deps.append(step.when.step)
            for dep in deps:
                if dep in by_id:
                    cycle = visit(dep, path + [step_id])
                    if cycle:
                        return cycle
        state[step_id] = 2
        return None

    for step in plan.steps:
        cycle = visit(step.id, [])
        if cycle:
            return cycle
    return None


def validate_semantic_plan(
    plan: SemanticPlan,
    capabilities: dict[str, Any],
    *,
    permissions: frozenset[str] | None = None,
) -> list[PlanIssue]:
    """Lista de issues ordenada por severidad. `error` impide compilar."""
    issues: list[PlanIssue] = []
    available = capabilities.get("available") or {}
    raw_actions = capabilities.get("actions") or {}
    if isinstance(raw_actions, dict):
        actions = {str(key) for key in raw_actions}
        action_meta = raw_actions
    else:
        actions = {str(item.get("action_id")) for item in raw_actions}
        action_meta = {
            str(item.get("action_id")): item for item in raw_actions if isinstance(item, dict)
        }
    agent_ids = {str(item.get("id")) for item in capabilities.get("agents") or []}
    kb_ids = {str(item) for item in capabilities.get("knowledge_bases") or []}
    by_id = {step.id: step for step in plan.steps}

    if len(by_id) != len(plan.steps):
        issues.append(
            PlanIssue(code="plan.duplicate_step", severity="error", message="Hay pasos con el mismo identificador.")
        )
    triggers = [step for step in plan.steps if step.type in TRIGGER_STEP_TYPES]
    if len(triggers) != 1:
        issues.append(
            PlanIssue(
                code="plan.trigger",
                severity="error",
                message="El plan necesita exactamente un disparador (evento, programa o manual).",
            )
        )

    cycle = _has_cycle(plan)
    if cycle:
        issues.append(
            PlanIssue(
                code="plan.cycle",
                severity="error",
                message="El plan tiene un ciclo: " + " → ".join(cycle),
            )
        )

    agent_steps = 0
    for step in plan.steps:
        for dep in step.depends_on:
            if dep not in by_id:
                issues.append(
                    PlanIssue(
                        code="plan.unknown_dependency",
                        severity="error",
                        step_id=step.id,
                        message=f"«{step.goal}» depende de un paso que no existe ({dep}).",
                    )
                )
        if step.when is not None:
            source = by_id.get(step.when.step)
            if source is None:
                issues.append(
                    PlanIssue(
                        code="plan.unknown_when",
                        severity="error",
                        step_id=step.id,
                        message=f"«{step.goal}» espera una decisión que no existe ({step.when.step}).",
                    )
                )
            elif source.type not in ("decision", "wait"):
                issues.append(
                    PlanIssue(
                        code="plan.when_not_decision",
                        severity="warning",
                        step_id=step.id,
                        message=f"«{step.goal}» usa una rama de un paso que no decide ni espera.",
                    )
                )
        if step.depends_on and step.type in TRIGGER_STEP_TYPES:
            issues.append(
                PlanIssue(
                    code="plan.trigger_dependency",
                    severity="error",
                    step_id=step.id,
                    message="El disparador no puede depender de otros pasos.",
                )
            )

        if step.type == "business_query":
            if not available.get("managed_db"):
                issues.append(
                    PlanIssue(
                        code="missing.managed_db",
                        severity="error",
                        step_id=step.id,
                        message="Para consultar datos de negocio primero necesitas una base de datos conectada.",
                        requirement="managed_db",
                    )
                )
            if not str(step.params.get("ask") or "").strip():
                issues.append(
                    PlanIssue(
                        code="missing.input",
                        severity="warning",
                        step_id=step.id,
                        message=f"«{step.goal}» necesita saber qué dato pedir.",
                    )
                )
        elif step.type == "knowledge_query":
            if not kb_ids:
                issues.append(
                    PlanIssue(
                        code="missing.knowledge_bases",
                        severity="error",
                        step_id=step.id,
                        message="Para consultar conocimiento primero necesitas una base de conocimiento.",
                        requirement="knowledge_bases",
                    )
                )
            operation = str(step.params.get("operation") or "").strip().lower()
            if operation and operation not in KNOWLEDGE_OPERATIONS:
                issues.append(
                    PlanIssue(
                        code="plan.knowledge_operation",
                        severity="error",
                        step_id=step.id,
                        message=f"Operación de conocimiento desconocida: {operation}.",
                    )
                )
            if operation == "compare" and not (
                step.params.get("compare_left") and step.params.get("compare_right")
            ):
                issues.append(
                    PlanIssue(
                        code="missing.compare_sides",
                        severity="warning",
                        step_id=step.id,
                        message=f"«{step.goal}» necesita indicar qué comparar (lado A y lado B).",
                    )
                )
        elif step.type == "capability_call":
            capability_ref = str(step.params.get("capability") or "").strip()
            if not capability_ref:
                issues.append(
                    PlanIssue(
                        code="missing.capability",
                        severity="error",
                        step_id=step.id,
                        message=f"«{step.goal}» necesita una capacidad concreta.",
                    )
                )
            else:
                descriptor = (capabilities.get("capability_index") or {}).get(capability_ref)
                if descriptor is None:
                    issues.append(
                        PlanIssue(
                            code="missing.capability",
                            severity="error",
                            step_id=step.id,
                            message=requirement_message("capability", capability_ref),
                            requirement=f"capability:{capability_ref}",
                        )
                    )
                else:
                    availability = descriptor.get("availability") or {}
                    if not availability.get("executable", False):
                        reasons = "; ".join(availability.get("reasons") or []) or str(
                            availability.get("status") or "no disponible"
                        )
                        issues.append(
                            PlanIssue(
                                code="capability.unavailable",
                                severity="error",
                                step_id=step.id,
                                message=f"La capacidad {capability_ref} no está disponible: {reasons}.",
                                requirement=f"capability:{capability_ref}",
                            )
                        )
                    provided = set((step.params.get("inputs") or {}).keys())
                    for input_ref in step.inputs:
                        provided.add(input_ref.to or input_ref.field)
                    missing_inputs = [
                        key
                        for key in (descriptor.get("required_inputs") or [])
                        if key not in provided
                    ]
                    if missing_inputs:
                        issues.append(
                            PlanIssue(
                                code="missing.capability_input",
                                severity="error",
                                step_id=step.id,
                                field="params.inputs",
                                message=(
                                    f"«{step.goal}» necesita: "
                                    + ", ".join(missing_inputs[:6])
                                    + "."
                                ),
                                expected=", ".join(
                                    (descriptor.get("required_inputs") or [])[:12]
                                ),
                                received=", ".join(sorted(provided)[:12]) or "sin inputs",
                                alternatives=[
                                    f"input:{item}"
                                    for item in (descriptor.get("required_inputs") or [])[:8]
                                ],
                                action_required=(
                                    "Proporciona los campos requeridos por el contrato "
                                    "o conéctalos desde un paso anterior."
                                ),
                            )
                        )
                    if permissions is not None:
                        missing_permissions = [
                            permission
                            for permission in (descriptor.get("required_permissions") or [])
                            if permission not in permissions and "admin:*" not in permissions
                        ]
                        if missing_permissions:
                            issues.append(
                                PlanIssue(
                                    code="permission.capability",
                                    severity="warning",
                                    step_id=step.id,
                                    message=(
                                        "Tu rol no puede ejecutar esta capacidad: "
                                        + ", ".join(missing_permissions[:3])
                                    ),
                                )
                            )
        elif step.type == "agent_analysis":
            agent_steps += 1
            if not available.get("agents"):
                issues.append(
                    PlanIssue(
                        code="missing.agents",
                        severity="error",
                        step_id=step.id,
                        message=requirement_message("agents"),
                        requirement="agents",
                    )
                )
            explicit = str(step.params.get("agent_id") or "").strip()
            if explicit and explicit not in agent_ids:
                issues.append(
                    PlanIssue(
                        code="missing.agent",
                        severity="error",
                        step_id=step.id,
                        message="El agente elegido no está disponible en este espacio.",
                        requirement="agents",
                    )
                )
            elif not explicit:
                matches = match_agents(f"{step.goal} {step.params.get('prompt') or ''}", capabilities)
                if not matches:
                    issues.append(
                        PlanIssue(
                            code="plan.agent_needs_selection",
                            severity="warning",
                            step_id=step.id,
                            message=f"«{step.goal}» usará un agente: elige cuál antes de publicar.",
                        )
                    )
            if permissions is not None and "agents:execute" not in permissions:
                issues.append(
                    PlanIssue(
                        code="permission.agents",
                        severity="warning",
                        step_id=step.id,
                        message="Tu rol actual no puede ejecutar agentes; pide acceso a un administrador.",
                    )
                )
        elif step.type == "integration_action":
            action_id = str(step.params.get("action_id") or "").strip()
            if not action_id:
                issues.append(
                    PlanIssue(
                        code="missing.action_id",
                        severity="error",
                        step_id=step.id,
                        message=f"«{step.goal}» necesita una acción de integración concreta.",
                    )
                )
            elif action_id not in actions:
                issues.append(
                    PlanIssue(
                        code="missing.integration",
                        severity="error",
                        step_id=step.id,
                        message=requirement_message("integration", action_id),
                        requirement=f"integration:{action_id}",
                    )
                )
            else:
                meta = action_meta.get(action_id) or {}
                if meta.get("executable", True) is False:
                    reasons = "; ".join(
                        str(item) for item in (meta.get("reasons") or [])[:2]
                    ) or str(meta.get("status") or "no disponible")
                    issues.append(
                        PlanIssue(
                            code="capability.unavailable",
                            severity="error",
                            step_id=step.id,
                            message=(
                                f"La acción {action_id} no está ejecutable: {reasons}."
                            ),
                            requirement=f"integration:{action_id}",
                        )
                    )
            if permissions is not None and "external_actions:execute" not in permissions:
                issues.append(
                    PlanIssue(
                        code="permission.integration",
                        severity="warning",
                        step_id=step.id,
                        message="Tu rol actual no puede ejecutar acciones externas.",
                    )
                )
        elif step.type == "notify":
            channel = str(step.params.get("channel") or "in_app").lower()
            if channel in ("slack", "teams", "whatsapp"):
                channel_label = {"slack": "Slack", "teams": "Microsoft Teams", "whatsapp": "WhatsApp"}[channel]
                issues.append(
                    PlanIssue(
                        code="missing.notification_channel",
                        severity="error",
                        step_id=step.id,
                        message=requirement_message("integration", channel_label),
                        requirement=f"integration:{channel}",
                    )
                )
            elif channel == "email" and not step.params.get("recipients"):
                issues.append(
                    PlanIssue(
                        code="missing.recipient",
                        severity="warning",
                        step_id=step.id,
                        message=f"«{step.goal}»: falta elegir a quién avisar por correo.",
                    )
                )
        elif step.type == "decision":
            if not step.inputs and not step.params.get("field"):
                issues.append(
                    PlanIssue(
                        code="missing.decision_input",
                        severity="error",
                        step_id=step.id,
                        message=f"«{step.goal}» necesita saber qué resultado decide la rama.",
                    )
                )
            elif step.inputs:
                reference = step.inputs[0]
                accepted_sources = set(step.depends_on)
                if step.when is not None:
                    accepted_sources.add(step.when.step)
                if reference.step not in accepted_sources:
                    issues.append(
                        PlanIssue(
                            code="plan.decision_input_not_dependency",
                            severity="warning",
                            step_id=step.id,
                            message=f"«{step.goal}» usa un dato de un paso del que no depende.",
                        )
                    )
        elif step.type == "filter" and not step.inputs:
            issues.append(
                PlanIssue(
                    code="missing.filter_items",
                    severity="warning",
                    step_id=step.id,
                    message=f"«{step.goal}»: falta elegir la lista a filtrar.",
                )
            )
        elif step.type == "wait":
            preset = str(step.params.get("preset") or "message").strip().lower()
            if preset not in ("message", "webhook", "payment", "timer", "human", "signal"):
                issues.append(
                    PlanIssue(
                        code="wait.invalid_preset",
                        severity="error",
                        step_id=step.id,
                        field="params.preset",
                        message=f"«{step.goal}» usa un preset de espera desconocido: {preset}.",
                        expected="message|webhook|payment|timer|human|signal",
                        received=preset,
                        action_required="Usa un preset soportado o cambia a una acción normal.",
                    )
                )
            on_timeout = str(step.params.get("on_timeout") or "").strip().lower()
            if on_timeout and on_timeout not in ("branch", "expire", "fail", "continue"):
                issues.append(
                    PlanIssue(
                        code="wait.invalid_timeout_policy",
                        severity="error",
                        step_id=step.id,
                        field="params.on_timeout",
                        message=f"«{step.goal}» usa una política de timeout desconocida: {on_timeout}.",
                        expected="branch|expire|fail|continue",
                        received=on_timeout,
                        alternatives=["continue", "fail", "expire"],
                        action_required="Elige una política de timeout válida.",
                    )
                )
            if on_timeout == "branch":
                has_timeout_branch = any(
                    other.when is not None
                    and other.when.step == step.id
                    and other.when.outcome is False
                    for other in plan.steps
                )
                if not has_timeout_branch:
                    issues.append(
                        PlanIssue(
                            code="wait.timeout_branch_missing",
                            severity="error",
                            step_id=step.id,
                            field="params.on_timeout",
                            message=(
                                f"«{step.goal}» deriva por timeout pero no tiene un paso "
                                "para esa rama."
                            ),
                            expected="paso con when {step, outcome:false}",
                            received="sin rama de timeout",
                            alternatives=["agregar paso de timeout", "usar expire/fail/continue"],
                            action_required="Agrega la rama de timeout o cambia on_timeout.",
                        )
                    )
            event_type = str(step.params.get("event_type") or "").strip()
            known_events = {str(item) for item in (capabilities.get("events") or [])}
            if event_type and known_events and event_type not in known_events and not event_type.startswith(
                ("custom.", "webhook.", "signal.", "watcher.")
            ):
                issues.append(
                    PlanIssue(
                        code="wait.unknown_event",
                        severity="warning",
                        step_id=step.id,
                        field="params.event_type",
                        message=f"«{step.goal}» espera un evento no registrado: {event_type}.",
                        expected="evento del catálogo o custom./webhook./signal.",
                        received=event_type,
                        action_required="Verifica el catálogo de eventos o configura el emisor.",
                    )
                )
        elif step.type == "state":
            if not str(step.params.get("path") or "").strip():
                issues.append(
                    PlanIssue(
                        code="state.path_required",
                        severity="error",
                        step_id=step.id,
                        field="params.path",
                        message=f"«{step.goal}» necesita un path de estado.",
                        expected="path no vacío (ej. cart.items)",
                        received="",
                        action_required="Define el path del estado durable.",
                    )
                )
        elif step.type == "loop":
            target = str(step.params.get("target") or "").strip()
            if not target:
                issues.append(
                    PlanIssue(
                        code="loop.target_required",
                        severity="error",
                        step_id=step.id,
                        field="params.target",
                        message=f"«{step.goal}» necesita el paso al que vuelve.",
                        expected="id de un paso anterior",
                        received="",
                        action_required="Define params.target con un id existente.",
                    )
                )
            elif target not in by_id:
                issues.append(
                    PlanIssue(
                        code="loop.unknown_target",
                        severity="error",
                        step_id=step.id,
                        field="params.target",
                        message=f"«{step.goal}» vuelve a un paso que no existe ({target}).",
                        expected="id de un paso del plan",
                        received=target,
                        alternatives=[item.id for item in plan.steps if item.id != step.id][:5],
                        action_required="Elige un target existente.",
                    )
                )
            elif target == step.id:
                issues.append(
                    PlanIssue(
                        code="loop.self_target",
                        severity="error",
                        step_id=step.id,
                        field="params.target",
                        message=f"«{step.goal}» no puede volver a sí mismo.",
                        expected="otro paso",
                        received=step.id,
                        action_required="Elige otro target.",
                    )
                )
            else:
                target_step = by_id[target]
                order = {item.id: index for index, item in enumerate(plan.steps)}
                if order.get(target, 0) >= order.get(step.id, 0):
                    issues.append(
                        PlanIssue(
                            code="loop.target_order",
                            severity="error",
                            step_id=step.id,
                            field="params.target",
                            message=f"«{step.goal}» debe volver a un paso anterior.",
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
                        PlanIssue(
                            code="loop.invalid_target",
                            severity="error",
                            step_id=step.id,
                            field="params.target",
                            message=(
                                f"«{step.goal}» no puede repetir un paso "
                                f"{target_step.type}."
                            ),
                            expected="paso de trabajo repetible",
                            received=target_step.type,
                            action_required="Elige el inicio del cuerpo del loop.",
                        )
                    )
            try:
                max_iterations = int(step.params.get("max_iterations") or 20)
            except (TypeError, ValueError):
                max_iterations = 0
            if not 1 <= max_iterations <= 100:
                issues.append(
                    PlanIssue(
                        code="loop.max_iterations",
                        severity="error",
                        step_id=step.id,
                        field="params.max_iterations",
                        message=f"«{step.goal}» necesita un límite entre 1 y 100.",
                        expected="1..100",
                        received=str(step.params.get("max_iterations")),
                        action_required="Acota las repeticiones.",
                    )
                )
        elif step.type == "for_each":
            issues.append(
                PlanIssue(
                    code="plan.for_each_unsupported",
                    severity="error",
                    step_id=step.id,
                    message=(
                        f"«{step.goal}» necesita un cuerpo que la planificación semántica "
                        "todavía no puede expresar. Divídelo en pasos o constrúyelo en el "
                        "lienzo avanzado."
                    ),
                )
            )

    for assumption in plan.assumptions:
        if assumption.requires_question:
            issues.append(
                PlanIssue(
                    code="assumption.high_impact",
                    severity="warning",
                    message=f"Confirma antes de publicar: {assumption.statement}",
                )
            )

    if agent_steps > 1:
        issues.append(
            PlanIssue(
                code="cost.many_agents",
                severity="warning",
                message=f"El flujo usa {agent_steps} agentes: revisa el costo por ejecución.",
            )
        )
    if any(
        step.type == "knowledge_query"
        and str(step.params.get("operation") or "").lower() == "investigate"
        for step in plan.steps
    ):
        issues.append(
            PlanIssue(
                code="cost.investigation",
                severity="info",
                message="La investigación cognitiva es más costosa: define un presupuesto.",
            )
        )

    return sorted(issues, key=lambda issue: _SEVERITY_ORDER.get(issue.severity, 9))


__all__ = ["validate_semantic_plan"]
