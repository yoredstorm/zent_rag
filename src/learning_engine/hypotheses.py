# =============================================================================
# Hipótesis medibles. El texto sale de los números del finding, no al revés.
# =============================================================================
from __future__ import annotations

from src.core.domain.learning_cycle import (
    ExperimentKind,
    ExperimentMode,
    ExperimentRequest,
    Finding,
    Hypothesis,
    ToolStep,
)
from src.learning_engine.safety import assert_experiment_safe

_KIND = {
    "retrieval": (ExperimentMode.GOLDEN_SET, ExperimentKind.RETRIEVAL_STRATEGY),
    "agent": (ExperimentMode.REPLAY, ExperimentKind.AGENT_RETRY_POLICY),
    "decision": (ExperimentMode.SHADOW, ExperimentKind.JEV),
    "cost": (ExperimentMode.REPLAY, ExperimentKind.LLM_MODEL),
    "grounding": (ExperimentMode.GOLDEN_SET, ExperimentKind.RETRIEVAL_STRATEGY),
    "knowledge": (ExperimentMode.REPLAY, ExperimentKind.STRUCTURED_NORMALIZATION),
}


def form_hypothesis(finding: Finding, *, minimum_improvement: float = 0.05) -> Hypothesis | None:
    baseline = finding.baseline_strategy.strip()
    candidate = finding.candidate_strategy.strip()
    if not baseline or not candidate or baseline == candidate:
        return None
    metric = "task_success"
    if finding.category == "cost":
        metric = "cost"
    elif finding.category == "grounding":
        metric = "grounding"
    statement = (
        f"{candidate} may outperform {baseline} for {finding.pattern_key} "
        f"on {metric}, with a minimum relative improvement of {minimum_improvement:.0%}. "
        f"Scope: {finding.pattern_key}."
    )
    return Hypothesis(
        organization_id=finding.organization_id,
        finding_id=finding.id,
        statement=statement,
        baseline=baseline,
        candidate=candidate,
        expected_metric=metric,
        minimum_improvement=minimum_improvement,
        scope=finding.pattern_key,
        guardrails={"grounding_min_delta": 0.0, "quality_min_delta": 0.0, "min_sample": 20},
    )


def experiment_for(hypothesis: Hypothesis, finding: Finding) -> ExperimentRequest:
    mode, kind = _KIND.get(finding.category, (ExperimentMode.REPLAY, ExperimentKind.WORKFLOW_ROUTE))
    tools: tuple[ToolStep, ...] = ()
    if finding.category == "agent":
        tools = (
            ToolStep(name="query_database", execution="dry_run", side_effect=False),
            ToolStep(name="inspect_schema", execution="dry_run", side_effect=False),
        )
    assert_experiment_safe(mode, tools)
    return ExperimentRequest(
        organization_id=hypothesis.organization_id,
        hypothesis_id=hypothesis.id,
        finding_id=finding.id,
        mode=mode,
        kind=kind,
        baseline=hypothesis.baseline,
        candidate=hypothesis.candidate,
        tool_plan=tools,
        memory_id=finding.memory_id,
    )
