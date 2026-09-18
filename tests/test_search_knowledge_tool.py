# =============================================================================
# search_knowledge tool — timeout configurable + instrumentación por etapa (§30)
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest

from src.agents.tools.base import ToolContext
from src.agents.tools.tools_builtin import SearchKnowledgeTool
from src.core.config import get_settings
from src.core.domain.entities import RetrievalChunk, RetrievalContext


class FakeRetriever:
    def __init__(self) -> None:
        self.queries: list = []

    async def retrieve(self, query) -> RetrievalContext:
        self.queries.append(query)
        return RetrievalContext(
            chunks=[
                RetrievalChunk(
                    document_id=uuid4(),
                    content="Start Position: 28",
                    score=0.9,
                    metadata={"source_id": "src-1"},
                )
            ],
            retrieval_latency_ms=1.0,
        )


class FakeEmbedder:
    async def embed(self, text, model=None):
        return [0.1] * 8


def make_context(org_id) -> ToolContext:
    return ToolContext(
        tenant_id=org_id,
        role="admin",
        org_config={"source_ids": [str(uuid4())]},
    )


@pytest.mark.asyncio
async def test_search_knowledge_reports_stage_latencies() -> None:
    retriever = FakeRetriever()
    tool = SearchKnowledgeTool(retriever, embedder=FakeEmbedder())
    organization_id = uuid4()
    context = make_context(organization_id)

    result = await tool.execute(context, {"query": "posición de Carrier Code"})
    assert result.error is None
    assert "Start Position: 28" in result.output
    stage_ms = result.meta["stage_ms"]
    for key in ("query_embedding_ms", "retrieve_ms", "total_ms"):
        assert key in stage_ms
        assert stage_ms[key] >= 0
    assert result.meta["source_ids"] == ["src-1"]
    assert len(retriever.queries) == 1


def test_search_knowledge_timeout_uses_settings(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "RAG_SEARCH_KNOWLEDGE_TIMEOUT_SECONDS", 7)
    tool = SearchKnowledgeTool(FakeRetriever(), embedder=FakeEmbedder())
    assert tool.timeout_seconds == 7


class FakeTabularService:
    def __init__(self, result) -> None:
        self.result = result
        self.calls: list[dict] = []

    async def try_answer(self, organization_id, question, **kwargs):
        self.calls.append({"organization_id": organization_id, "question": question, **kwargs})
        return self.result


class FakeBigTabularRetriever:
    """Chunk tabular largo: el marcador está más allá del corte viejo de 1200."""

    def __init__(self) -> None:
        self.queries: list = []
        marker_at = 1500
        content = ("TABLE: T | SHEET: S | ROWS: 1-40\nKEY: Field Name | Start Loc\n"
                   + "x" * marker_at
                   + "\nMARKER_AFTER_1200 Field Name=Carrier Code | Start Loc=6")
        self._chunk = RetrievalChunk(
            document_id=uuid4(),
            content=content,
            score=0.5,
            metadata={
                "source_id": "src-1",
                "knowledge_type": "table_row_group",
                "table_name": "T",
                "row_start": 1,
                "row_end": 40,
            },
        )

    async def retrieve(self, query) -> RetrievalContext:
        self.queries.append(query)
        return RetrievalContext(chunks=[self._chunk], retrieval_latency_ms=1.0)


@pytest.mark.asyncio
async def test_search_knowledge_prefers_exact_and_keeps_full_tabular_chunk() -> None:
    from src.core.ports.sql_expert import SqlQueryResult

    exact = SqlQueryResult(
        sql="-- zent tabular\nSELECT 1;",
        columns=["Field Name", "Start Loc"],
        rows=[["Carrier Code", "6"]],
        row_count=1,
        metadata={
            "strategy": "tabular_lookup:row_label+column",
            "confidence": 0.95,
            "tables": ["ATPCO_Attributes"],
            "provenance": [
                {
                    "workbook": "atpco.xlsx",
                    "sheet": "ATPCO_Attributes",
                    "table": "ATPCO_Attributes",
                    "row": 5775,
                    "cell": "B5775",
                    "column": "Start Loc",
                }
            ],
        },
    )
    tabular = FakeTabularService(exact)
    tool = SearchKnowledgeTool(
        FakeBigTabularRetriever(), embedder=FakeEmbedder(), tabular_query=tabular
    )

    result = await tool.execute(make_context(uuid4()), {"query": "posición de Carrier Code"})

    assert result.error is None
    assert result.output.startswith("[EXACT structured lookup]")
    assert "Start Loc: 6" in result.output
    assert "B5775" in result.output
    assert "MARKER_AFTER_1200" in result.output  # presupuesto tabular 6000
    assert result.meta["exact"] is True
    assert tabular.calls and tabular.calls[0]["source_ids"]
