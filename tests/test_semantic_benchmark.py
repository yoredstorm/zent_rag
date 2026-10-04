# =============================================================================
# Semantic Benchmark — BASELINE vs NUEVO (Fase 16)
# =============================================================================
# Reglas que se prueban:
#   - recall de evidencia/dependencias, citation precision y abstention;
#   - agregados honestos (None cuando no hay expectativa, nunca 0 falso);
#   - deltas por caso y promoción solo con mejora medible;
#   - render legible y carga de casos desde JSON.
# =============================================================================
from __future__ import annotations

from src.rag.evaluation.semantic_benchmark import (
    ModeObservation,
    PromotionThresholds,
    compare_semantic_modes,
    load_benchmark_cases,
    render_benchmark_report,
    summarize_mode,
)


def _cases():
    return load_benchmark_cases(
        [
            {
                "case_id": "c1",
                "question": "¿FCLAS &&&F acepta X?",
                "expected_evidence": ["e1", "e2"],
                "expected_dependencies": ["d1"],
                "expected_citations": ["c1", "c2"],
            },
            {
                "case_id": "c2",
                "question": "¿existe la política Z?",
                "expect_abstention": True,
            },
        ]
    )


def test_compare_modes_measures_knowledge_not_only_chunks() -> None:
    cases = _cases()
    baseline = {
        "c1": ModeObservation(
            mode="baseline",
            retrieved_evidence=("e1",),
            retrieved_sources=("doc-a",),
            citations=("c1",),
            context_tokens=1000,
            latency_ms=40.0,
            cost_usd=0.001,
        ),
        "c2": ModeObservation(
            mode="baseline",
            retrieved_evidence=("x1",),
            citations=("cx",),
            abstained=False,
            context_tokens=900,
            latency_ms=35.0,
        ),
    }
    candidate = {
        "c1": ModeObservation(
            mode="candidate",
            retrieved_evidence=("e1", "e2"),
            retrieved_dependencies=("d1",),
            retrieved_sources=("doc-a",),
            citations=("c1", "c2"),
            context_tokens=1300,
            latency_ms=55.0,
            cost_usd=0.0012,
        ),
        "c2": ModeObservation(
            mode="candidate",
            abstained=True,
            context_tokens=400,
            latency_ms=20.0,
        ),
    }
    report = compare_semantic_modes(cases, baseline=baseline, candidate=candidate)
    assert report["cases"] == 2
    assert report["baseline"]["evidence_recall"] == 0.5
    assert report["candidate"]["evidence_recall"] == 1.0
    assert report["candidate"]["dependency_recall"] == 1.0
    assert report["candidate"]["citation_precision"] == 1.0
    assert report["candidate"]["abstention_precision"] == 1.0
    assert report["baseline"]["abstention_precision"] == 0.0
    assert report["delta"]["dependency_recall"] == 1.0
    assert report["promotion_ready"] is True

    rendered = render_benchmark_report(report)
    assert "dependency_recall" in rendered
    assert "promotion_ready: True" in rendered


def test_compare_without_gains_does_not_promote() -> None:
    cases = _cases()
    baseline = {
        "c1": ModeObservation(
            mode="baseline", retrieved_evidence=("e1", "e2"), citations=("c1",)
        )
    }
    candidate = {
        "c1": ModeObservation(
            mode="candidate", retrieved_evidence=("e1",), citations=("c1",)
        )
    }
    report = compare_semantic_modes(cases, baseline=baseline, candidate=candidate)
    assert report["promotion_ready"] is False
    assert report["delta"]["evidence_recall"] == -0.5


def test_missing_expectations_are_none_not_zero() -> None:
    cases = load_benchmark_cases(
        [{"case_id": "c9", "question": "sin expectativas"}]
    )
    baseline = {"c9": ModeObservation(mode="baseline", retrieved_evidence=("a",))}
    report = compare_semantic_modes(cases, baseline=baseline, candidate={})
    assert report["baseline"]["evidence_recall"] is None
    assert report["baseline"]["citation_precision"] is None
    assert report["baseline"]["abstention_precision"] is None


def test_promotion_thresholds_are_objective() -> None:
    """Fase 33: no se promueve por "parece mejor"; umbrales explícitos."""
    cases = _cases()
    baseline = {
        "c1": ModeObservation(
            mode="baseline",
            retrieved_evidence=("e1",),
            citations=("c1",),
            context_tokens=1000,
            latency_ms=40.0,
            cost_usd=0.001,
        )
    }
    candidate = {
        "c1": ModeObservation(
            mode="candidate",
            retrieved_evidence=("e1", "e2"),
            retrieved_dependencies=("d1",),
            citations=("c1", "c2"),
            context_tokens=1300,
            latency_ms=130.0,
            cost_usd=0.0012,
        )
    }
    default = compare_semantic_modes(
        cases, baseline=baseline, candidate=candidate
    )
    assert default["promotion_ready"] is False  # latencia 3.25x > 1.5x

    relaxed = compare_semantic_modes(
        cases,
        baseline=baseline,
        candidate=candidate,
        thresholds=PromotionThresholds(max_latency_ratio=4.0),
    )
    assert relaxed["promotion_ready"] is True
    assert relaxed["thresholds"]["max_latency_ratio"] == 4.0

    strict_cases = compare_semantic_modes(
        cases,
        baseline=baseline,
        candidate=candidate,
        thresholds=PromotionThresholds(min_cases=5, max_latency_ratio=4.0),
    )
    assert strict_cases["promotion_ready"] is False


def test_summarize_mode_aggregates() -> None:
    cases = _cases()
    summary = summarize_mode(
        cases,
        {
            "c1": ModeObservation(
                mode="baseline",
                retrieved_evidence=("e1", "e2"),
                retrieved_dependencies=("d1",),
                citations=("c1", "c2"),
            )
        },
    )
    assert summary["cases"] == 1
    assert summary["evidence_recall"] == 1.0
    assert summary["dependency_recall"] == 1.0
