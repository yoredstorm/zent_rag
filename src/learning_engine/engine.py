# =============================================================================
# LearningEngine — observa, agrupa, hipotetiza, pide experimentos, recomienda.
# No muta producción. La promoción exige un actor administrativo.
# =============================================================================
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol
from uuid import UUID

from src.core.domain.learning_cycle import (
    ExperimentStatus,
    FindingStatus,
    HypothesisStatus,
    MetricSample,
    PromotionAudit,
    Recommendation,
    RecommendationAction,
    RecommendationStatus,
    RunSignal,
    StrategyComparison,
    WindowName,
)
from src.core.domain.memory import MemoryStatus, MemoryType, ValidationPath
from src.learning_engine.clusters import sync_clusters
from src.learning_engine.detector import detect
from src.learning_engine.evaluation import compare_arms, lab_summary
from src.learning_engine.hypotheses import experiment_for, form_hypothesis
from src.learning_engine.recommendations import build_recommendation, suggest_action
from src.learning_engine.store import InMemoryLearningStore, LearningNotFound
from src.learning_engine.windows import confidence_for, slice_window, window_start
from src.memory.policy import MemoryMaturityPolicy, MemoryPolicyError
from src.memory.service import MemoryFoundationService, MemoryObservation
from src.memory.signature import PatternFeatures

_REJECTABLE = {
    MemoryStatus.OBSERVED,
    MemoryStatus.REINFORCED,
    MemoryStatus.PATTERN,
    MemoryStatus.VALIDATED,
}
_SIGNAL_STATUSES = {MemoryStatus.VALIDATED, MemoryStatus.ACTIVE}


class PromotionDenied(PermissionError):
    """Promoción sin actor admin, o experimento que no es claramente mejor."""


class ConfigPort(Protocol):
    async def snapshot(self, organization_id: UUID) -> dict[str, Any]: ...

    async def apply(self, organization_id: UUID, *, candidate: str, baseline: str) -> dict[str, Any]: ...

    async def rollback(self, organization_id: UUID, snapshot: dict[str, Any]) -> None: ...


@dataclass
class AnalysisReport:
    findings: list = field(default_factory=list)
    hypotheses: list = field(default_factory=list)
    experiments: list = field(default_factory=list)
    comparisons: list = field(default_factory=list)
    clustered: list = field(default_factory=list)


