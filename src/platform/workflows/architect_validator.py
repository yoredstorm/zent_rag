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
    actions = {str(item.get("action_id")) for item in capabilities.get("actions") or []}
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
            elif source.type != "decision":
                issues.append(
                    PlanIssue(
                        code="plan.when_not_decision",
                        severity="warning",
                        step_id=step.id,
                        message=f"«{step.goal}» usa una rama de un paso que no es una decisión.",
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
        elif step.type == "for_each" and not step.inputs:
            issues.append(
                PlanIssue(
                    code="missing.loop_collection",
                    severity="warning",
                    step_id=step.id,
                    message=f"«{step.goal}»: falta elegir la lista a recorrer.",
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
