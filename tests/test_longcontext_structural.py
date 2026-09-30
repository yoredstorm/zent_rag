# =============================================================================
# Long-Context Fase 3 — expansión estructural sobre store (parent/sibling/nota)
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from src.core.domain.entities import RetrievalChunk, RetrievalContext
from src.intelligence.response.anchors import extract_anchors
from src.rag.longcontext.expansion import (
    ExactAnchorExpansion,
    ExpansionContext,
    ParentSectionExpansion,
    SectionNeighborhoodExpansion,
    TableNoteExpansion,
    default_strategies,
)
from src.rag.longcontext.must_keep import is_must_keep
from src.rag.retrieval.models import RetrievalQuery

ORG = UUID("11111111-1111-1111-1111-111111111111")


def _chunk(texto: str, **metadata: str) -> RetrievalChunk:
    return RetrievalChunk(
        document_id=uuid4(), content=texto, score=0.5, metadata=metadata
    )


class _Store:
    def __init__(
        self,
        *,
        by_chunk_id: list[RetrievalChunk] | None = None,
        neighborhood: list[RetrievalChunk] | None = None,
        literal: list[RetrievalChunk] | None = None,
    ) -> None:
        self._by_chunk_id = by_chunk_id or []
        self._neighborhood = neighborhood or []
        self._literal = literal or []
        self.chunk_id_calls: list[list[str]] = []
        self.neighborhood_calls: list[dict] = []
        self.literal_calls: list[list[str]] = []

    async def get_documents_by_chunk_ids(self, organization_id, chunk_ids, **kwargs):
        self.chunk_id_calls.append([str(value) for value in chunk_ids])
        wanted = set(self.chunk_id_calls[-1])
        return RetrievalContext(
            chunks=[
                chunk
                for chunk in self._by_chunk_id
                if str((chunk.metadata or {}).get("chunk_id") or "") in wanted
            ]
        )

    async def get_neighborhood(self, organization_id, **kwargs):
        self.neighborhood_calls.append(kwargs)
        return RetrievalContext(chunks=list(self._neighborhood))

    async def scan_text_literal(self, *, needles, **kwargs):
        self.literal_calls.append([str(needle) for needle in needles])
        return RetrievalContext(chunks=list(self._literal))


def _query() -> RetrievalQuery:
    return RetrievalQuery(
        query="consulta",
        organization_id=ORG,
        query_embedding=[0.1, 0.2],
    )


def _context(chunks: list[RetrievalChunk], **kwargs) -> ExpansionContext:
    return ExpansionContext(query=_query(), chunks=chunks, **kwargs)


class TestStructuralExpansion:
    @pytest.mark.asyncio
    async def test_parent_section_fetched(self) -> None:
        padre = _chunk("sección completa que explica", chunk_id="p1")
        store = _Store(by_chunk_id=[padre])
        strategy = ParentSectionExpansion(store)
        hijo = _chunk("fragmento partido", parent_id="p1")

        expansion = await strategy.expand(_context([hijo]))

        assert [c.document_id for c in expansion.chunks] == [padre.document_id]
        assert expansion.chunks[0].metadata["retrieval"] == "expansion_parent"

    @pytest.mark.asyncio
    async def test_neighborhood_uses_prev_next_and_section(self) -> None:
        store = _Store(neighborhood=[_chunk("hermano siguiente", chunk_id="n2")])
        strategy = SectionNeighborhoodExpansion(store)
        actual = _chunk(
            "fragmento actual",
            parent_id="p1",
            section_id="s1",
            prev_chunk_id="n0",
            next_chunk_id="n2",
        )

        expansion = await strategy.expand(_context([actual]))

        call = store.neighborhood_calls[0]
        assert "p1" in call["chunk_ids"]
        assert "n0" in call["chunk_ids"]  # prev
        assert "n2" in call["chunk_ids"]  # next
        assert call["section_ids"] == ["s1"]
        assert expansion.chunks[0].metadata["retrieval"] == "expansion_section"

    @pytest.mark.asyncio
    async def test_table_note_references_become_needles(self) -> None:
        store = _Store(literal=[_chunk("Nota 4: complementa la Tabla 9")])
        strategy = TableNoteExpansion(store)
        actual = _chunk("El byte 105 se detalla en la Tabla 9, ver Nota 4.")

        expansion = await strategy.expand(_context([actual]))

        needles = [needle.lower() for needle in store.literal_calls[0]]
        assert "tabla 9" in needles
        assert "nota 4" in needles
        assert expansion.chunks[0].metadata["retrieval"] == "expansion_table_note"

    @pytest.mark.asyncio
    async def test_exact_anchor_expansion_marks_must_keep(self) -> None:
        store = _Store(literal=[_chunk("La máscara &&&F acepta QNNF0SME")])
        strategy = ExactAnchorExpansion(store)
        anchors = extract_anchors("consulta si FCLAS &&&F acepta QNNF0SME")

        expansion = await strategy.expand(
            _context([], anchors=anchors, missing_needles=("&&&F", "QNNF0SME"))
        )

        assert expansion.chunks
        assert is_must_keep(expansion.chunks[0])
        assert expansion.chunks[0].metadata["retrieval"] == "expansion_exact"
        needles = [needle.lower() for needle in store.literal_calls[0]]
        assert "&&&f" in needles

    def test_default_strategy_order_is_specific_to_broad(self) -> None:
        async def _retrieve(spec):  # pragma: no cover - sólo orden
            return RetrievalContext(chunks=[])

        names = [strategy.name for strategy in default_strategies(_Store(), _retrieve)]
        assert names == [
            "parent_sections",
            "section_neighborhood",
            "exact_anchors",
            "table_notes",
            "same_document",
            "cross_document",
            "concepts",
            "document_level",
        ]
