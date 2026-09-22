"""Memory foundation: lifecycle, tenant isolation, recall, traces."""
from __future__ import annotations

import asyncio
import inspect
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from src.core.domain.decision import DecisionContext, RoutingDecision
from src.core.domain.memory import (
    EvidenceRef,
    MemoryEvidenceKind,
    MemoryStatus,
    MemoryType,
    MemoryVisibility,
    ValidationPath,
)
from src.decision.engine import _trace_from
from src.decision.settings import DecisionEngineSettings
from src.memory.content import MemoryContentError
from src.memory.policy import MemoryMaturityPolicy, MemoryPolicyError
from src.memory.recall import MemoryRecallService, RecallQuery
from src.memory.repository import InMemoryMemoryRepository
from src.memory.service import MemoryFoundationService, MemoryNotFound, MemoryObservation
from src.memory.signature import PatternFeatures, infer_pattern_features, pattern_key, pattern_signature
from src.memory.taxonomy import FailureCode, SuccessSignal


def _features(**overrides) -> PatternFeatures:
    base = dict(
        intent_family="structured_field_lookup",
        source_type="tabular",
        retrieval_modality="structured_exact",
        tool_family="none",
        failure_category="none",
    )
    base.update(overrides)
    return PatternFeatures(**base)


def _obs(org, **overrides) -> MemoryObservation:
    payload = dict(
        organization_id=org,
        memory_type=MemoryType.OPERATIONAL,
        title="structured field lookup",
        description="Excel field positions prefer structured_exact",
        features=_features(),
        source_component="rag.adaptive",
        phase="retrieval",
        outcome="success",
        confidence=0.91,
        success=True,
        conversation_id=uuid4(),
        run_id=uuid4(),
        request_id=uuid4(),
    )
    payload.update(overrides)
    return MemoryObservation(**payload)


def _stack():
    repo = InMemoryMemoryRepository()
    policy = MemoryMaturityPolicy()
    return repo, MemoryFoundationService(repo, policy), MemoryRecallService(repo, policy)


async def _promote(service, org, record):
    await service.validate(org, record.id, via=ValidationPath.ADMIN, actor_id=uuid4())
    return await service.activate(org, record.id, actor_id=uuid4())


@pytest.mark.asyncio
async def test_memory_creation_starts_observed():
    org = uuid4()
    _, service, _ = _stack()
    record = await service.observe(_obs(org))
    assert record.status == MemoryStatus.OBSERVED
    assert record.support_count == 1
    assert record.visibility == MemoryVisibility.TENANT
    events = await service.timeline(org, record.id)
    kinds = [event.event_type.value for event in events]
    assert kinds == ["memory.created", "memory.observed"]


@pytest.mark.asyncio
async def test_reinforcement_and_pattern_never_auto_activate():
    org = uuid4()
    _, service, _ = _stack()
    first = await service.observe(_obs(org, idempotency_key="once"))
    second = await service.observe(
        _obs(org, idempotency_key="twice", conversation_id=first.created_from_conversation_id)
    )
    assert second.id == first.id
    assert second.status == MemoryStatus.REINFORCED
    assert second.support_count == 2
    current = second
    for index in range(3):
        current = await service.observe(_obs(org, idempotency_key=f"more-{index}"))
    assert current.support_count == 5
    assert current.status == MemoryStatus.PATTERN
    assert current.status != MemoryStatus.ACTIVE
    assert current.status != MemoryStatus.VALIDATED


@pytest.mark.asyncio
async def test_contradiction_removes_active_memory_from_recall():
    org = uuid4()
    repo, service, recall = _stack()
    created = await service.observe(_obs(org))
    active = await _promote(service, org, created)
    assert active.status == MemoryStatus.ACTIVE
    contradicted = await service.contradict(_obs(org, outcome="conflict", success=False))
    assert contradicted.status == MemoryStatus.CONTRADICTED
    found = await recall.recall(RecallQuery(organization_id=org, features=_features()))
    assert found == []
    assert repo.records[created.id].organization_id == org


