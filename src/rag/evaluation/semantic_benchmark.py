# =============================================================================
# Semantic Benchmark — BASELINE vs NUEVO (§67)
# =============================================================================
# Compara dos modos de retrieval sobre los MISMOS casos:
#
#   BASELINE: nutrient chunks planos.
#   NUEVO:    Semantic Fabric + Dynamic Context (dependencias + contexto
#             compilado + expansión por grafo).
#
# Métricas: answer correctness (proxy determinista), evidence recall,
# dependency recall, citation precision, abstention precision, context tokens,
# latency y cost. Sin mejora medible no hay promoción.
# =============================================================================
from __future__ import annotations

import json
from dataclasses import dataclass, field

BENCHMARK_VERSION = "semantic-benchmark-1"


@dataclass(frozen=True, kw_only=True)
class SemanticBenchCase:
    case_id: str
    question: str
    expected_sources: tuple[str, ...] = ()
    expected_evidence: tuple[str, ...] = ()
    expected_dependencies: tuple[str, ...] = ()
    expected_citations: tuple[str, ...] = ()
    expect_abstention: bool = False
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "question": self.question[:300],
            "expected_sources": list(self.expected_sources),
            "expected_evidence": list(self.expected_evidence),
            "expected_dependencies": list(self.expected_dependencies),
            "expected_citations": list(self.expected_citations),
            "expect_abstention": bool(self.expect_abstention),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, kw_only=True)
class ModeObservation:
    """Lo que un modo produjo para un caso (real o precomputado)."""

    mode: str
    retrieved_sources: tuple[str, ...] = ()
    retrieved_evidence: tuple[str, ...] = ()
    retrieved_dependencies: tuple[str, ...] = ()
    citations: tuple[str, ...] = ()
    abstained: bool = False
    context_tokens: int = 0
    latency_ms: float = 0.0
    cost_usd: float = 0.0

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "retrieved_sources": list(self.retrieved_sources),
            "retrieved_evidence": list(self.retrieved_evidence),
            "retrieved_dependencies": list(self.retrieved_dependencies),
            "citations": list(self.citations),
            "abstained": bool(self.abstained),
            "context_tokens": int(self.context_tokens),
            "latency_ms": round(float(self.latency_ms), 2),
            "cost_usd": round(float(self.cost_usd), 6),
        }


def load_benchmark_cases(payload: list[dict]) -> list[SemanticBenchCase]:
    cases: list[SemanticBenchCase] = []
    for index, raw in enumerate(payload or ()):
        if not isinstance(raw, dict):
            continue
        question = str(raw.get("question") or "").strip()
        if not question:
            continue
        cases.append(
            SemanticBenchCase(
                case_id=str(raw.get("case_id") or f"case-{index}"),
                question=question,
                expected_sources=tuple(
                    str(value) for value in raw.get("expected_sources") or ()
                ),
                expected_evidence=tuple(
                    str(value) for value in raw.get("expected_evidence") or ()
                ),
                expected_dependencies=tuple(
                    str(value) for value in raw.get("expected_dependencies") or ()
                ),
                expected_citations=tuple(
                    str(value) for value in raw.get("expected_citations") or ()
                ),
                expect_abstention=bool(raw.get("expect_abstention")),
                metadata=dict(raw.get("metadata") or {}),
            )
        )
    return cases


def _recall(retrieved: tuple[str, ...], expected: tuple[str, ...]) -> float | None:
    if not expected:
        return None
    hits = len(set(retrieved) & set(expected))
    return round(hits / len(expected), 4)


def _citation_precision(
    observation: ModeObservation, case: SemanticBenchCase
) -> float | None:
    if not observation.citations:
        return None
    if not case.expected_citations:
        # Sin expectativa declarada no se premia ni castiga: None honesto.
        return None
    hits = len(set(observation.citations) & set(case.expected_citations))
    return round(hits / len(observation.citations), 4)


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def observe_case(
    case: SemanticBenchCase, observation: ModeObservation
) -> dict:
    evidence_recall = _recall(
        observation.retrieved_evidence, case.expected_evidence
    )
    dependency_recall = _recall(
        observation.retrieved_dependencies, case.expected_dependencies
    )
    citation_precision = _citation_precision(observation, case)
    abstention_correct = (
        bool(observation.abstained) == bool(case.expect_abstention)
        if case.expect_abstention
        else None
    )
    correctness_components = [
        value
        for value in (evidence_recall, dependency_recall, citation_precision)
        if value is not None
    ]
    answer_correctness = _mean(correctness_components)
    return {
        "case_id": case.case_id,
        "question": case.question[:200],
        "mode": observation.mode,
        "answer_correctness": answer_correctness,
        "evidence_recall": evidence_recall,
        "dependency_recall": dependency_recall,
        "citation_precision": citation_precision,
        "abstention_correct": abstention_correct,
        "context_tokens": int(observation.context_tokens),
        "latency_ms": round(float(observation.latency_ms), 2),
        "cost_usd": round(float(observation.cost_usd), 6),
    }


def summarize_mode(
    cases: list[SemanticBenchCase], observations: dict[str, ModeObservation]
) -> dict:
    """Resumen agregado de un modo: caso -> observación."""
    by_case = {case.case_id: case for case in cases}
    rows = [
        observe_case(by_case[case_id], observation)
        for case_id, observation in observations.items()
        if case_id in by_case
    ]
    return _aggregate(rows)


