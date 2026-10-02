# =============================================================================
# Runners graph + temporal — observación con refs canónicas (C2).
# =============================================================================
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from src.runtime.entity_resolution import (
    EntityMatch,
    EntityResolution,
    MentionResolution,
)
from src.runtime.graph_runner import GraphRunner
from src.runtime.representation_runners import RunnerContext
from src.runtime.temporal_runner import TemporalRunner

_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _ctx(entities: EntityResolution | None) -> RunnerContext:
    return RunnerContext(
        query="q",
        organization_id=uuid4(),
        user_id=None,
        role="admin",
        strategy=None,
        entities=entities,
    )


def _resolved(canonical_id: str, name: str = "Category 31") -> EntityResolution:
    return EntityResolution(
        mentions=(
            MentionResolution(
                mention=name,
                status="resolved",
                matches=(
                    EntityMatch(
                        mention=name,
                        canonical_id=canonical_id,
                        name=name,
                        kind="entity",
                        match="exact_name",
                        confidence=0.9,
                    ),
                ),
            ),
        )
    )


class FakeEdges:
    def __init__(self, edges, *, boom=False):
        self.edges = edges
        self.boom = boom
        self.calls = 0

    async def object_edges(self, organization_id, object_id, *, limit=200):
        self.calls += 1
        if self.boom:
            raise RuntimeError("caída")
        return {"edges": self.edges, "count": len(self.edges)}


class FakeAssertions:
    def __init__(self, rows, *, boom=False):
        self.rows = rows
        self.boom = boom

    async def object_assertions(self, organization_id, object_id, *, limit=100):
        if self.boom:
            raise RuntimeError("caída")
        return self.rows


@pytest.mark.asyncio
async def test_graph_runner_items_con_refs() -> None:
    edge = {
        "id": str(uuid4()),
        "subject_id": str(uuid4()),
        "object_id": str(uuid4()),
        "subject_name": "Record 4",
        "predicate": "requires",
        "object_name": "Record 2",
        "relationship_type": "depends_on",
        "confidence": 0.8,
    }
    lookup = FakeEdges([edge])
    result = await GraphRunner(lookup).run(_ctx(_resolved(str(uuid4()))))
    assert result.status == "ok"
    assert result.items[0].refs["edge_id"] == edge["id"]
    assert result.items[0].refs["predicate"] == "requires"
    assert "Record 4" in result.items[0].title
    assert lookup.calls == 1


@pytest.mark.asyncio
async def test_graph_runner_sin_entidades_skip() -> None:
    result = await GraphRunner(FakeEdges([])).run(_ctx(None))
    assert result.status == "skipped"


@pytest.mark.asyncio
async def test_graph_runner_ambigua_no_consulta() -> None:
    ambiguous = EntityResolution(
        mentions=(MentionResolution(mention="R", status="ambiguous", matches=()),)
    )
    lookup = FakeEdges([])
    result = await GraphRunner(lookup).run(_ctx(ambiguous))
    assert result.status == "skipped"
    assert lookup.calls == 0


@pytest.mark.asyncio
async def test_temporal_runner_estado_vigencia() -> None:
    rows = [
        {
            "id": str(uuid4()),
            "subject_label": "Rule X",
            "predicate": "applies_to",
            "object_value": "Category 31",
            "confidence": 0.9,
            "valid_from": "2024-01-01T00:00:00+00:00",
            "valid_to": "2025-01-01T00:00:00+00:00",
        },
        {
            "id": str(uuid4()),
            "subject_label": "Rule X",
            "predicate": "applies_to",
            "object_value": "Category 32",
            "confidence": 0.8,
            "valid_from": "2025-06-01T00:00:00+00:00",
            "valid_to": None,
        },
    ]
    runner = TemporalRunner(FakeAssertions(rows), now=lambda: _NOW)
    result = await runner.run(_ctx(_resolved(str(uuid4()))))
    assert result.status == "ok"
    states = [item.refs["validity"] for item in result.items]
    assert states == ["historical", "current"]
    assert result.items[0].refs["assertion_id"] == rows[0]["id"]
    assert result.items[0].refs["object_value"] == "Category 31"
    assert result.items[0].refs["subject_label"] == "Rule X"


@pytest.mark.asyncio
async def test_temporal_runner_sin_ventana_es_empty() -> None:
    rows = [
        {
            "id": str(uuid4()),
            "subject_label": "Rule X",
            "predicate": "applies_to",
            "object_value": "Category 31",
            "confidence": 0.9,
            "valid_from": None,
            "valid_to": None,
        }
    ]
    runner = TemporalRunner(FakeAssertions(rows), now=lambda: _NOW)
    result = await runner.run(_ctx(_resolved(str(uuid4()))))
    assert result.status == "empty"