@pytest.mark.asyncio
async def test_lifecycle_admin_gates_and_restore():
    org = uuid4()
    _, service, recall = _stack()
    record = await service.observe(_obs(org))
    with pytest.raises(MemoryPolicyError):
        await service.activate(org, record.id)
    validated = await service.validate(org, record.id, via=ValidationPath.ADMIN)
    assert validated.status == MemoryStatus.VALIDATED
    hidden = await recall.recall(RecallQuery(organization_id=org, features=_features()))
    assert hidden == []
    active = await service.activate(org, record.id, actor_id=uuid4())
    assert active.status == MemoryStatus.ACTIVE
    assert active.activated_at is not None
    rejected = await service.reject(org, record.id, actor_id=uuid4())
    restored = await service.restore(org, rejected.id, actor_id=uuid4())
    assert restored.status == MemoryStatus.OBSERVED
    expired = await service.expire(org, record.id, actor_id=uuid4())
    assert expired.status == MemoryStatus.EXPIRED


def test_pattern_signature_ignores_prompt_text():
    features = infer_pattern_features(
        "En que posicion esta el Carrier Code en la tabla Excel de embarques " * 4
    )
    signature = pattern_signature(features)
    assert "carrier" not in signature
    assert pattern_key(features) == "structured_field_lookup"
    noisy = PatternFeatures(
        intent_family="please look at this very long user prompt about nothing",
        source_type="tabular",
        retrieval_modality="structured_exact",
        tool_family="none",
        failure_category="none",
    )
    assert pattern_signature(noisy).startswith("unclassified|")
    schema = _features(tool_family="query_database", failure_category="sql.schema_mismatch")
    assert pattern_key(schema) == "agent_tool_retry_schema_error"


@pytest.mark.asyncio
async def test_maturity_policy_thresholds_never_reach_active():
    policy = MemoryMaturityPolicy.from_env(
        {"MEMORY_PATTERN_MIN_SUPPORT": "4", "MEMORY_PATTERN_MIN_CONFIDENCE": "0.5"}
    )
    assert policy.pattern_min_support == 4
    org = uuid4()
    _, service, _ = _stack()
    stored = await service.observe(_obs(org, confidence=1.0))
    stored.support_count = 100
    stored.confidence = 1.0
    stored.status = policy.status_after_support(stored, has_knowledge_evidence=True)
    assert stored.status == MemoryStatus.PATTERN


@pytest.mark.asyncio
async def test_tenant_isolation_and_recall_filters():
    org_a, org_b = uuid4(), uuid4()
    repo, service, recall = _stack()
    record_a = await _promote(service, org_a, await service.observe(_obs(org_a)))
    await _promote(service, org_b, await service.observe(_obs(org_b)))
    own = await recall.recall(RecallQuery(organization_id=org_a, features=_features()))
    other = await recall.recall(RecallQuery(organization_id=org_b, features=_features()))
    assert [item.id for item in own] == [record_a.id]
    assert all(item.organization_id == org_b for item in other)
    assert all(item.id != record_a.id for item in other)
    with pytest.raises(MemoryNotFound):
        await service.get(org_b, record_a.id)

    inactive = await service.observe(
        _obs(org_a, features=_features(intent_family="database_aggregation", source_type="database"))
    )
    missed = await recall.recall(
        RecallQuery(
            organization_id=org_a,
            features=_features(intent_family="database_aggregation", source_type="database"),
        )
    )
    assert inactive.id not in {item.id for item in missed}

    stale = await _promote(
        service,
        org_a,
        await service.observe(
            _obs(
                org_a,
                features=_features(intent_family="exact_identifier_query", source_type="database"),
            )
        ),
    )
    stale.last_observed_at = datetime.now(timezone.utc) - timedelta(days=120)
    await repo.save(stale)
    stale_hits = await recall.recall(
        RecallQuery(
            organization_id=org_a,
            features=_features(intent_family="exact_identifier_query", source_type="database"),
        )
    )
    assert stale_hits == []
    stale.status = MemoryStatus.STALE
    stale.last_observed_at = datetime.now(timezone.utc)
    await repo.save(stale)
    assert (
        await recall.recall(
            RecallQuery(
                organization_id=org_a,
                features=_features(intent_family="exact_identifier_query", source_type="database"),
            )
        )
        == []
    )