def compare_semantic_modes(
    cases: list[SemanticBenchCase],
    *,
    baseline: dict[str, ModeObservation],
    candidate: dict[str, ModeObservation],
) -> dict:
    """Compara los dos modos caso por caso y agrega métricas honestas."""
    per_case: list[dict] = []
    baseline_rows: list[dict] = []
    candidate_rows: list[dict] = []
    for case in cases:
        base = baseline.get(case.case_id)
        cand = candidate.get(case.case_id)
        if base is None and cand is None:
            continue
        row: dict = {"case_id": case.case_id, "question": case.question[:200]}
        if base is not None:
            base_metrics = observe_case(case, base)
            baseline_rows.append(base_metrics)
            row["baseline"] = base_metrics
        if cand is not None:
            cand_metrics = observe_case(case, cand)
            candidate_rows.append(cand_metrics)
            row["candidate"] = cand_metrics
        if base is not None and cand is not None:
            row["delta"] = {
                key: _delta(cand_metrics.get(key), base_metrics.get(key))
                for key in (
                    "answer_correctness",
                    "evidence_recall",
                    "dependency_recall",
                    "citation_precision",
                )
            }
        per_case.append(row)

    summary_base = _aggregate(baseline_rows)
    summary_cand = _aggregate(candidate_rows)
    return {
        "version": BENCHMARK_VERSION,
        "cases": len(per_case),
        "baseline": summary_base,
        "candidate": summary_cand,
        "delta": {
            key: _delta(summary_cand.get(key), summary_base.get(key))
            for key in (
                "answer_correctness",
                "evidence_recall",
                "dependency_recall",
                "citation_precision",
                "abstention_precision",
                "context_tokens",
                "latency_ms",
                "cost_usd",
            )
        },
        "promotion_ready": _promotion_ready(summary_base, summary_cand),
        "per_case": per_case,
    }


def _delta(candidate_value, baseline_value) -> float | None:
    if candidate_value is None or baseline_value is None:
        return None
    return round(float(candidate_value) - float(baseline_value), 4)


def _aggregate(rows: list[dict]) -> dict:
    def values(key: str) -> list[float]:
        return [
            float(row[key])
            for row in rows
            if row.get(key) is not None
        ]

    abstention = [
        row["abstention_correct"]
        for row in rows
        if row.get("abstention_correct") is not None
    ]
    return {
        "cases": len(rows),
        "answer_correctness": _mean(values("answer_correctness")),
        "evidence_recall": _mean(values("evidence_recall")),
        "dependency_recall": _mean(values("dependency_recall")),
        "citation_precision": _mean(values("citation_precision")),
        "abstention_precision": _mean(
            [1.0 if value else 0.0 for value in abstention]
        ),
        "context_tokens": (
            round(_mean(values("context_tokens")) or 0.0, 2) if rows else None
        ),
        "latency_ms": round(_mean(values("latency_ms")) or 0.0, 2) if rows else None,
        "cost_usd": round(_mean(values("cost_usd")) or 0.0, 6) if rows else None,
    }


def _promotion_ready(baseline: dict, candidate: dict) -> bool:
    """Mejora medible en conocimiento, sin empeorar costo/latencia a lo loco."""
    def gain(key: str) -> float | None:
        base, cand = baseline.get(key), candidate.get(key)
        if base is None or cand is None:
            return None
        return float(cand) - float(base)

    knowledge_gains = [
        gain("dependency_recall"),
        gain("citation_precision"),
        gain("evidence_recall"),
        gain("answer_correctness"),
    ]
    positive = [value for value in knowledge_gains if value is not None and value > 0]
    if not positive:
        return False
    tokens_gain = gain("context_tokens")
    latency_gain = gain("latency_ms")
    if tokens_gain is not None and tokens_gain > 0.5 * max(
        1.0, float(baseline.get("context_tokens") or 0.0)
    ):
        return False
    if latency_gain is not None and latency_gain > 0.5 * max(
        1.0, float(baseline.get("latency_ms") or 0.0)
    ):
        return False
    return True


def render_benchmark_report(report: dict) -> str:
    """Reporte legible para PR/revisión (no es un resumen de marketing)."""
    base = report.get("baseline") or {}
    cand = report.get("candidate") or {}
    lines = [
        "# Semantic Benchmark (baseline vs fabric+dynamic context)",
        "",
        f"cases: {report.get('cases')}",
        "",
        "| metric | baseline | candidate | delta |",
        "|---|---|---|---|",
    ]
    for key in (
        "answer_correctness",
        "evidence_recall",
        "dependency_recall",
        "citation_precision",
        "abstention_precision",
        "context_tokens",
        "latency_ms",
        "cost_usd",
    ):
        delta = (report.get("delta") or {}).get(key)
        lines.append(
            f"| {key} | {base.get(key)} | {cand.get(key)} | {delta} |"
        )
    lines.append("")
    lines.append(f"promotion_ready: {bool(report.get('promotion_ready'))}")
    return "\n".join(lines)


def report_to_json(report: dict) -> str:
    return json.dumps(report, indent=2, default=str)


__all__ = [
    "BENCHMARK_VERSION",
    "ModeObservation",
    "SemanticBenchCase",
    "compare_semantic_modes",
    "load_benchmark_cases",
    "observe_case",
    "render_benchmark_report",
    "report_to_json",
    "summarize_mode",
]
