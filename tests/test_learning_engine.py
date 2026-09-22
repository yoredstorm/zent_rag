"""Learning engine: clusters, findings, safe experiments, human promotion."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from src.core.domain.learning_cycle import (
    ExperimentMode,
    Hypothesis,
    MetricSample,
    RecommendationAction,
    RecommendationStatus,
    RunSignal,
    ToolStep,
    WindowName,
)
from src.core.domain.memory import MemoryStatus, MemoryType
from src.learning_engine import AUTONOMOUS_PRODUCTION_MUTATION
from src.learning_engine.conflicts import ClaimView, detect_conflicts, resolve_conflict
from src.learning_engine.engine import LearningEngine, PromotionDenied
from src.learning_engine.evaluation import compare_arms, lab_summary
from src.learning_engine.health import knowledge_health
from src.learning_engine.outcome import OutcomeEvaluator
from src.learning_engine.safety import ExperimentSafetyError, assert_experiment_safe
from src.learning_engine.specialists import explain_finding
from src.learning_engine.store import InMemoryLearningStore
from src.memory.policy import MemoryMaturityPolicy
from src.memory.recall import MemoryRecallService, RecallQuery
from src.memory.repository import InMemoryMemoryRepository
from src.memory.service import MemoryFoundationService
from src.memory.signature import PatternFeatures


def _stack(min_sample: int = 20, config=None):
    repo = InMemoryMemoryRepository()
    memory = MemoryFoundationService(repo, MemoryMaturityPolicy())
    store = InMemoryLearningStore()
    engine = LearningEngine(store, memory, config_port=config, min_sample=min_sample)
    return repo, memory, store, engine


def _signal(org, **overrides) -> RunSignal:
    payload = dict(
        organization_id=org,
        pattern_key="tabular_field_lookup",
        intent_family="tabular_field_lookup",
        source_type="tabular",
        source_name="ATPCO_Record2.xlsx",
        retrieval_strategy="vector",
        success=False,
        failure_code="retrieval.wrong_strategy",
        quality=0.40,
        grounding=0.90,
        cost=0.001,
        latency_ms=400,
    )
    payload.update(overrides)
    return RunSignal(**payload)


def _copies(org, count: int, **overrides) -> list[RunSignal]:
    return [_signal(org, **overrides) for _ in range(count)]


def _arm(count: int, **fields) -> list[MetricSample]:
    return [MetricSample(**fields) for _ in range(count)]


class _Config:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.state = {"retrieval": "vector"}

    async def snapshot(self, organization_id):
        self.calls.append("snapshot")
        return dict(self.state)

    async def apply(self, organization_id, *, candidate: str, baseline: str):
        self.calls.append("apply")
        self.state = {"retrieval": candidate, "baseline": baseline}
        return dict(self.state)

    async def rollback(self, organization_id, snapshot):
        self.calls.append("rollback")
        self.state = dict(snapshot)


@pytest.mark.asyncio
async def test_failure_clustering_one_memory():
    org = uuid4()
    _, memory, _, engine = _stack()
    failures = _copies(org, 184, failure_code="retrieval.wrong_strategy", success=False)
    others = _copies(
        org,
        5,
        retrieval_strategy="structured_exact",
        success=True,
        failure_code="",
        quality=0.91,
    )
    await engine.ingest(failures + others, analyze=True, window=WindowName.ALL_TIME)
    rows = await memory.list_memories(org, memory_type=MemoryType.LEARNING.value, limit=20)
    assert len(rows) == 1
    record = rows[0]
    assert record.support_count == 184
    assert record.metadata["occurrences"] == 184
    assert record.metadata["known_alternative"] == "structured_exact"
    assert "ATPCO_Record2.xlsx" in record.metadata["affected_sources"]
    assert record.metadata["observed_outcome"] == "low retrieval precision"


@pytest.mark.asyncio
async def test_success_clustering_scorecard():
    org = uuid4()
    _, memory, _, engine = _stack()
    good = _copies(
        org,
        484,
        pattern_key="sku_exact_lookup",
        intent_family="sku_exact_lookup",
        source_type="database",
        retrieval_strategy="structured_exact",
        success=True,
        failure_code="",
        latency_ms=312,
        cost=0.0004,
    )
    bad = _copies(
        org,
        8,
        pattern_key="sku_exact_lookup",
        intent_family="sku_exact_lookup",
        source_type="database",
        retrieval_strategy="structured_exact",
        success=False,
        failure_code="retrieval.low_relevance",
        latency_ms=312,
        cost=0.0004,
    )
    await engine.ingest(good + bad, analyze=True, window=WindowName.ALL_TIME)
    rows = await memory.list_memories(org, memory_type=MemoryType.OPERATIONAL.value, limit=10)
    assert len(rows) == 1
    record = rows[0]
    assert record.support_count == 492
    assert record.success_count == 484
    assert record.metadata["success_rate"] == pytest.approx(0.9837, abs=1e-4)
    assert record.metadata["average_latency_ms"] == pytest.approx(312, abs=0.1)
    assert record.metadata["average_cost"] == pytest.approx(0.0004, abs=1e-6)
    assert record.metadata["strategy"] == "structured_exact"


@pytest.mark.asyncio
async def test_sample_size_protection():
    org = uuid4()
    _, _, _, engine = _stack(min_sample=20)
    report = await engine.ingest(_copies(org, 8), analyze=True)
    assert report is not None
    assert report.findings == []


@pytest.mark.asyncio
async def test_finding_creation_and_dedup():
    org = uuid4()
    _, _, store, engine = _stack()
    vector = _copies(org, 24, retrieval_strategy="vector", success=False, failure_code="retrieval.wrong_strategy")
    vector += _copies(org, 40, retrieval_strategy="vector", success=True, failure_code="")
    structured = _copies(
        org,
        40,
        retrieval_strategy="structured_exact",
        success=True,
        failure_code="",
        quality=0.91,
    )
    first = await engine.ingest(vector + structured, analyze=True)
    assert first is not None
    finding = next(item for item in first.findings if item.category == "retrieval" and item.candidate_strategy)
    assert finding.organization_id == org
    assert finding.pattern_key == "tabular_field_lookup"
    assert finding.severity.value == "medium"
    assert finding.sample_size >= 20
    assert finding.window == "24h"
    assert finding.confidence == "high"
    assert finding.first_seen is not None
    assert finding.last_seen is not None
    assert finding.evidence
    assert "ATPCO_Record2.xlsx" in finding.affected
    assert finding.impact["baseline_success_rate"] < finding.impact["candidate_success_rate"]
    second = await engine.analyze(org)
    assert len(await store.list_findings(org)) == 1
    again = (await store.list_findings(org))[0]
    assert again.id == finding.id
    assert len(second.findings) == 1


@pytest.mark.asyncio
async def test_hypothesis_is_measurable():
    org = uuid4()
    _, _, _, engine = _stack()
    report = await engine.ingest(_gap_signals(org), analyze=True)
    assert report is not None
    hypothesis = report.hypotheses[0]
    assert hypothesis.baseline != hypothesis.candidate
    assert hypothesis.expected_metric == "task_success"
    assert hypothesis.minimum_improvement > 0
    assert hypothesis.scope == "tabular_field_lookup"
    assert hypothesis.falsifiable is True
    assert "grounding_min_delta" in hypothesis.guardrails
    with pytest.raises(ValueError):
        Hypothesis(
            organization_id=org,
            finding_id=uuid4(),
            statement="maybe better",
            baseline="vector",
            candidate="vector",
            expected_metric="task_success",
            minimum_improvement=0.05,
            scope="tabular_field_lookup",
        )


@pytest.mark.asyncio
async def test_experiment_request_is_offline():
    org = uuid4()
    _, _, _, engine = _stack()
    report = await engine.ingest(_gap_signals(org), analyze=True)
    assert report is not None
    experiment = report.experiments[0]
    assert experiment.mode == ExperimentMode.GOLDEN_SET
    assert experiment.to_public_dict()["mutates_production"] is False
    assert experiment.status.value == "queued"


@pytest.mark.asyncio
async def test_baseline_candidate_comparison_and_recommendation():
    org = uuid4()
    repo, memory, store, engine = _stack()
    report = await engine.ingest(_gap_signals(org), analyze=True)
    assert report is not None
    experiment = report.experiments[0]
    recommendation = await engine.complete_experiment(
        org,
        experiment.id,
        baseline=_arm(83, task_success=0.62, grounding=0.90, latency_ms=380, cost=0.0045, quality=0.62),
        candidate=_arm(83, task_success=0.77, grounding=0.91, latency_ms=312, cost=0.0040, quality=0.77),
    )
    assert recommendation.suggested_action == RecommendationAction.PROMOTE
    assert recommendation.status == RecommendationStatus.PENDING
    assert recommendation.sample_size == 83
    assert recommendation.deltas["task_success"] == pytest.approx((0.77 - 0.62) / 0.62, abs=1e-6)
    assert recommendation.deltas["latency_ms"] < 0
    assert recommendation.deltas["cost"] < 0
    assert "chain of thought" not in recommendation.explanation.lower()
    assert "Calidad" in recommendation.explanation
    assert store.promotions == {}
    record = await memory.get(org, recommendation.memory_id)
    assert record.status == MemoryStatus.VALIDATED
    assert record.status != MemoryStatus.ACTIVE
    assert AUTONOMOUS_PRODUCTION_MUTATION is False
    assert repo.records[record.id].status == MemoryStatus.VALIDATED


@pytest.mark.asyncio
async def test_no_automatic_promotion_and_manual_audit():
    org = uuid4()
    config = _Config()
    _, memory, store, engine = _stack(config=config)
    report = await engine.ingest(_gap_signals(org), analyze=True)
    recommendation = await engine.complete_experiment(
        org,
        report.experiments[0].id,
        baseline=_arm(83, task_success=0.62, grounding=0.90, latency_ms=380, cost=0.0045),
        candidate=_arm(83, task_success=0.77, grounding=0.91, latency_ms=312, cost=0.0040),
    )
    assert config.calls == []
    assert config.state == {"retrieval": "vector"}
    actor = uuid4()
    with pytest.raises(PromotionDenied):
        await engine.promote(org, recommendation.id, actor_id=None, is_admin=False)
    with pytest.raises(PromotionDenied):
        await engine.promote(org, recommendation.id, actor_id=actor, is_admin=False)
    record = await memory.get(org, recommendation.memory_id)
    assert record.status == MemoryStatus.VALIDATED
    audit = await engine.promote(org, recommendation.id, actor_id=actor, is_admin=True)
    assert audit.actor_id == actor
    assert audit.experiment_id == recommendation.experiment_id
    assert audit.baseline == recommendation.baseline
    assert audit.candidate == recommendation.candidate
    assert audit.metrics["relative"]["task_success"] > 0
    assert audit.config_mutated is True
    assert config.calls == ["snapshot", "apply"]
    assert (await memory.get(org, recommendation.memory_id)).status == MemoryStatus.ACTIVE
    assert len(await store.list_promotions(org)) == 1
    await engine.rollback(org, audit.id, actor_id=actor, is_admin=True)
    assert config.calls[-1] == "rollback"
    assert config.state["retrieval"] == "vector"
    assert (await memory.get(org, recommendation.memory_id)).status == MemoryStatus.VALIDATED


@pytest.mark.asyncio
async def test_rejected_candidate_keeps_history():
    org = uuid4()
    repo, memory, _, engine = _stack()
    report = await engine.ingest(_gap_signals(org), analyze=True)
    recommendation = await engine.complete_experiment(
        org,
        report.experiments[0].id,
        baseline=_arm(30, task_success=0.90, grounding=0.95),
        candidate=_arm(30, task_success=0.40, grounding=0.95),
    )
    assert recommendation.suggested_action == RecommendationAction.REJECT
    record = await memory.get(org, recommendation.memory_id)
    assert record.status == MemoryStatus.REJECTED
    events = await repo.list_events(org, record.id, limit=20, offset=0)
    assert events
    assert await memory.get(org, record.id) is not None


@pytest.mark.asyncio
async def test_stale_and_contradicted_memory():
    org = uuid4()
    repo, memory, _, engine = _stack(min_sample=5)
    now = datetime.now(timezone.utc)
    old = _copies(
        org,
        10,
        pattern_key="sku_exact_lookup",
        intent_family="sku_exact_lookup",
        source_type="database",
        retrieval_strategy="structured_exact",
        success=True,
        failure_code="",
    )
    for signal in old:
        signal.occurred_at = now - timedelta(days=3)
    await engine.ingest(old, analyze=True, window=WindowName.LAST_7D)
    operational = await memory.list_memories(org, memory_type=MemoryType.OPERATIONAL.value, limit=5)
    record = operational[0]
    await memory.validate(org, record.id, via="experiment")
    await memory.activate(org, record.id, actor_id=uuid4())
    record.last_observed_at = now - timedelta(days=120)
    await repo.save(record)
    changed = await engine.reevaluate(org, window=WindowName.LAST_24H, now=now)
    assert f"stale:{record.id}" in changed
    assert (await memory.get(org, record.id)).status == MemoryStatus.STALE

    fresh = _copies(
        org,
        8,
        pattern_key="definitions_lookup",
        intent_family="definitions_lookup",
        source_type="knowledge",
        retrieval_strategy="hybrid",
        success=True,
        failure_code="",
    )
    for signal in fresh:
        signal.occurred_at = now - timedelta(days=3)
    await engine.ingest(fresh, analyze=True, window=WindowName.LAST_7D)
    second = (await memory.list_memories(org, memory_type=MemoryType.OPERATIONAL.value, limit=10))
    active = next(item for item in second if item.pattern_key == "definitions_lookup")
    await memory.validate(org, active.id, via="experiment")
    await memory.activate(org, active.id, actor_id=uuid4())
    bad = _copies(
        org,
        6,
        pattern_key="definitions_lookup",
        intent_family="definitions_lookup",
        source_type="knowledge",
        retrieval_strategy="hybrid",
        success=False,
        failure_code="",
    )
    await engine.ingest(bad, analyze=False)
    changed = await engine.reevaluate(org, window=WindowName.LAST_24H, now=now)
    assert f"contradicted:{active.id}" in changed
    assert (await memory.get(org, active.id)).status == MemoryStatus.CONTRADICTED


@pytest.mark.asyncio
async def test_agent_repeated_tool_detection():
    org = uuid4()
    _, _, _, engine = _stack()
    rows = _copies(
        org,
        20,
        pattern_key="sql_retry",
        intent_family="sql_retry",
        source_type="database",
        retrieval_strategy="",
        success=False,
        failure_code="",
        tool_sequence=("query_database", "query_database"),
        tool_errors=("schema error", "schema mismatch"),
    )
    report = await engine.ingest(rows, analyze=True)
    assert report is not None
    finding = report.findings[0]
    assert finding.category == "agent"
    assert finding.candidate_strategy == "inspect_schema_then_retry_once"
    assert report.experiments[0].mode == ExperimentMode.REPLAY
    assert all(step.execution == "dry_run" for step in report.experiments[0].tool_plan)


@pytest.mark.asyncio
async def test_retrieval_strategy_learning_does_not_override_policy():
    org = uuid4()
    repo, memory, _, engine = _stack()
    await engine.ingest(_gap_signals(org), analyze=True)
    report = await engine.analyze(org)
    comparison = next(item for item in report.comparisons if item.kind == "retrieval")
    assert {row["strategy"] for row in comparison.rows} >= {"vector", "structured_exact"}
    assert comparison.production_policy_controls_execution is True
    operational = await memory.list_memories(org, memory_type=MemoryType.OPERATIONAL.value, limit=10)
    winner = next(item for item in operational if item.retrieval_modality == "structured_exact")
    await memory.validate(org, winner.id, via="experiment")
    refreshed = await engine.analyze(org)
    marked = next(item for item in refreshed.comparisons if item.pattern_key == "tabular_field_lookup")
    assert marked.judgment_signal is True
    assert marked.validated_memory_id == winner.id
    recall = MemoryRecallService(repo, MemoryMaturityPolicy())
    visible = await recall.recall(
        RecallQuery(
            organization_id=org,
            features=PatternFeatures(
                intent_family="tabular_field_lookup",
                source_type="tabular",
                retrieval_modality="structured_exact",
                tool_family="none",
                failure_category="none",
            ),
        )
    )
    assert visible == []


@pytest.mark.asyncio
async def test_knowledge_conflict_detection_needs_human():
    org = uuid4()
    older = ClaimView(
        organization_id=org,
        subject="fare",
        predicate="amount",
        object_value="10",
        source="rules-2020",
        freshness=datetime(2020, 1, 1, tzinfo=timezone.utc),
        version=1,
    )
    newer = ClaimView(
        organization_id=org,
        subject="fare",
        predicate="amount",
        object_value="12",
        source="rules-2024",
        freshness=datetime(2024, 1, 1, tzinfo=timezone.utc),
        version=4,
        authority="tariff",
    )
    found = detect_conflicts([older, newer])
    assert len(found) == 1
    assert found[0].suggestion == "human_review"
    assert found[0].chosen_claim_id is None
    assert found[0].to_public_dict()["auto_resolved"] is False
    resolved = resolve_conflict(
        found[0], actor_id=uuid4(), chosen_claim_id=older.claim_id, reason="authority is tariff but effective date still open"
    )
    assert resolved.status == "resolved"
    assert resolved.chosen_claim_id == older.claim_id


@pytest.mark.asyncio
async def test_cost_optimization_finding_protects_grounding():
    org = uuid4()
    _, _, _, engine = _stack()
    costly = _copies(
        org,
        20,
        pattern_key="answer_route",
        intent_family="answer_route",
        retrieval_strategy="",
        route_label="large_model",
        success=True,
        failure_code="",
        quality=0.90,
        grounding=0.97,
        cost=0.020,
    )
    cheap = _copies(
        org,
        20,
        pattern_key="answer_route",
        intent_family="answer_route",
        retrieval_strategy="",
        route_label="deterministic",
        success=True,
        failure_code="",
        quality=0.90,
        grounding=0.97,
        cost=0.004,
    )
    report = await engine.ingest(costly + cheap, analyze=True)
    assert report is not None
    finding = next(item for item in report.findings if item.category == "cost")
    assert finding.baseline_strategy == "large_model"
    assert finding.candidate_strategy == "deterministic"
    assert finding.impact["current_cost"] > finding.impact["candidate_cost"]
    assert finding.impact["monthly_potential_saving"] > 0
    assert finding.impact["grounding_protected"] is True
    weak = _copies(
        org,
        20,
        pattern_key="unsafe_cut",
        intent_family="unsafe_cut",
        retrieval_strategy="",
        route_label="large_model",
        success=True,
        failure_code="",
        quality=0.90,
        grounding=0.97,
        cost=0.020,
    )
    weaker = _copies(
        org,
        20,
        pattern_key="unsafe_cut",
        intent_family="unsafe_cut",
        retrieval_strategy="",
        route_label="cheap_model",
        success=True,
        failure_code="",
        quality=0.90,
        grounding=0.40,
        cost=0.001,
    )
    guarded = await engine.ingest(weak + weaker, analyze=True)
    assert guarded is not None
    assert all(item.pattern_key != "unsafe_cut" or item.category != "cost" for item in guarded.findings)


@pytest.mark.asyncio
async def test_tenant_isolation():
    left = uuid4()
    right = uuid4()
    _, _, store, engine = _stack()
    await engine.ingest(_gap_signals(left), analyze=True)
    await engine.ingest(_gap_signals(right), analyze=True)
    left_ids = {item.id for item in await store.list_findings(left)}
    right_ids = {item.id for item in await store.list_findings(right)}
    assert left_ids.isdisjoint(right_ids)
    foreign = next(iter(right_ids))
    assert await store.get_finding(left, foreign) is None


def test_shadow_tools_cannot_cause_side_effects():
    called = {"n": 0}

    def send_email():
        called["n"] += 1

    def charge_payment():
        called["n"] += 1

    def mutate_database():
        called["n"] += 1

    for name in ("send_email", "charge_payment", "mutate_database", "workflow_destructive"):
        with pytest.raises(ExperimentSafetyError):
            assert_experiment_safe(
                ExperimentMode.SHADOW,
                (ToolStep(name=name, execution="live", side_effect=True),),
            )
    assert_experiment_safe(
        ExperimentMode.REPLAY,
        (
            ToolStep(name="send_email", execution="mock", side_effect=True),
            ToolStep(name="mutate_database", execution="dry_run", side_effect=True),
            ToolStep(name="workflow_destructive", execution="simulation", side_effect=True),
        ),
    )
    sentinels = (send_email, charge_payment, mutate_database)
    assert all(callable(item) for item in sentinels)
    assert called["n"] == 0


def test_outcome_is_multidimensional_and_ignores_http_status():
    org = uuid4()
    evaluator = OutcomeEvaluator()
    ok = _signal(
        org,
        metadata={"http_status": 200},
        success=None,
        failure_code="",
        answer_grounded=True,
        grounding=None,
        quality=0.8,
    )
    failed = _signal(
        org,
        metadata={"http_status": 500},
        success=None,
        failure_code="",
        answer_grounded=True,
        grounding=None,
        quality=0.8,
    )
    left = evaluator.evaluate(ok)
    right = evaluator.evaluate(failed)
    assert left.as_dict()["quality"] == 0.8
    assert left.grounding == 1.0
    assert left.task_success is not None
    assert "score" not in left.as_dict()
    assert left.as_dict() == right.as_dict()


def test_lab_summary_reuses_experiment_lab():
    report = {
        "results": [
            {
                "rules": {
                    "match": True,
                    "confidence": 0.4,
                    "latency_ms": 10,
                    "tokens": 3,
                    "cost": 0.01,
                    "fallback": False,
                },
                "jev": {
                    "match": False,
                    "confidence": 0.9,
                    "latency_ms": 20,
                    "tokens": 8,
                    "cost": 0.02,
                    "fallback": True,
                },
            }
        ]
    }
    summary = lab_summary(report)
    assert summary["rules"]["routing_accuracy"] == 1.0
    assert summary["jev"]["routing_accuracy"] == 0.0
    evaluation = compare_arms(uuid4(), uuid4(), _arm(2, task_success=0.5), _arm(2, task_success=0.5))
    assert evaluation.reproducible["sample_size"] == 2


def test_specialist_does_not_invent_metrics():
    org = uuid4()
    from src.core.domain.learning_cycle import Finding, FindingSeverity

    finding = Finding(
        organization_id=org,
        category="retrieval",
        severity=FindingSeverity.MEDIUM,
        pattern_key="tabular_field_lookup",
        observed="vector success 62%",
        alternative="structured_exact historically 91%",
        baseline_strategy="vector",
        candidate_strategy="structured_exact",
        sample_size=184,
        window="30d",
        confidence="high",
        dedupe_key="retrieval:tabular_field_lookup:vector:structured_exact",
        evidence=["baseline_success=0.6200"],
    )
    note = explain_finding(finding)
    assert note["specialist"] == "retrieval_analyst"
    assert note["invented_metrics"] is False
    assert "62%" in note["interpretation"]
    assert "91%" in note["interpretation"]


def test_knowledge_health_keeps_components():
    health = knowledge_health(
        {
            "retrievability": 94,
            "freshness": 71,
            "conflict_rate": 83,
            "grounding_success": 97,
        },
        notes={"freshness": "Rules2024 stale"},
    )
    assert health.components["retrievability"] == 94
    assert health.components["freshness"] == 71
    assert "Rules2024 stale" in health.warnings
    assert health.aggregate == pytest.approx((94 + 71 + 83 + 97) / 4)


def _gap_signals(org):
    vector_fail = _copies(org, 24, retrieval_strategy="vector", success=False, failure_code="retrieval.wrong_strategy")
    vector_ok = _copies(org, 40, retrieval_strategy="vector", success=True, failure_code="")
    structured = _copies(
        org,
        40,
        retrieval_strategy="structured_exact",
        success=True,
        failure_code="",
        quality=0.91,
    )
    return vector_fail + vector_ok + structured
