"""Impacto de memoria de una respuesta, resuelto por query_id."""
from __future__ import annotations

import inspect
import json
from uuid import uuid4

import pytest
from fastapi import HTTPException

from src.core.domain.memory import MemoryEvent, MemoryEventType
from src.memory.repository import InMemoryMemoryRepository
from tests.test_memory_foundation import _features, _obs, _stack


def _forbidden(payload: dict) -> None:
    raw = json.dumps(payload)
    for key in ("pattern_signature", "pattern_key", "metadata", "request_id", "organization_id"):
        assert f'"{key}"' not in raw


@pytest.mark.asyncio
async def test_query_impact_buckets_this_request_only():
    org = uuid4()
    repo, service, _ = _stack()
    request_id = uuid4()
    query_id = uuid4()
    other_request = uuid4()
    created = await service.observe(_obs(org, request_id=request_id, idempotency_key="create"))
    await service.observe(
        _obs(
            org,
            request_id=other_request,
            idempotency_key="other",
            features=_features(intent_family="other_intent"),
        )
    )
    await service.record_use(
        organization_id=org,
        memory_id=created.id,
        source_component="decision.engine",
        phase="pre_retrieval",
        outcome="knowledge.answer",
        request_id=request_id,
        idempotency_key="used-1",
    )
    impact = await service.query_impact(org, query_id=query_id, request_id=request_id)
    assert impact["query_id"] == str(query_id)
    assert impact["truncated"] is False
    assert impact["counts"]["created"] == 1
    assert impact["counts"]["used"] == 1
    assert impact["counts"]["reinforced"] == 0
    assert impact["counts"]["contradicted"] == 0
    assert impact["counts"]["validated"] == 0
    used = impact["used"][0]
    assert used["memory_id"] == str(created.id)
    assert used["display_id"] == str(created.id).replace("-", "")[:8]
    assert used["phase"] == "pre_retrieval"
    assert used["needs_evidence"] is False
    assert used["support_count"] == 1
    assert used["success_rate"] is not None
    assert used["previous_support"] is None
    assert used["support_after"] is None
    created_item = impact["created"][0]
    assert created_item["needs_evidence"] is True
    assert created_item["status"] == "observed"
    assert created_item["support_count"] is None
    assert created_item["support_after"] == 1
    assert created_item["confidence_after"] is not None
    _forbidden(impact)
    other = await service.query_impact(org, query_id=uuid4(), request_id=other_request)
    assert other["counts"]["created"] == 1
    assert other["counts"]["used"] == 0
    assert repo.records[created.id].organization_id == org


@pytest.mark.asyncio
async def test_query_impact_other_tenant_is_empty():
    org = uuid4()
    _, service, _ = _stack()
    request_id = uuid4()
    await service.observe(_obs(org, request_id=request_id, idempotency_key="mine"))
    impact = await service.query_impact(uuid4(), query_id=uuid4(), request_id=request_id)
    assert impact["counts"] == {
        "used": 0,
        "created": 0,
        "reinforced": 0,
        "contradicted": 0,
        "validated": 0,
    }
    assert impact["used"] == []
    assert impact["created"] == []


@pytest.mark.asyncio
async def test_reinforcement_persists_before_and_after():
    org = uuid4()
    repo, service, _ = _stack()
    request_id = uuid4()
    first = await service.observe(_obs(org, request_id=request_id, idempotency_key="a"))
    confidence_before = round(float(first.confidence), 4)
    second = await service.observe(
        _obs(org, request_id=request_id, idempotency_key="b", confidence=0.4)
    )
    reinforced = [event for event in repo.events if event.event_type == MemoryEventType.REINFORCED]
    assert len(reinforced) == 1
    meta = reinforced[0].metadata
    assert meta["support_before"] == 1
    assert meta["support_after"] == second.support_count == 2
    assert meta["confidence_before"] == confidence_before
    assert meta["confidence_after"] == round(float(second.confidence), 4)
    impact = await service.query_impact(org, query_id=uuid4(), request_id=request_id)
    item = impact["reinforced"][0]
    assert item["previous_support"] == 1
    assert item["support_after"] == 2
    assert item["previous_confidence"] == meta["confidence_before"]
    assert item["confidence_after"] == meta["confidence_after"]
    assert item["support_count"] is None
    assert item["success_rate"] is None


