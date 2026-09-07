"""Phase 26C — Verified Query search and mapping suggestions."""
from __future__ import annotations

from uuid import UUID

import pytest

from src.core.domain.semantic import BusinessSemanticAST, SemanticCompileResult
from src.core.domain.verified_query import (
    MappingSuggestionStatus,
    VerifiedQuery,
    VerifiedQueryStatus,
)
from src.intelligence.verified_queries import VerifiedQueryService

ORG = UUID(int=1)


class _MemStore:
    def __init__(self) -> None:
        self.items: list[VerifiedQuery] = []
        self.suggestions = []

    async def list_verified(self, organization_id, *, dialect=None):
        items = [
            i
            for i in self.items
            if i.organization_id == organization_id
            and i.status == VerifiedQueryStatus.VERIFIED
        ]
        if dialect:
            items = [i for i in items if i.dialect == dialect]
        return items

    async def upsert(self, item):
        self.items.append(item)
        return item

    async def upsert_mapping_suggestion(self, suggestion):
        self.suggestions.append(suggestion)
        return suggestion


@pytest.fixture
def service() -> VerifiedQueryService:
    svc = VerifiedQueryService(store=_MemStore())  # type: ignore[arg-type]
    return svc


@pytest.mark.asyncio
async def test_search_requires_semantic_overlap_not_just_text(
    service: VerifiedQueryService,
) -> None:
    store: _MemStore = service.store  # type: ignore[assignment]
    store.items.append(
        VerifiedQuery(
            organization_id=ORG,
            name="corp sales yesterday",
            canonical_question="¿Cuántas ventas corporativas hubo ayer?",
            verified_sql="SELECT count(*) FROM sales WHERE segment='corp'",
            status=VerifiedQueryStatus.VERIFIED,
            semantic_ast={
                "query_type": "metric_query",
                "metrics": [],
                "segments": ["corporativo"],
                "entities": [],
                "facts": ["ventas"],
                "time": {"scope": "past"},
            },
            dialect="postgres",
        )
    )
    # Different semantics — warehouse inventory — similar Spanish noise words only
    compiled = SemanticCompileResult(
        semantic_ast=BusinessSemanticAST(
            query_type="metric_query",
            metrics=[{"name": "margen", "version": None}],
            segments=[],
            entities=[],
            time={"scope": "past"},
            facts=[],
        )
    )
    hits = await service.search(
        ORG,
        question="¿Cuál es el margen del almacén?",
        compile_result=compiled,
        min_score=0.2,
    )
    assert hits == []


@pytest.mark.asyncio
async def test_search_matches_on_shared_segment_and_fact(
    service: VerifiedQueryService,
) -> None:
    store: _MemStore = service.store  # type: ignore[assignment]
    store.items.append(
        VerifiedQuery(
            organization_id=ORG,
            name="corp sales",
            canonical_question="ventas corporativas ayer",
            verified_sql="SELECT 1",
            status=VerifiedQueryStatus.VERIFIED,
            semantic_ast={
                "metrics": [],
                "segments": ["corporativo"],
                "entities": [],
                "facts": ["ventas"],
                "time": {"scope": "past"},
            },
        )
    )
    compiled = SemanticCompileResult(
        semantic_ast=BusinessSemanticAST(
            query_type="metric_query",
            metrics=[],
            segments=["corporativo"],
            facts=["ventas"],
            time={"from": "2026-08-01", "to": "2026-08-31"},
        )
    )
    # Boost metric overlap via concept deps path — use segment match heavily
    # by also putting corporativo in compile segments (already) and question text
    hits = await service.search(
        ORG,
        question="ventas corporativas agosto",
        compile_result=compiled,
        min_score=0.2,
    )
    assert len(hits) == 1
    assert hits[0].adaptable is True
    assert "time" in hits[0].adaptation_notes[0]


def test_adapt_time_only_does_not_mutate_sql(
    service: VerifiedQueryService,
) -> None:
    vq = VerifiedQuery(
        organization_id=ORG,
        name="x",
        canonical_question="ventas ayer",
        verified_sql="SELECT 1 FROM sales WHERE d=current_date-1",
        semantic_ast={"time": {"scope": "past"}, "segments": ["corporativo"]},
        status=VerifiedQueryStatus.VERIFIED,
    )
    adapted = service.adapt_time_only(
        vq, new_time={"from": "2026-08-01", "to": "2026-08-31"}
    )
    assert adapted["verified_sql"] == vq.verified_sql
    assert adapted["semantic_ast"]["time"]["from"] == "2026-08-01"
    assert adapted["adaptation"] == "time_only"


@pytest.mark.asyncio
async def test_mapping_suggestion_stays_inferred(
    service: VerifiedQueryService,
) -> None:
    sqls = [
        "SELECT * FROM t WHERE CCUST = '139'",
        "SELECT sum(a) FROM t WHERE CCUST = '139'",
        "SELECT * FROM t WHERE CCUST = '139' AND x=1",
    ]
    suggestion = await service.suggest_mappings_from_sql_history(
        ORG, concept="Aeromexico", successful_sql=sqls, min_evidence=3
    )
    assert suggestion is not None
    assert suggestion.status == MappingSuggestionStatus.INFERRED
    assert "CCUST" in suggestion.physical_predicate
    assert suggestion.evidence_count >= 3
