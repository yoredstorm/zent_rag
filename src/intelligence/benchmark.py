# =============================================================================
# Intelligence Benchmark Suite (Phase 30A)
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Callable


class BenchmarkCategory(StrEnum):
    SIMPLE_RAG = "Simple RAG"
    COMPLEX_RAG = "Complex RAG"
    TEXT_TO_SQL = "Text-to-SQL"
    MULTI_TABLE_SQL = "Multi-table SQL"
    LEGACY_DB_SQL = "Legacy DB SQL"
    BUSINESS_METRICS = "Business Metrics"
    AMBIGUOUS_TERMS = "Ambiguous Terms"
    MISSING_DATA = "Missing Data"
    MISSING_CONTEXT = "Missing Context"
    SOURCE_CONFLICTS = "Source Conflicts"
    CROSS_SOURCE = "Cross-source Questions"
    TEMPORAL = "Temporal Questions"
    ENTITY_RESOLUTION = "Entity Resolution"
    ANALYTICAL = "Analytical Questions"
    ADVERSARIAL = "Adversarial Questions"
    PERMISSION = "Permission Tests"


@dataclass(kw_only=True)
class IntelligenceBenchmarkCase:
    """Caso gold de answerability / semantic intelligence."""

    id: str
    question: str
    category: BenchmarkCategory | str
    expected_answerability: str
    expected_intent: str | None = None
    expected_abstention_reason: str | None = None
    expected_concepts: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        cat = (
            self.category.value
            if isinstance(self.category, BenchmarkCategory)
            else str(self.category)
        )
        return {
            "id": self.id,
            "question": self.question,
            "category": cat,
            "expected_answerability": self.expected_answerability,
            "expected_intent": self.expected_intent,
            "expected_abstention_reason": self.expected_abstention_reason,
            "expected_concepts": list(self.expected_concepts),
            "metadata": dict(self.metadata),
        }


AnswerabilityFn = Callable[[IntelligenceBenchmarkCase], str]


class IntelligenceBenchmarkRunner:
    """Evalúa expected answerability contra un predictor inyectable."""

    def __init__(self, cases: list[IntelligenceBenchmarkCase] | None = None) -> None:
        self.cases = list(cases or [])

    def add_case(self, case: IntelligenceBenchmarkCase) -> None:
        self.cases.append(case)

    def run(self, predict: AnswerabilityFn) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        passed = 0
        for case in self.cases:
            actual = predict(case)
            ok = actual == case.expected_answerability
            if ok:
                passed += 1
            results.append(
                {
                    "id": case.id,
                    "category": case.to_dict()["category"],
                    "expected": case.expected_answerability,
                    "actual": actual,
                    "passed": ok,
                }
            )
        total = len(self.cases) or 1
        return {
            "total": len(self.cases),
            "passed": passed,
            "failed": len(self.cases) - passed,
            "pass_rate": round(passed / total, 4),
            "results": results,
        }

    @staticmethod
    def default_suite() -> list[IntelligenceBenchmarkCase]:
        return [
            IntelligenceBenchmarkCase(
                id="bm_sales_fact",
                question="¿Cuántas ventas hubo ayer?",
                category=BenchmarkCategory.BUSINESS_METRICS,
                expected_answerability="ANSWERABLE",
                expected_intent="business_metric",
                expected_concepts=["ventas"],
            ),
            IntelligenceBenchmarkCase(
                id="bm_profitable",
                question="¿Cuántos clientes rentables tenemos?",
                category=BenchmarkCategory.MISSING_CONTEXT,
                expected_answerability="CONTEXT_MISSING",
                expected_abstention_reason="missing_definition",
            ),
            IntelligenceBenchmarkCase(
                id="bm_margin_fx",
                question="¿Cuál fue el margen total?",
                category=BenchmarkCategory.MISSING_CONTEXT,
                expected_answerability="CONTEXT_MISSING",
                metadata={"mixed_currency": True},
            ),
            IntelligenceBenchmarkCase(
                id="bm_why_sales",
                question="¿Por qué bajaron las ventas?",
                category=BenchmarkCategory.ANALYTICAL,
                expected_answerability="ANSWERABLE",
                metadata={"requires_research_plan": True},
            ),
            IntelligenceBenchmarkCase(
                id="bm_ceo_salary",
                question="¿Qué salario tiene el CEO?",
                category=BenchmarkCategory.PERMISSION,
                expected_answerability="ACCESS_BLOCKED",
            ),
        ]
