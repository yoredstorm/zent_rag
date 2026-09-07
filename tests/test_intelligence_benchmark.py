"""Phase 30A — Intelligence benchmark suite."""
from __future__ import annotations

from src.intelligence.benchmark import (
    BenchmarkCategory,
    IntelligenceBenchmarkCase,
    IntelligenceBenchmarkRunner,
)


def test_categories_from_spec() -> None:
    names = {c.value for c in BenchmarkCategory}
    assert "Simple RAG" in names
    assert "Text-to-SQL" in names
    assert "Missing Context" in names
    assert "Analytical Questions" in names
    assert "Permission Tests" in names
    assert "Entity Resolution" in names


def test_runner_evaluates_expected_answerability() -> None:
    runner = IntelligenceBenchmarkRunner(
        [
            IntelligenceBenchmarkCase(
                id="1",
                question="¿Cuántas ventas hubo ayer?",
                category=BenchmarkCategory.BUSINESS_METRICS,
                expected_answerability="ANSWERABLE",
            ),
            IntelligenceBenchmarkCase(
                id="2",
                question="¿Cuántos clientes rentables tenemos?",
                category=BenchmarkCategory.MISSING_CONTEXT,
                expected_answerability="CONTEXT_MISSING",
            ),
        ]
    )

    def predict(case: IntelligenceBenchmarkCase) -> str:
        if "rentables" in case.question:
            return "CONTEXT_MISSING"
        return "ANSWERABLE"

    out = runner.run(predict)
    assert out["passed"] == 2
    assert out["failed"] == 0
    assert out["pass_rate"] == 1.0


def test_default_suite_non_empty() -> None:
    suite = IntelligenceBenchmarkRunner.default_suite()
    assert len(suite) >= 5
    cats = {c.to_dict()["category"] for c in suite}
    assert "Permission Tests" in cats
