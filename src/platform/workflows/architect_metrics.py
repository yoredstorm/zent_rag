# =============================================================================
# Workflow Architect — métricas (Fase 10, brief §31).
#
# Contadores en proceso (sin dependencia de Prometheus) para evaluar el
# arquitecto; `snapshot()` expone tasas. Los push a Prometheus se pueden
# enganchar después sin cambiar la API.
# =============================================================================
from __future__ import annotations

from typing import Any

_COUNTERS: dict[str, int] = {
    "workflow_architect_plans_total": 0,
    "workflow_architect_plan_valid_total": 0,
    "workflow_architect_compile_success_total": 0,
    "workflow_architect_clarification_total": 0,
    "workflow_architect_requirements_total": 0,
    "workflow_architect_unnecessary_agent_total": 0,
    "workflow_architect_revision_total": 0,
}


def record_plan_outcome(
    *,
    valid: bool,
    compiled: bool,
    clarifications: int = 0,
    requirements: int = 0,
    unnecessary_agent: bool = False,
) -> None:
    _COUNTERS["workflow_architect_plans_total"] += 1
    if valid:
        _COUNTERS["workflow_architect_plan_valid_total"] += 1
    if compiled:
        _COUNTERS["workflow_architect_compile_success_total"] += 1
    if clarifications > 0:
        _COUNTERS["workflow_architect_clarification_total"] += 1
    if requirements > 0:
        _COUNTERS["workflow_architect_requirements_total"] += 1
    if unnecessary_agent:
        _COUNTERS["workflow_architect_unnecessary_agent_total"] += 1


def record_revision() -> None:
    _COUNTERS["workflow_architect_revision_total"] += 1


def reset_metrics() -> None:
    for key in _COUNTERS:
        _COUNTERS[key] = 0


def snapshot() -> dict[str, Any]:
    total = max(_COUNTERS["workflow_architect_plans_total"], 1)

    def rate(key: str) -> float:
        return round(_COUNTERS[key] / total, 4)

    return {
        "counters": dict(_COUNTERS),
        "workflow_architect_plan_valid_rate": rate("workflow_architect_plan_valid_total"),
        "workflow_architect_compile_success_rate": rate(
            "workflow_architect_compile_success_total"
        ),
        "workflow_architect_clarification_rate": rate(
            "workflow_architect_clarification_total"
        ),
        "workflow_architect_unnecessary_agent_rate": rate(
            "workflow_architect_unnecessary_agent_total"
        ),
    }


__all__ = ["record_plan_outcome", "record_revision", "reset_metrics", "snapshot"]
