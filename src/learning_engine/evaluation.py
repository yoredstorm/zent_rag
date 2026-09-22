# =============================================================================
# Baseline vs candidate. Los medios y el tamaño de muestra quedan guardados.
# =============================================================================
from __future__ import annotations

from dataclasses import fields
from typing import Any

from src.core.domain.learning_cycle import (
    HIGHER_IS_BETTER,
    LOWER_IS_BETTER,
    EvaluationRecord,
    MetricSample,
)
from src.learning_engine.windows import confidence_for
from src.runtime.experiments import summarize


def _mean(samples: list[MetricSample], name: str) -> float | None:
    values = [getattr(sample, name) for sample in samples if getattr(sample, name) is not None]
    if not values:
        return None
    return sum(float(value) for value in values) / len(values)


def _means(samples: list[MetricSample]) -> dict[str, float | None]:
    names = [item.name for item in fields(MetricSample)]
    return {name: _mean(samples, name) for name in names}


def _relative(baseline: float | None, candidate: float | None, *, higher: bool) -> float | None:
    if baseline is None or candidate is None:
        return None
    if baseline == 0:
        return candidate - baseline if higher else baseline - candidate
    if higher:
        return (candidate - baseline) / abs(baseline)
    return (baseline - candidate) / abs(baseline)


def compare_arms(
    organization_id,
    experiment_id,
    baseline: list[MetricSample],
    candidate: list[MetricSample],
) -> EvaluationRecord:
    if not baseline or not candidate:
        raise ValueError("comparison requires baseline and candidate samples")
    sample_size = min(len(baseline), len(candidate))
    base_means = _means(baseline)
    cand_means = _means(candidate)
    deltas: dict[str, float | None] = {}
    for name, base in base_means.items():
        higher = name in HIGHER_IS_BETTER
        if name not in HIGHER_IS_BETTER and name not in LOWER_IS_BETTER:
            continue
        deltas[name] = _relative(base, cand_means.get(name), higher=higher)
    signed = _signed_changes(base_means, cand_means)
    return EvaluationRecord(
        organization_id=organization_id,
        experiment_id=experiment_id,
        sample_size=sample_size,
        confidence=confidence_for(sample_size),
        baseline_means=base_means,
        candidate_means=cand_means,
        deltas=deltas,
        reproducible={
            "sample_size": sample_size,
            "baseline_means": base_means,
            "candidate_means": cand_means,
            "signed_changes": signed,
            "higher_is_better": sorted(HIGHER_IS_BETTER),
            "lower_is_better": sorted(LOWER_IS_BETTER),
        },
    )


def _signed_changes(
    baseline: dict[str, float | None], candidate: dict[str, float | None]
) -> dict[str, float | None]:
    """Cambio firmado (candidato - base) / |base|. Negativo en latencia = más rápido."""
    signed: dict[str, float | None] = {}
    for name in ("quality", "task_success", "grounding", "latency_ms", "cost"):
        base = baseline.get(name)
        cand = candidate.get(name)
        if base is None or cand is None or base == 0:
            signed[name] = None
            continue
        signed[name] = (cand - base) / abs(base)
    return signed


def lab_summary(report: dict[str, Any]) -> dict[str, Any]:
    """Reutiliza Experiment Lab. No compara proveedores por su cuenta."""
    return summarize(report)


def samples_from_lab(
    report: dict[str, Any],
    *,
    baseline: str,
    candidate: str,
) -> tuple[list[MetricSample], list[MetricSample]]:
    summary = lab_summary(report)
    return [_arm(summary.get(baseline))], [_arm(summary.get(candidate))]


def _arm(row: dict[str, Any] | None) -> MetricSample:
    if not row:
        return MetricSample()
    accuracy = row.get("routing_accuracy")
    return MetricSample(
        task_success=float(accuracy) if accuracy is not None else None,
        latency_ms=row.get("average_latency_ms"),
        cost=row.get("cost"),
        tokens=row.get("tokens"),
        fallbacks=row.get("fallback_rate"),
    )
