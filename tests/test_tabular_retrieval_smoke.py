# =============================================================================
# Tabular retrieval smoke — los chunks tabulares son recuperables (Qdrant real)
# =============================================================================
# Verifica que, sin filas V1, la búsqueda sparse (BM25 sobre vectores sparse de
# Qdrant) encuentra row-groups/rows tabulares con headers y que el filtro
# `metadata.v2_tabular` funciona. Es la garantía de que el supersede V1 no deja
# al agente sin evidencia.
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from src.infrastructure.qdrant.vector_store import QdrantVectorStore
from src.knowledge.structure import get_parser
from src.knowledge.tabular.chunker import TabularChunkingConfig, chunk_tabular_workbook
from tests import tabular_fixtures as fx

_ORG = UUID("00000000-0000-0000-0000-0000000000aa")
_SOURCE = UUID("00000000-0000-0000-0000-0000000000bb")


def _document():
    return get_parser("xlsx").parse(
        fx.atpco_workbook_bytes(),
        organization_id=_ORG,
        external_id="obj/ATPCO_TEST.xlsx",
        source_id=_SOURCE,
        source_name="ATPCO_TEST.xlsx",
    )


@pytest.mark.asyncio
async def test_sparse_search_finds_tabular_chunks_with_headers() -> None:
    store = QdrantVectorStore()
    organization_id = uuid4()
    document = _document()
    chunks = chunk_tabular_workbook(
        document, config=TabularChunkingConfig(row_group_size=4)
    )
    assert chunks
    points = []
    for chunk in chunks:
        metadata = {
            **chunk.metadata,
            "source_id": str(_SOURCE),
            "document_id": str(document.id),
            "v2_doc": "true",
            "content_hash": chunk.content_hash,
        }
        points.append((uuid4(), [0.1] * 1024, chunk.content, metadata))
    await store.upsert_batch(organization_id, points)
    try:
        result = await store.search_sparse(
            organization_id,
            "Carrier Code 28",
            top_k=5,
            filters={"metadata.v2_tabular": "true"},
            score_threshold=0.0,
            role="admin",
        )
        assert result.chunks, "sparse no recuperó chunks tabulares"
        assert any("Carrier Code" in chunk.content for chunk in result.chunks)
        group = next(
            chunk
            for chunk in result.chunks
            if chunk.metadata.get("knowledge_type") == "table_row_group"
        )
        assert "KEY:" in group.content
        assert "Start Position" in group.content
    finally:
        await store.delete_points(
            organization_id, [str(point[0]) for point in points]
        )


@pytest.mark.asyncio
async def test_sparse_search_tabular_filter_excludes_other_docs() -> None:
    store = QdrantVectorStore()
    organization_id = uuid4()
    other_point = (
        uuid4(),
        [0.1] * 1024,
        "Carrier Code appears in a non-tabular document",
        {"source_id": str(uuid4()), "v2_doc": "true"},
    )
    await store.upsert_batch(organization_id, [other_point])
    try:
        result = await store.search_sparse(
            organization_id,
            "Carrier Code",
            top_k=5,
            filters={"metadata.v2_tabular": "true"},
            score_threshold=0.0,
            role="admin",
        )
        assert all(
            chunk.metadata.get("v2_tabular") == "true" for chunk in result.chunks
        )
    finally:
        await store.delete_points(organization_id, [str(other_point[0])])
