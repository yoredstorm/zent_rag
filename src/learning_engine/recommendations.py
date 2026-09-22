# =============================================================================
# Recomendación cuantificada. El texto cita métricas. No hay chain-of-thought.
# =============================================================================
from __future__ import annotations

from src.core.domain.learning_cycle import (
    EvaluationRecord,
    Hypothesis,
    Recommendation,
    RecommendationAction,
)


def suggest_action(evaluation: EvaluationRecord, hypothesis: Hypothesis) -> RecommendationAction:
    guardrails = hypothesis.guardrails or {}
    min_sample = int(guardrails.get("min_sample", 20))
    if evaluation.sample_size < min_sample:
        return RecommendationAction.CONTINUE_TESTING
    if _guardrail_broken(evaluation, "grounding", float(guardrails.get("grounding_min_delta", 0.0))):
        return RecommendationAction.REJECT
    if _guardrail_broken(evaluation, "quality", float(guardrails.get("quality_min_delta", 0.0))):
        return RecommendationAction.REJECT
    if _guardrail_broken(evaluation, "task_success", float(guardrails.get("quality_min_delta", 0.0))):
        return RecommendationAction.REJECT
    delta = evaluation.deltas.get(hypothesis.expected_metric)
    if delta is None:
        return RecommendationAction.CONTINUE_TESTING
    if delta + 1e-9 >= float(hypothesis.minimum_improvement):
        return RecommendationAction.PROMOTE
    if delta < 0:
        return RecommendationAction.REJECT
    return RecommendationAction.CONTINUE_TESTING


def _guardrail_broken(evaluation: EvaluationRecord, metric: str, minimum: float) -> bool:
    base = evaluation.baseline_means.get(metric)
    cand = evaluation.candidate_means.get(metric)
    if base is None or cand is None:
        return False
    return (cand - base) < minimum


def explain(evaluation: EvaluationRecord, hypothesis: Hypothesis, problem: str) -> str:
    signed = evaluation.reproducible.get("signed_changes") or {}
    parts = [
        problem.strip(),
        f"Baseline {hypothesis.baseline}.",
        f"Candidato {hypothesis.candidate}.",
    ]
    labels = (
        ("Calidad", "task_success"),
        ("Grounding", "grounding"),
        ("Latencia", "latency_ms"),
        ("Costo", "cost"),
    )
    for label, key in labels:
        value = signed.get(key)
        if value is None:
            continue
        parts.append(f"{label} {value * 100:+.1f}%.")
    parts.append(f"Muestra {evaluation.sample_size}.")
    parts.append(f"Confianza {evaluation.confidence}.")
    return " ".join(part for part in parts if part)


def build_recommendation(
    *,
    evaluation: EvaluationRecord,
    hypothesis: Hypothesis,
    problem: str,
    finding_id,
    memory_id,
    action: RecommendationAction,
) -> Recommendation:
    return Recommendation(
        organization_id=evaluation.organization_id,
        experiment_id=evaluation.experiment_id,
        evaluation_id=evaluation.id,
        finding_id=finding_id,
        hypothesis_id=hypothesis.id,
        memory_id=memory_id,
        problem=problem,
        baseline=hypothesis.baseline,
        candidate=hypothesis.candidate,
        suggested_action=action,
        explanation=explain(evaluation, hypothesis, problem),
        sample_size=evaluation.sample_size,
        confidence=evaluation.confidence,
        deltas=dict(evaluation.reproducible.get("signed_changes") or {}),
        metrics={
            "baseline": evaluation.baseline_means,
            "candidate": evaluation.candidate_means,
            "relative": evaluation.deltas,
        },
    )