@pytest.mark.asyncio
async def test_old_reinforced_event_without_snapshot_has_no_previous():
    org = uuid4()
    repo, service, _ = _stack()
    request_id = uuid4()
    created = await service.observe(_obs(org, request_id=uuid4(), idempotency_key="seed"))
    await repo.append_event(
        MemoryEvent(
            organization_id=org,
            memory_id=created.id,
            event_type=MemoryEventType.REINFORCED,
            source_component="learning",
            phase="retrieval",
            outcome="reinforced",
            request_id=request_id,
            metadata={"status": "reinforced", "support_delta": 1},
        )
    )
    impact = await service.query_impact(org, query_id=uuid4(), request_id=request_id)
    item = impact["reinforced"][0]
    assert item["status"] == "reinforced"
    assert item["previous_support"] is None
    assert item["previous_confidence"] is None
    assert item["support_after"] is None
    assert item["needs_evidence"] is False


@pytest.mark.asyncio
async def test_used_success_rate_is_null_without_support():
    org = uuid4()
    repo, service, _ = _stack()
    request_id = uuid4()
    created = await service.observe(_obs(org, request_id=uuid4(), idempotency_key="seed"))
    created.support_count = 0
    created.success_count = 0
    await repo.save(created)
    await service.record_use(
        organization_id=org,
        memory_id=created.id,
        source_component="decision.engine",
        phase="pre_retrieval",
        outcome="knowledge.answer",
        request_id=request_id,
    )
    impact = await service.query_impact(org, query_id=uuid4(), request_id=request_id)
    assert impact["used"][0]["support_count"] == 0
    assert impact["used"][0]["success_rate"] is None


@pytest.mark.asyncio
async def test_query_impact_truncates_after_100_events():
    org = uuid4()
    repo, service, _ = _stack()
    request_id = uuid4()
    created = await service.observe(_obs(org, request_id=uuid4(), idempotency_key="seed"))
    for index in range(101):
        await repo.append_event(
            MemoryEvent(
                organization_id=org,
                memory_id=created.id,
                event_type=MemoryEventType.USED,
                source_component="decision.engine",
                phase="pre_retrieval",
                outcome="knowledge.answer",
                request_id=request_id,
                idempotency_key=f"used-{index}",
            )
        )
    impact = await service.query_impact(org, query_id=uuid4(), request_id=request_id)
    assert impact["truncated"] is True
    assert impact["counts"]["used"] == 1


@pytest.mark.asyncio
async def test_query_impact_route_rejects_bad_uuid(monkeypatch):
    from src.api.routes import memory as routes

    class Ctx:
        organization_id = uuid4()

    monkeypatch.setattr(routes, "require_permission", lambda request, perm: Ctx())
    with pytest.raises(HTTPException) as exc:
        await routes.query_memory_impact("not-a-uuid", request=object())
    assert exc.value.status_code == 400
    assert exc.value.detail["error_code"] == "invalid_query_id"


@pytest.mark.asyncio
async def test_query_impact_route_empty_without_flow(monkeypatch):
    from src.api.routes import memory as routes

    org = uuid4()

    class Ctx:
        organization_id = org

    monkeypatch.setattr(routes, "require_permission", lambda request, perm: Ctx())

    async def _missing(_org, _query_id):
        assert _org == org
        return None

    monkeypatch.setattr("src.rag.flow_store.request_id_for_query", _missing)
    query_id = uuid4()
    body = await routes.query_memory_impact(str(query_id), request=object())
    assert body["query_id"] == str(query_id)
    assert body["truncated"] is False
    assert body["counts"]["used"] == 0
    assert body["created"] == []
    _forbidden(body)


def test_request_id_lookup_filters_tenant_and_skips_flow_json():
    from src.rag import flow_store

    source = inspect.getsource(flow_store.request_id_for_query)
    assert "organization_id = :oid" in source
    assert "query_id = :qid" in source
    assert "SELECT request_id" in source
    assert "SELECT flow" not in source


def test_events_for_request_sql_is_tenant_scoped():
    source = inspect.getsource(InMemoryMemoryRepository)
    assert "request_id" in source
    from src.infrastructure.postgres.memory_store import PostgresMemoryRepository

    sql = inspect.getsource(PostgresMemoryRepository.events_for_request)
    assert "organization_id = :oid" in sql
    assert "request_id = :request_id" in sql
    assert "LIMIT :limit" in sql
