# =============================================================================
# Workflow Architect — Clarification Engine (Fase 6, brief §9–§10).
#
# Preguntas de negocio, no técnicas. Las assumptions de alto impacto siempre
# se confirman; los requisitos (integración/DB) no son preguntas: son pasos.
# =============================================================================
from __future__ import annotations

import hashlib
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
        "contract.input_unknown",
        "contract.output_unknown",
        "contract.type_mismatch",
        "contract.literal_type",
        "contract.outputs_missing",
        "contract.version_mismatch",
        "contract.params_invalid",
        "contract.idempotency_required",
    }
)

_IMPACT_ORDER = {"high": 0, "medium": 1, "low": 2}
_SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


def clarification_payload(
    question: str,
    *,
    code: str,
    impact: str = "medium",
    step_id: str | None = None,
    field: str | None = None,
    expected: str | None = None,
    received: str | None = None,
    alternatives: list[str] | None = None,
    action_required: str | None = None,
    severity: str = "warning",
) -> dict[str, Any]:
    """Pregunta con contrato estable para UI y reanudación de sesión."""
    text = str(question or "").strip()
    digest = hashlib.sha256(
        f"{code}|{step_id or ''}|{field or ''}|{text}".encode("utf-8")
    ).hexdigest()[:12]
    return {
        "question_id": f"q_{digest}",
        "question": text,
        "impact": impact,
        "severity": severity,
        "code": code,
        "step_id": step_id,
        "field": field,
        "expected": expected,
        "received": received,
        "alternatives": list(alternatives or [])[:5],
        "action_required": action_required,
        "resolved": False,
    }


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

    def add(
        question: str,
        *,
        impact: str,
        code: str,
        step_id: str | None = None,
        issue: PlanIssue | None = None,
    ) -> None:
        text = str(question or "").strip()
        if not text:
            return
        payload = clarification_payload(
            text,
            code=code,
            impact=impact,
            step_id=step_id,
            field=getattr(issue, "field", None),
            expected=getattr(issue, "expected", None),
            received=getattr(issue, "received", None),
            alternatives=getattr(issue, "alternatives", None),
            action_required=getattr(issue, "action_required", None),
            severity=getattr(issue, "severity", "warning"),
        )
        if payload["question_id"] in seen or text in seen:
            return
        seen.add(payload["question_id"])
        seen.add(text)
        questions.append(payload)

    for issue in issues:
        if issue.code not in _QUESTION_CODES:
            continue
        add(
            issue.message,
            impact="high" if issue.code.startswith(("assumption.", "contract.")) else "medium",
            code=issue.code,
            step_id=issue.step_id,
            issue=issue,
        )
    if intent is not None:
        for item in intent.missing_information:
            add(str(item), impact="high", code="intent.missing_information")
    questions.sort(
        key=lambda item: (
            _IMPACT_ORDER.get(str(item["impact"]), 9),
            _SEVERITY_ORDER.get(str(item.get("severity") or "warning"), 9),
            str(item.get("code") or ""),
            str(item.get("step_id") or ""),
            str(item.get("question") or ""),
        )
    )
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


__all__ = [
    "build_clarifications",
    "build_requirements",
    "clarification_payload",
]
