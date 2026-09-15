# =============================================================================
# Workflow Architect — Clarification Engine (Fase 6, brief §9–§10).
#
# Preguntas de negocio, no técnicas. Las assumptions de alto impacto siempre
# se confirman; los requisitos (integración/DB) no son preguntas: son pasos.
# =============================================================================
from __future__ import annotations

from typing import Any

from src.platform.workflows.architect_models import ArchitectIntent, PlanIssue, SemanticPlan

_QUESTION_CODES = frozenset(
    {
        "missing.input",
        "missing.recipient",
        "missing.compare_sides",
        "missing.decision_input",
        "missing.filter_items",
        "missing.loop_collection",
        "plan.agent_needs_selection",
        "assumption.high_impact",
    }
)

_IMPACT_ORDER = {"high": 0, "medium": 1, "low": 2}


def build_clarifications(
    plan: SemanticPlan,
    issues: list[PlanIssue],
    *,
    intent: ArchitectIntent | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Preguntas necesarias (máximo `limit`), priorizando alto impacto."""
    questions: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(question: str, *, impact: str, code: str, step_id: str | None = None) -> None:
        text = str(question or "").strip()
        if not text or text in seen:
            return
        seen.add(text)
        questions.append(
            {"question": text, "impact": impact, "code": code, "step_id": step_id}
        )

    for issue in issues:
        if issue.code not in _QUESTION_CODES:
            continue
        add(
            issue.message,
            impact="high" if issue.code.startswith("assumption.") else "medium",
            code=issue.code,
            step_id=issue.step_id,
        )
    if intent is not None:
        for item in intent.missing_information:
            add(str(item), impact="high", code="intent.missing_information")
    questions.sort(key=lambda item: _IMPACT_ORDER.get(str(item["impact"]), 9))
    return questions[:limit]


def build_requirements(issues: list[PlanIssue]) -> list[dict[str, Any]]:
    """Requisitos de plataforma que el usuario debe resolver antes de publicar."""
    seen: set[str] = set()
    requirements: list[dict[str, Any]] = []
    for issue in issues:
        if not issue.requirement or issue.requirement in seen:
            continue
        seen.add(issue.requirement)
        requirements.append(
            {
                "requirement": issue.requirement,
                "code": issue.code,
                "message": issue.message,
                "resolved": False,
            }
        )
    return requirements


__all__ = ["build_clarifications", "build_requirements"]