class LearningEngine:
    """Coordinador. AUTONOMOUS_PRODUCTION_MUTATION permanece en False."""

    AUTONOMOUS_PRODUCTION_MUTATION = False

    def __init__(
        self,
        store: InMemoryLearningStore,
        memory: MemoryFoundationService,
        *,
        config_port: ConfigPort | None = None,
        every_n: int = 50,
        min_sample: int = 20,
        auto_window: WindowName = WindowName.LAST_24H,
    ) -> None:
        if every_n < 1:
            raise ValueError("every_n must be >= 1")
        if min_sample < 1:
            raise ValueError("min_sample must be >= 1")
        self._store = store
        self._memory = memory
        self._config = config_port
        self._every_n = every_n
        self._min_sample = min_sample
        self._auto_window = auto_window
        self._pending = 0
        self._maturity = MemoryMaturityPolicy()

    async def ingest(
        self,
        signals: list[RunSignal],
        *,
        analyze: bool = False,
        window: WindowName = WindowName.LAST_24H,
    ) -> AnalysisReport | None:
        if not signals:
            return None
        organization_id = signals[0].organization_id
        for signal in signals:
            if signal.organization_id != organization_id:
                raise ValueError("a batch must belong to one organization")
            await self._store.append_signal(signal)
        if not analyze:
            return None
        return await self.analyze(organization_id, window=window)

    async def note(self, signal: RunSignal) -> AnalysisReport | None:
        """Evento suelto. El análisis corre cada N eventos, no en cada mensaje."""
        await self._store.append_signal(signal)
        self._pending += 1
        if self._pending < self._every_n:
            return None
        self._pending = 0
        return await self.analyze(signal.organization_id, window=self._auto_window)

    async def analyze(
        self,
        organization_id: UUID,
        *,
        window: WindowName = WindowName.LAST_24H,
        now: datetime | None = None,
    ) -> AnalysisReport:
        current = now or datetime.now(timezone.utc)
        start = window_start(window, current)
        window_signals = slice_window(
            await self._store.signals_in_window(organization_id, start),
            window,
            current,
        )
        fresh = await self._store.unclustered_signals(organization_id)
        if window != WindowName.ALL_TIME:
            visible = {signal.id for signal in window_signals}
            fresh = [signal for signal in fresh if signal.id in visible]
        clustered = await sync_clusters(self._memory, fresh, context=window_signals)
        await self._store.mark_clustered(organization_id, [signal.id for signal in fresh])
        index = {(item.pattern_key, item.strategy): item.record.id for item in clustered}
        hits = detect(window_signals, window=window, min_sample=self._min_sample)
        findings = []
        hypotheses = []
        experiments = []
        for hit in hits:
            finding = hit.to_finding(organization_id, current)
            finding.memory_id = index.get((finding.pattern_key, finding.candidate_strategy))
            finding = await self._store.upsert_finding(finding)
            hypothesis = form_hypothesis(finding, minimum_improvement=0.05)
            if hypothesis is None:
                findings.append(finding)
                continue
            finding.status = FindingStatus.HYPOTHESIZED
            hypothesis = await self._store.upsert_hypothesis(hypothesis)
            experiment = experiment_for(hypothesis, finding)
            experiment.memory_id = finding.memory_id
            experiment = await self._store.save_experiment(experiment)
            finding.status = FindingStatus.EXPERIMENTING
            await self._store.save_finding(finding)
            findings.append(finding)
            hypotheses.append(hypothesis)
            experiments.append(experiment)
        comparisons = await self._save_comparisons(organization_id, window_signals, window)
        return AnalysisReport(
            findings=findings,
            hypotheses=hypotheses,
            experiments=experiments,
            comparisons=comparisons,
            clustered=clustered,
        )

    async def complete_experiment(
        self,
        organization_id: UUID,
        experiment_id: UUID,
        *,
        baseline: list[MetricSample],
        candidate: list[MetricSample],
        lab_report: dict[str, Any] | None = None,
    ) -> Recommendation:
        experiment = await self._require_experiment(organization_id, experiment_id)
        hypothesis = await self._store.get_hypothesis(organization_id, experiment.hypothesis_id)
        finding = await self._store.get_finding(organization_id, experiment.finding_id)
        if hypothesis is None or finding is None:
            raise LearningNotFound(str(experiment_id))
        evaluation = compare_arms(organization_id, experiment.id, baseline, candidate)
        if lab_report is not None:
            evaluation.reproducible["lab"] = lab_summary(lab_report)
        evaluation = await self._store.save_evaluation(evaluation)
        action = suggest_action(evaluation, hypothesis)
        memory_id = experiment.memory_id or finding.memory_id
        if action == RecommendationAction.PROMOTE and memory_id is not None:
            await self._validate_memory(organization_id, memory_id)
            hypothesis.status = HypothesisStatus.SUPPORTED
        elif action == RecommendationAction.REJECT:
            hypothesis.status = HypothesisStatus.REJECTED
            if evaluation.sample_size >= int(hypothesis.guardrails.get("min_sample", 20)):
                await self._reject_memory(organization_id, memory_id)
        else:
            hypothesis.status = HypothesisStatus.TESTING
        await self._store.save_hypothesis(hypothesis)
        problem = finding.observed or finding.pattern_key
        recommendation = build_recommendation(
            evaluation=evaluation,
            hypothesis=hypothesis,
            problem=problem,
            finding_id=finding.id,
            memory_id=memory_id,
            action=action,
        )
        recommendation = await self._store.save_recommendation(recommendation)
        experiment.status = ExperimentStatus.COMPLETED
        finding.status = FindingStatus.RECOMMENDED
        await self._store.save_experiment(experiment)
        await self._store.save_finding(finding)
        return recommendation

    async def promote(
        self,
        organization_id: UUID,
        recommendation_id: UUID,
        *,
        actor_id: UUID | None,
        is_admin: bool,
    ) -> PromotionAudit:
        if actor_id is None or not is_admin:
            raise PromotionDenied("promotion requires an administrative actor")
        recommendation = await self._require_recommendation(organization_id, recommendation_id)
        if recommendation.status != RecommendationStatus.PENDING:
            raise PromotionDenied("recommendation is not pending")
        if recommendation.suggested_action != RecommendationAction.PROMOTE:
            raise PromotionDenied("experiment is not clearly better")
        previous: dict[str, Any] = {}
        applied: dict[str, Any] = {}
        mutated = False
        if self._config is not None:
            previous = await self._config.snapshot(organization_id)
            applied = await self._config.apply(
                organization_id,
                candidate=recommendation.candidate,
                baseline=recommendation.baseline,
            )
            mutated = True
        if recommendation.memory_id is not None:
            record = await self._memory.get(organization_id, recommendation.memory_id)
            if record.status == MemoryStatus.VALIDATED:
                await self._memory.activate(
                    organization_id,
                    recommendation.memory_id,
                    actor_id=actor_id,
                    source_component="learning.engine",
                )
        audit = PromotionAudit(
            organization_id=organization_id,
            actor_id=actor_id,
            recommendation_id=recommendation.id,
            experiment_id=recommendation.experiment_id,
            memory_id=recommendation.memory_id,
            baseline=recommendation.baseline,
            candidate=recommendation.candidate,
            metrics=dict(recommendation.metrics),
            config_mutated=mutated,
            previous_snapshot=previous,
            applied_snapshot=applied,
        )
        recommendation.status = RecommendationStatus.PROMOTED
        await self._store.save_recommendation(recommendation)
        return await self._store.save_promotion(audit)

    async def resolve(
        self,
        organization_id: UUID,
        recommendation_id: UUID,
        action: RecommendationAction | str,
        *,
        actor_id: UUID | None,
        is_admin: bool,
    ) -> Recommendation | PromotionAudit:
        chosen = RecommendationAction(action)
        if chosen == RecommendationAction.PROMOTE:
            return await self.promote(
                organization_id,
                recommendation_id,
                actor_id=actor_id,
                is_admin=is_admin,
            )
        if actor_id is None or not is_admin:
            raise PromotionDenied("resolution requires an administrative actor")
        recommendation = await self._require_recommendation(organization_id, recommendation_id)
        if chosen == RecommendationAction.CONTINUE_TESTING:
            recommendation.status = RecommendationStatus.CONTINUED
            return await self._store.save_recommendation(recommendation)
        recommendation.status = RecommendationStatus.REJECTED
        await self._reject_memory(organization_id, recommendation.memory_id)
        return await self._store.save_recommendation(recommendation)

    async def rollback(
        self,
        organization_id: UUID,
        promotion_id: UUID,
        *,
        actor_id: UUID | None,
        is_admin: bool,
    ) -> PromotionAudit:
        if actor_id is None or not is_admin:
            raise PromotionDenied("rollback requires an administrative actor")
        promotion = await self._store.get_promotion(organization_id, promotion_id)
        if promotion is None:
            raise LearningNotFound(str(promotion_id))
        if promotion.rolled_back_at is not None:
            raise PromotionDenied("promotion already rolled back")
        if self._config is not None and promotion.previous_snapshot:
            await self._config.rollback(organization_id, promotion.previous_snapshot)
        if promotion.memory_id is not None:
            record = await self._memory.get(organization_id, promotion.memory_id)
            if record.status == MemoryStatus.ACTIVE:
                await self._memory.deactivate(
                    organization_id,
                    promotion.memory_id,
                    actor_id=actor_id,
                    source_component="learning.engine",
                )
        promotion.rolled_back_at = datetime.now(timezone.utc)
        promotion.rolled_back_by = actor_id
        promotion.config_mutated = False
        return await self._store.save_promotion(promotion)

    async def reevaluate(
        self,
        organization_id: UUID,
        *,
        window: WindowName = WindowName.LAST_7D,
        now: datetime | None = None,
    ) -> list[str]:
        current = now or datetime.now(timezone.utc)
        start = window_start(window, current)
        signals = await self._store.signals_in_window(organization_id, start)
        records = await self._memory.list_memories(organization_id, status=MemoryStatus.ACTIVE.value, limit=100)
        changed: list[str] = []
        for record in records:
            matched = [
                signal
                for signal in signals
                if signal.pattern_key in {record.pattern_key, record.intent_family}
            ]
            if len(matched) >= self._min_sample:
                rate = sum(1 for signal in matched if signal.success) / len(matched)
                if record.success_rate - rate >= 0.15 and rate < 0.5:
                    await self._memory.contradict(_observation_from(record, outcome="degraded"))
                    changed.append(f"contradicted:{record.id}")
                    continue
            if self._maturity.is_stale(record, now=current):
                await self._memory.mark_stale(
                    organization_id, record.id, source_component="learning.engine"
                )
                changed.append(f"stale:{record.id}")
        return changed

    async def list_findings(self, organization_id: UUID, *, limit: int = 50, offset: int = 0):
        return await self._store.list_findings(organization_id, limit=limit, offset=offset)

    async def list_recommendations(self, organization_id: UUID):
        return await self._store.list_recommendations(organization_id)

    async def list_comparisons(self, organization_id: UUID, *, kind: str | None = None):
        return await self._store.list_comparisons(organization_id, kind=kind)

    async def record_conflicts(self, claims: list):
        from src.learning_engine.conflicts import detect_conflicts

        found = detect_conflicts(claims)
        saved = []
        for item in found:
            saved.append(await self._store.save_conflict(item))
        return saved

    async def resolve_conflict(
        self,
        organization_id: UUID,
        conflict_id: UUID,
        *,
        actor_id: UUID,
        chosen_claim_id: UUID,
        reason: str,
    ):
        from src.learning_engine.conflicts import resolve_conflict as _resolve

        current = await self._store.get_conflict(organization_id, conflict_id)
        if current is None:
            raise LearningNotFound(str(conflict_id))
        resolved = _resolve(
            current, actor_id=actor_id, chosen_claim_id=chosen_claim_id, reason=reason
        )
        return await self._store.save_conflict(resolved)

    async def analyze_recent(self, *, limit: int = 50) -> int:
        organizations = await self._store.organizations_with_recent_signals(periodic_cutoff(24))
        ran = 0
        for organization_id in organizations[:limit]:
            await self.analyze(organization_id, window=WindowName.LAST_24H)
            ran += 1
        return ran

    async def _save_comparisons(self, organization_id, signals, window) -> list[StrategyComparison]:
        memories = await self._memory.list_memories(organization_id, limit=100)
        signal_ids = {}
        for record in memories:
            if record.status in _SIGNAL_STATUSES:
                signal_ids[record.pattern_key] = record.id
                signal_ids[record.intent_family] = record.id
        saved: list[StrategyComparison] = []
        grouped: dict[str, list[RunSignal]] = defaultdict(list)
        for signal in signals:
            grouped[signal.pattern_key].append(signal)
        for pattern, rows in grouped.items():
            if len(rows) < self._min_sample:
                continue
            by_strategy: dict[str, list[RunSignal]] = defaultdict(list)
            for row in rows:
                if row.retrieval_strategy:
                    by_strategy[row.retrieval_strategy].append(row)
            if by_strategy:
                comparison_rows = []
                for strategy, group in by_strategy.items():
                    successes = sum(1 for item in group if item.success)
                    comparison_rows.append(
                        {
                            "strategy": strategy,
                            "runs": len(group),
                            "successful": successes,
                            "success_rate": round(successes / len(group), 4),
                            "average_latency_ms": round(sum(item.latency_ms for item in group) / len(group), 2),
                            "average_cost": round(sum(item.cost for item in group) / len(group), 6),
                        }
                    )
                memory_id = signal_ids.get(pattern)
                saved.append(
                    await self._store.save_comparison(
                        StrategyComparison(
                            organization_id=organization_id,
                            pattern_key=pattern,
                            window=WindowName(window).value,
                            kind="retrieval",
                            rows=comparison_rows,
                            sample_size=len(rows),
                            confidence=confidence_for(len(rows)),
                            validated_memory_id=memory_id,
                            judgment_signal=memory_id is not None,
                            production_policy_controls_execution=True,
                        )
                    )
                )
        return saved

    async def _validate_memory(self, organization_id: UUID, memory_id: UUID) -> None:
        try:
            record = await self._memory.get(organization_id, memory_id)
        except Exception:
            return
        if record.status in {MemoryStatus.VALIDATED, MemoryStatus.ACTIVE}:
            return
        try:
            await self._memory.validate(
                organization_id,
                memory_id,
                via=ValidationPath.EXPERIMENT,
                source_component="learning.engine",
            )
        except MemoryPolicyError:
            return

    async def _reject_memory(self, organization_id: UUID, memory_id: UUID | None) -> None:
        if memory_id is None:
            return
        try:
            record = await self._memory.get(organization_id, memory_id)
        except Exception:
            return
        if record.status not in _REJECTABLE:
            return
        try:
            await self._memory.reject(
                organization_id,
                memory_id,
                source_component="learning.engine",
            )
        except MemoryPolicyError:
            return

    async def _require_experiment(self, organization_id: UUID, experiment_id: UUID):
        row = await self._store.get_experiment(organization_id, experiment_id)
        if row is None:
            raise LearningNotFound(str(experiment_id))
        return row

    async def _require_recommendation(self, organization_id: UUID, recommendation_id: UUID) -> Recommendation:
        row = await self._store.get_recommendation(organization_id, recommendation_id)
        if row is None:
            raise LearningNotFound(str(recommendation_id))
        return row


def _observation_from(record, *, outcome: str) -> MemoryObservation:
    return MemoryObservation(
        organization_id=record.organization_id,
        memory_type=record.memory_type if record.memory_type != MemoryType.CONVERSATION else MemoryType.LEARNING,
        title=record.title,
        description=record.description or record.title,
        features=PatternFeatures(
            intent_family=record.intent_family,
            source_type=record.source_type,
            retrieval_modality=record.retrieval_modality,
            tool_family=record.tool_family,
            failure_category=record.failure_category or "none",
        ),
        source_component="learning.engine",
        phase="reevaluate",
        outcome=outcome,
        confidence=record.confidence,
        idempotency_key=f"reevaluate:{record.id}:{outcome}",
    )


def periodic_cutoff(hours: int = 24) -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=max(1, hours))
