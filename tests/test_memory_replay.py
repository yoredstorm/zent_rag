"""Replay de una respuesta histórica contra la memoria actual."""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from src.memory.replay import ReplayBlocked, ReplayBook, ReplayNotFound, compare_flows, what_changed


def _atpco_original() -> dict:
    return {
        "query_id": "11111111-1111-1111-1111-111111111111",
        "status": "completed",
        "verdict": {"route": "Documentos"},
        "retrieval": {"strategy": "vector", "chunks": 2},
        "evidence": {"sufficient": False, "score": 0.22},
        "generation": {"cost": 0.0041},
        "timings": {"total_ms": 1800},
        "sources": [{"title": "ATPCO_Record2.xlsx", "score": 0.31}],
    }


def _atpco_current() -> dict:
    return {
        "query_id": "22222222-2222-2222-2222-222222222222",
        "status": "completed",
        "verdict": {"route": "Documentos"},
        "retrieval": {"strategy": "structured_exact", "chunks": 1},
        "grounding": {"grounded": True, "score": 0.97},
        "generation": {"cost": 0.0008},
        "timings": {"total_ms": 600},
        "sources": [{"title": "ATPCO_Record2.xlsx", "score": 0.99}],
    }


def test_replay_creates_a_new_run_and_leaves_the_original():
    org = uuid4()
    book = ReplayBook()
    original = _atpco_original()
    book.remember(org, original)
    frozen = {
        "query_id": original["query_id"],
        "retrieval": {"strategy": "vector", "chunks": 2},
    }
    result = book.start(
        org,
        UUID(original["query_id"]),
        tools=[{"name": "query_database", "execution": "dry_run", "side_effect": True}],
        patterns=[
            {
                "memory_id": "93800000-0000-0000-0000-000000000938",
                "display_id": "93800000",
                "title": "Structured field lookup",
                "retrieval_modality": "structured_exact",
            }
        ],
        original_memories=[],
    )
    assert result["replay_query_id"] != result["source_query_id"]
    assert result["original_unchanged"] is True
    assert original["retrieval"]["strategy"] == "vector"
    assert book.flows[(str(org), original["query_id"])]["retrieval"] == frozen["retrieval"]
    assert result["comparison"]["fields"]["retrieval_strategy"]["current"] == "structured_exact"
    assert result["comparison"]["fields"]["grounding"]["current"] is None
    assert result["comparison"]["fields"]["cost"]["current"] is None


def test_side_effect_tool_without_simulation_is_blocked():
    org = uuid4()
    book = ReplayBook()
    original = _atpco_original()
    book.remember(org, original)
    with pytest.raises(ReplayBlocked) as exc:
        book.start(
            org,
            UUID(original["query_id"]),
            tools=[{"name": "send_email", "execution": "live"}],
            patterns=[],
        )
    assert exc.value.tool == "send_email"
    assert book.replays == []
    assert original["retrieval"]["strategy"] == "vector"


def test_other_tenant_cannot_replay():
    org = uuid4()
    book = ReplayBook()
    book.remember(org, _atpco_original())
    with pytest.raises(ReplayNotFound):
        book.start(uuid4(), UUID(_atpco_original()["query_id"]), tools=[], patterns=[])


def test_what_changed_uses_only_real_diffs():
    memory_id = "93800000-0000-0000-0000-000000000938"
    changes = what_changed(
        _atpco_original(),
        _atpco_current(),
        original_memories=[],
        current_memories=[
            {
                "memory_id": memory_id,
                "display_id": "93800000",
                "title": "Structured field lookup",
            }
        ],
    )
    kinds = [item["kind"] for item in changes]
    assert "retrieval_strategy" in kinds
    assert "memory" in kinds
    assert "cost" in kinds
    assert "latency_ms" in kinds
    assert "grounding" not in kinds
    both = what_changed(
        {**_atpco_original(), "grounding": {"grounded": False, "score": 0.22}},
        _atpco_current(),
        original_memories=[],
        current_memories=[],
    )
    assert any(item["kind"] == "grounding" and item["original"] == 0.22 for item in both)
    assert all(item["kind"] != "passage_judge" for item in changes)
    memory = next(item for item in changes if item["kind"] == "memory")
    assert memory["memory_id"] == memory_id
    assert memory["title"] == "Structured field lookup"


