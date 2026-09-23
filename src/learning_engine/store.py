# =============================================================================
# Store del ciclo. Toda lectura filtra organization_id.
# =============================================================================
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from src.core.domain.learning_cycle import (
    EvaluationRecord,
    ExperimentRequest,
    ExperimentStatus,
    Finding,
    Hypothesis,
    PromotionAudit,
    Recommendation,
    RunSignal,
    StrategyComparison,
    merge_finding,
)

__all__ = [
    "InMemoryLearningStore",
    "LearningNotFound",
    "merge_finding",
]


class LearningNotFound(KeyError):
    pass


class InMemoryLearningStore:
    def __init__(self) -> None:
        self.signals: dict[UUID, RunSignal] = {}
        self.findings: dict[UUID, Finding] = {}
        self.hypotheses: dict[UUID, Hypothesis] = {}
        self.experiments: dict[UUID, ExperimentRequest] = {}
        self.evaluations: dict[UUID, EvaluationRecord] = {}
        self.recommendations: dict[UUID, Recommendation] = {}
        self.promotions: dict[UUID, PromotionAudit] = {}
        self.comparisons: dict[UUID, StrategyComparison] = {}
        self.conflicts: dict[UUID, object] = {}

    async def append_signal(self, signal: RunSignal) -> RunSignal:
        self.signals[signal.id] = signal
        return signal

    async def signals_in_window(self, organization_id: UUID, start: datetime | None) -> list[RunSignal]:
        rows = [row for row in self.signals.values() if row.organization_id == organization_id]
        if start is None:
            return rows
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        selected = []
        for row in rows:
            occurred = row.occurred_at
            if occurred.tzinfo is None:
                occurred = occurred.replace(tzinfo=timezone.utc)
            if occurred >= start:
                selected.append(row)
        return selected

    async def unclustered_signals(self, organization_id: UUID) -> list[RunSignal]:
        return [
            row
            for row in self.signals.values()
            if row.organization_id == organization_id and not row.clustered
        ]

    async def mark_clustered(self, organization_id: UUID, signal_ids: list[UUID]) -> None:
        for signal_id in signal_ids:
            row = self.signals.get(signal_id)
            if row is not None and row.organization_id == organization_id:
                row.clustered = True

    async def upsert_finding(self, finding: Finding) -> Finding:
        for current in self.findings.values():
            if current.organization_id == finding.organization_id and current.dedupe_key == finding.dedupe_key:
                return merge_finding(current, finding)
        self.findings[finding.id] = finding
        return finding

    async def list_findings(self, organization_id: UUID, *, limit: int = 50, offset: int = 0) -> list[Finding]:
        rows = [row for row in self.findings.values() if row.organization_id == organization_id]
        rows.sort(key=lambda row: row.last_seen, reverse=True)
        return rows[offset : offset + limit]

    async def get_finding(self, organization_id: UUID, finding_id: UUID) -> Finding | None:
        row = self.findings.get(finding_id)
        if row is None or row.organization_id != organization_id:
            return None
        return row

    async def upsert_hypothesis(self, hypothesis: Hypothesis) -> Hypothesis:
        for current in self.hypotheses.values():
            if current.organization_id == hypothesis.organization_id and current.finding_id == hypothesis.finding_id:
                return current
        self.hypotheses[hypothesis.id] = hypothesis
        return hypothesis

    async def list_hypotheses(self, organization_id: UUID) -> list[Hypothesis]:
        return [row for row in self.hypotheses.values() if row.organization_id == organization_id]

    async def get_hypothesis(self, organization_id: UUID, hypothesis_id: UUID) -> Hypothesis | None:
        row = self.hypotheses.get(hypothesis_id)
        if row is None or row.organization_id != organization_id:
            return None
        return row

    async def save_experiment(self, experiment: ExperimentRequest) -> ExperimentRequest:
        if experiment.id in self.experiments:
            self.experiments[experiment.id] = experiment
            return experiment
        for current in self.experiments.values():
            if (
                current.organization_id == experiment.organization_id
                and current.hypothesis_id == experiment.hypothesis_id
                and current.status == ExperimentStatus.QUEUED
            ):
                return current
        self.experiments[experiment.id] = experiment
        return experiment

    async def get_experiment(self, organization_id: UUID, experiment_id: UUID) -> ExperimentRequest | None:
        row = self.experiments.get(experiment_id)
        if row is None or row.organization_id != organization_id:
            return None
        return row

    async def save_evaluation(self, evaluation: EvaluationRecord) -> EvaluationRecord:
        self.evaluations[evaluation.id] = evaluation
        return evaluation

    async def save_recommendation(self, recommendation: Recommendation) -> Recommendation:
        self.recommendations[recommendation.id] = recommendation
        return recommendation

    async def list_recommendations(self, organization_id: UUID) -> list[Recommendation]:
        return [row for row in self.recommendations.values() if row.organization_id == organization_id]

    async def get_recommendation(self, organization_id: UUID, recommendation_id: UUID) -> Recommendation | None:
        row = self.recommendations.get(recommendation_id)
        if row is None or row.organization_id != organization_id:
            return None
        return row

    async def save_promotion(self, promotion: PromotionAudit) -> PromotionAudit:
        self.promotions[promotion.id] = promotion
        return promotion

    async def get_promotion(self, organization_id: UUID, promotion_id: UUID) -> PromotionAudit | None:
        row = self.promotions.get(promotion_id)
        if row is None or row.organization_id != organization_id:
            return None
        return row

    async def list_promotions(self, organization_id: UUID) -> list[PromotionAudit]:
        return [row for row in self.promotions.values() if row.organization_id == organization_id]

    async def save_comparison(self, comparison: StrategyComparison) -> StrategyComparison:
        for current in self.comparisons.values():
            if (
                current.organization_id == comparison.organization_id
                and current.kind == comparison.kind
                and current.pattern_key == comparison.pattern_key
                and current.window == comparison.window
            ):
                current.rows = list(comparison.rows)
                current.sample_size = comparison.sample_size
                current.confidence = comparison.confidence
                current.validated_memory_id = comparison.validated_memory_id
                current.judgment_signal = comparison.judgment_signal
                return current
        self.comparisons[comparison.id] = comparison
        return comparison

    async def save_finding(self, finding: Finding) -> Finding:
        self.findings[finding.id] = finding
        return finding

    async def save_hypothesis(self, hypothesis: Hypothesis) -> Hypothesis:
        self.hypotheses[hypothesis.id] = hypothesis
        return hypothesis

    async def list_comparisons(self, organization_id: UUID, *, kind: str | None = None) -> list[StrategyComparison]:
        rows = [row for row in self.comparisons.values() if row.organization_id == organization_id]
        if kind:
            rows = [row for row in rows if row.kind == kind]
        return rows

    async def organizations_with_recent_signals(self, start: datetime) -> list[UUID]:
        found: list[UUID] = []
        for row in self.signals.values():
            occurred = row.occurred_at
            if occurred.tzinfo is None:
                occurred = occurred.replace(tzinfo=timezone.utc)
            if occurred >= start and row.organization_id not in found:
                found.append(row.organization_id)
        return found

    async def save_conflict(self, conflict):
        self.conflicts[conflict.id] = conflict
        return conflict

    async def get_conflict(self, organization_id: UUID, conflict_id: UUID):
        row = self.conflicts.get(conflict_id)
        if row is None or row.organization_id != organization_id:
            return None
        return row