@pytest.mark.asyncio
async def test_events_evidence_impact_and_idempotency():
    org = uuid4()
    run_id = uuid4()
    conversation_id = uuid4()
    _, service, _ = _stack()
    claim_id = uuid4()
    record = await service.observe(
        _obs(
            org,
            run_id=run_id,
            conversation_id=conversation_id,
            idempotency_key="same-event",
            evidence=[
                EvidenceRef(kind=MemoryEvidenceKind.RUN, ref_id=run_id, ref_label="run"),
                EvidenceRef(kind=MemoryEvidenceKind.CLAIM, ref_id=claim_id, ref_label="claim"),
                EvidenceRef(kind=MemoryEvidenceKind.EXPERIMENT, ref_id=uuid4(), ref_label="experiment"),
            ],
        )
    )
    again = await service.observe(_obs(org, idempotency_key="same-event", run_id=run_id))
    assert again.support_count == 1
    page = await service.evidence(org, record.id, limit=1, offset=1)
    assert len(page) == 1
    assert page[0].ref_id is not None
    await service.record_use(
        organization_id=org,
        memory_id=record.id,
        source_component="decision.engine",
        phase="pre_retrieval",
        outcome="knowledge.answer",
        run_id=run_id,
        conversation_id=conversation_id,
        request_id=uuid4(),
        metadata={"route": "structured_lookup", "confidence": 0.94},
    )
    await service.contradict(
        _obs(
            org,
            run_id=run_id,
            conversation_id=conversation_id,
            outcome="conflict",
            success=False,
            idempotency_key="contra-1",
        )
    )
    impact = await service.run_impact(org, run_id=run_id)
    assert impact["created"][0]["memory_id"] == str(record.id)
    assert impact["used"][0]["pattern_key"] == "structured_field_lookup"
    assert impact["contradicted"][0]["memory_id"] == str(record.id)
    assert impact["organization_id"] == str(org)
    blob = json.dumps(impact)
    assert "I first thought" not in blob
    assert "chain_of_thought" not in blob


@pytest.mark.asyncio
async def test_chain_of_thought_is_not_persisted():
    org = uuid4()
    repo, service, _ = _stack()
    with pytest.raises(MemoryContentError):
        await service.observe(
            _obs(org, metadata={"chain_of_thought": "I first thought vector search"})
        )
    with pytest.raises(MemoryContentError):
        await service.observe(
            _obs(org, description="I first thought vector search but then reasoned")
        )
    assert repo.events == []
    assert repo.records == {}


@pytest.mark.asyncio
async def test_failure_taxonomy_skips_isolated_errors():
    org = uuid4()
    repo, service, _ = _stack()
    skipped = await service.record_failure(
        _obs(org, memory_type=MemoryType.LEARNING, success=False),
        FailureCode.TOOL_TIMEOUT,
        occurrences=1,
    )
    assert skipped is None
    assert repo.records == {}
    created = await service.record_failure(
        _obs(
            org,
            memory_type=MemoryType.LEARNING,
            features=_features(
                tool_family="query_database", intent_family="database_aggregation"
            ),
            success=False,
        ),
        FailureCode.SQL_SCHEMA_MISMATCH,
        occurrences=1,
    )
    assert created is not None
    assert created.pattern_key == "agent_tool_retry_schema_error"
    assert created.status == MemoryStatus.OBSERVED


@pytest.mark.asyncio
async def test_success_signal_and_knowledge_requires_ledger_ref():
    org = uuid4()
    _, service, _ = _stack()
    success = await service.record_success(
        _obs(
            org,
            features=_features(intent_family="knowledge_definition", source_type="knowledge"),
        ),
        SuccessSignal.GROUNDED_ANSWER,
    )
    assert success.success_signal == SuccessSignal.GROUNDED_ANSWER.value
    assert success.success_count == 1
    knowledge = await service.observe(
        _obs(
            org,
            memory_type=MemoryType.KNOWLEDGE,
            title="Carrier Code column",
            features=_features(
                intent_family="knowledge_definition",
                source_type="knowledge",
                retrieval_modality="hybrid",
            ),
            evidence=[
                EvidenceRef(kind=MemoryEvidenceKind.CLAIM, ref_id=uuid4(), ref_label="claim")
            ],
        )
    )
    validated = await service.validate(org, knowledge.id, via=ValidationPath.ADMIN)
    assert validated.status == MemoryStatus.VALIDATED
    bare = await service.observe(
        _obs(
            org,
            memory_type=MemoryType.KNOWLEDGE,
            title="LLM only",
            features=_features(intent_family="exact_identifier_query"),
        )
    )
    with pytest.raises(MemoryPolicyError):
        await service.validate(org, bare.id, via=ValidationPath.ADMIN)