def test_improvement_requires_comparable_metrics():
    compared = compare_flows(_atpco_original(), _atpco_current())
    assert compared["improvement"]["quality"] is None
    assert compared["improvement"]["cost"] == pytest.approx((0.0008 - 0.0041) / 0.0041, rel=1e-3)
    partial = compare_flows(
        {"verdict": {"route": "Documentos"}, "retrieval": {"strategy": "vector"}},
        {"verdict": {"route": "Documentos"}, "retrieval": {"strategy": "vector"}},
    )
    assert partial["improvement"]["quality"] is None
    assert partial["improvement"]["cost"] is None
    assert partial["fields"]["grounding"]["original"] is None
    assert partial["fields"]["cost"]["current"] is None


def test_same_memory_is_not_listed_as_a_change():
    memory = {"memory_id": "abc", "display_id": "abc", "title": "Lookup"}
    changes = what_changed(
        _atpco_original(),
        {**_atpco_original(), "query_id": "other"},
        original_memories=[memory],
        current_memories=[memory],
    )
    assert all(item["kind"] != "memory" for item in changes)


@pytest.mark.asyncio
async def test_replay_route_creates_a_new_run(monkeypatch):
    from src.api.routes import memory as routes

    org = uuid4()
    source = uuid4()
    original = {
        "status": "completed",
        "verdict": {"route": "Documentos"},
        "retrieval": {"strategy": "vector"},
    }

    class Ctx:
        organization_id = org

    monkeypatch.setattr(routes, "require_permission", lambda request, perm: Ctx())

    async def _flow(organization_id, query_id):
        assert organization_id == org
        assert query_id == source
        return dict(original)

    async def _request_id(_organization_id, _query_id):
        return None

    async def _patterns(_organization_id, question):
        assert "Record2" in question
        return [
            {
                "memory_id": "93800000-0000-0000-0000-000000000938",
                "display_id": "93800000",
                "title": "Structured field lookup",
                "retrieval_modality": "structured_exact",
            }
        ]

    saved: list[dict] = []

    async def _persist(organization_id, result):
        assert organization_id == org
        saved.append(result)

    monkeypatch.setattr("src.rag.flow_store.get_flow", _flow)
    monkeypatch.setattr("src.rag.flow_store.request_id_for_query", _request_id)
    monkeypatch.setattr(routes, "_replay_patterns", _patterns)
    monkeypatch.setattr("src.memory.replay_store.persist_replay", _persist)
    body = await routes.replay_query(
        str(source),
        routes.ReplayIn(question="¿Cuál es la posición del carrier code en Record2?"),
        object(),
    )
    assert body["source_query_id"] == str(source)
    assert body["replay_query_id"] != str(source)
    assert body["original_unchanged"] is True
    assert "organization_id" not in body
    assert body["comparison"]["fields"]["retrieval_strategy"]["original"] == "vector"
    assert body["comparison"]["fields"]["retrieval_strategy"]["current"] == "structured_exact"
    assert saved[0]["replay_id"] == body["replay_id"]
    assert original["retrieval"]["strategy"] == "vector"


@pytest.mark.asyncio
async def test_replay_route_blocks_live_email(monkeypatch):
    from fastapi import HTTPException

    from src.api.routes import memory as routes

    org = uuid4()

    class Ctx:
        organization_id = org

    monkeypatch.setattr(routes, "require_permission", lambda request, perm: Ctx())

    async def _flow(_organization_id, query_id):
        return {"query_id": str(query_id), "verdict": {"route": "Documentos"}}

    async def _missing(*_args, **_kwargs):
        return None

    monkeypatch.setattr("src.rag.flow_store.get_flow", _flow)
    monkeypatch.setattr("src.rag.flow_store.request_id_for_query", _missing)
    monkeypatch.setattr(routes, "_replay_patterns", _missing)
    with pytest.raises(HTTPException) as exc:
        await routes.replay_query(
            str(uuid4()),
            routes.ReplayIn(tools=[{"name": "send_email", "execution": "live"}]),
            object(),
        )
    assert exc.value.status_code == 409
    assert exc.value.detail["error_code"] == "replay_blocked"


@pytest.mark.asyncio
async def test_replay_route_missing_flow_is_404(monkeypatch):
    from fastapi import HTTPException

    from src.api.routes import memory as routes

    class Ctx:
        organization_id = uuid4()

    monkeypatch.setattr(routes, "require_permission", lambda request, perm: Ctx())

    async def _missing(*_args, **_kwargs):
        return None

    monkeypatch.setattr("src.rag.flow_store.get_flow", _missing)
    with pytest.raises(HTTPException) as exc:
        await routes.replay_query(str(uuid4()), routes.ReplayIn(), object())
    assert exc.value.status_code == 404

