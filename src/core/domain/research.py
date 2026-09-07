# =============================================================================
# Domain — Analytical Research Plans (Phase 29)
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4


class ResearchStepStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"
    DATA_MISSING = "DATA_MISSING"
    CONTEXT_MISSING = "CONTEXT_MISSING"
    SKIPPED = "SKIPPED"


@dataclass(kw_only=True)
class ResearchStep:
    """Nodo de un Research Plan analítico."""

    id: str = field(default_factory=lambda: str(uuid4()))
    name: str
    operation: str = "inspect"
    status: ResearchStepStatus = ResearchStepStatus.PENDING
    depends_on: list[str] = field(default_factory=list)
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "operation": self.operation,
            "status": self.status.value,
            "depends_on": list(self.depends_on),
            "result": dict(self.result),
            "error": self.error,
        }


@dataclass(kw_only=True)
class ResearchBudgets:
    """Presupuestos duros del Research Plan (integrable con LoopGuard)."""

    max_steps: int = 10
    max_sql_queries: int = 8
    max_retrieval_calls: int = 4
    max_tool_calls: int = 12
    max_tokens: int = 8000
    max_cost_usd: float = 0.25
    max_duration_seconds: float = 60.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_steps": self.max_steps,
            "max_sql_queries": self.max_sql_queries,
            "max_retrieval_calls": self.max_retrieval_calls,
            "max_tool_calls": self.max_tool_calls,
            "max_tokens": self.max_tokens,
            "max_cost_usd": self.max_cost_usd,
            "max_duration_seconds": self.max_duration_seconds,
        }


@dataclass(kw_only=True)
class ResearchPlan:
    """Plan explícito para preguntas analíticas / causales."""

    id: UUID = field(default_factory=uuid4)
    question: str
    steps: list[ResearchStep] = field(default_factory=list)
    budgets: ResearchBudgets = field(default_factory=ResearchBudgets)
    steps_executed: int = 0
    sql_queries: int = 0
    retrieval_calls: int = 0
    tool_calls: int = 0
    tokens_used: int = 0
    cost_usd: float = 0.0

    def budget_exceeded(self) -> str | None:
        b = self.budgets
        if len(self.steps) > b.max_steps:
            return "max_steps"
        if self.steps_executed > b.max_steps:
            return "max_steps"
        if self.sql_queries > b.max_sql_queries:
            return "max_sql_queries"
        if self.retrieval_calls > b.max_retrieval_calls:
            return "max_retrieval_calls"
        if self.tool_calls > b.max_tool_calls:
            return "max_tool_calls"
        if self.tokens_used > b.max_tokens:
            return "max_tokens"
        if self.cost_usd > b.max_cost_usd:
            return "max_cost"
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "question": self.question,
            "steps": [s.to_dict() for s in self.steps],
            "budgets": self.budgets.to_dict(),
            "steps_executed": self.steps_executed,
            "budget_exceeded": self.budget_exceeded(),
        }