@pytest.mark.asyncio
async def test_concurrent_reinforcement_is_single_record():
    org = uuid4()
    repo, service, _ = _stack()

    async def one(index: int):
        return await service.observe(_obs(org, idempotency_key=f"c-{index}"))

    records = await asyncio.gather(*(one(index) for index in range(20)))
    assert len({record.id for record in records}) == 1
    assert len(repo.records) == 1
    assert records[0].support_count == 20


@pytest.mark.asyncio
async def test_decision_trace_references_memory_without_cot():
    org = uuid4()
    memory_id = uuid4()
    context = DecisionContext(
        user_request="posicion del campo",
        organization_id=org,
        operational_patterns=(
            {
                "memory_id": str(memory_id),
                "pattern_key": "structured_field_lookup",
                "memory_type": "operational",
                "success_rate": 0.97,
                "support_count": 184,
                "confidence": 0.94,
                "description": "I first thought vector search",
            },
        ),
    )
    state = context.sanitized_state()
    assert state["known_operational_patterns"][0]["memory_id"] == str(memory_id)
    assert "description" not in state["known_operational_patterns"][0]
    assert "I first thought" not in json.dumps(state)
    decision = RoutingDecision(capability="knowledge.answer", confidence=0.94, provider="legacy")
    trace = _trace_from(context, decision, DecisionEngineSettings())
    payload = json.loads(json.dumps(trace.to_dict(), default=str))
    assert payload["memory_ids"] == [str(memory_id)]
    assert "I first thought" not in json.dumps(payload)
    jev_source = inspect.getsource(__import__("src.decision.providers.jev", fromlist=["jev"]))
    assert "MemoryFoundation" not in jev_source
    assert "memory.activate" not in jev_source


@pytest.mark.asyncio
async def test_hook_supplies_patterns_and_records_use(monkeypatch):
    from src.decision.hook import OrchestratorDecisionHook

    seen: dict = {}

    async def fake_recall(**kwargs):
        seen["recall_org"] = kwargs["organization_id"]
        return [
            {
                "memory_id": str(uuid4()),
                "pattern_key": "structured_field_lookup",
                "memory_type": "operational",
                "success_rate": 0.97,
                "support_count": 184,
                "confidence": 0.94,
            }
        ]

    async def fake_record(**kwargs):
        seen["used"] = kwargs["patterns"]
        seen["capability"] = kwargs["capability"]

    monkeypatch.setattr("src.memory.integration.recall_for_decision", fake_recall)
    monkeypatch.setattr("src.memory.integration.record_memory_influence", fake_record)

    class _Engine:
        settings = DecisionEngineSettings()

        async def decide(self, context):
            seen["patterns"] = context.operational_patterns
            return RoutingDecision(
                capability="knowledge.answer",
                confidence=0.94,
                provider="legacy",
                resolved=True,
            )

    org = uuid4()
    hook = OrchestratorDecisionHook(_Engine())
    decision = await hook.evaluate(
        organization_id=org,
        request_id=uuid4(),
        user_id=None,
        query="posicion de columna",
        role="admin",
        sql_enabled=False,
        conversation_state={"conversation_id": str(uuid4()), "run_id": str(uuid4())},
    )
    assert decision.capability == "knowledge.answer"
    assert seen["recall_org"] == org
    assert seen["patterns"][0]["pattern_key"] == "structured_field_lookup"
    assert seen["used"][0]["memory_id"] == seen["patterns"][0]["memory_id"]
    assert seen["capability"] == "knowledge.answer"


def test_postgres_queries_stay_tenant_scoped():
    from src.infrastructure.postgres.memory_store import PostgresMemoryRepository

    source = inspect.getsource(PostgresMemoryRepository)
    for snippet in (
        "WHERE organization_id = :oid",
        "AND organization_id = :organization_id",
        "m.organization_id = e.organization_id",
        "m.organization_id = ev.organization_id",
        "visibility = 'tenant'",
    ):
        assert snippet in source
    lowered = source.lower()
    assert "select *" in lowered
    assert "where organization_id" in lowered
