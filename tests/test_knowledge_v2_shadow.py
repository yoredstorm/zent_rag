# =============================================================================
# Knowledge V2 — Orchestrator shadow retrieval (Phase F slice 1)
# =============================================================================
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.agents.runtime.orchestrator import RAGOrchestrator
from src.core.config import get_settings
from src.core.domain.entities import RetrievalChunk, RetrievalContext
from src.rag.retrieval.structured import AssembledContext, V2RetrievalOptions


class StubStructuredRetriever:
    def __init__(self, children: list[RetrievalChunk]) -> None:
        self._children = children
        self.called = False
        self.last_query = None
        self.last_options = None

    async def retrieve(self, query, options: V2RetrievalOptions | None = None):
        self.called = True
        self.last_query = query
        self.last_options = options
        return AssembledContext(
            children=tuple(self._children),
            parents=(),
            context=tuple(self._children),
            options=options or V2RetrievalOptions(),
        )


def _stub() -> SimpleNamespace:
    return SimpleNamespace()


def _build_orchestrator(structured_retriever=None, promote_v2: bool = False) -> RAGOrchestrator:
    return RAGOrchestrator(
        organization_repo=_stub(),
        vector_store=_stub(),
        llm_provider=_stub(),
        embedding_provider=_stub(),
        cache_provider=_stub(),
        structured_retriever=structured_retriever,
        promote_v2=promote_v2,
    )


def _hash_chunk(content: str, chash: str) -> RetrievalChunk:
    return RetrievalChunk(
        document_id=uuid4(),
        content=content,
        score=0.9,
        metadata={"content_hash": chash, "v2_chunk": "true"},
    )


async def _enable_shadow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_KNOWLEDGE_V2_SHADOW", "true")
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_shadow_runs_when_retriever_injected(monkeypatch) -> None:
    await _enable_shadow(monkeypatch)
    shared = "hash-compartido"
    stub_retriever = StubStructuredRetriever(
        children=[_hash_chunk("v2 ctx", shared)]
    )
    orch = _build_orchestrator(stub_retriever)
    v1_context = RetrievalContext(
        chunks=[_hash_chunk("v1 ctx", shared), _hash_chunk("otro", "h2")]
    )

    await orch._maybe_v2_shadow(
        organization_id=uuid4(),
        user_id=None,  # sin ACL groups + si no hay db en el test
        query="Resume el contrato",
        role="admin",
        query_embedding=[0.1, 0.2],
        retrieval_context=v1_context,
        metadata_filters=None,
        language=None,
    )

    assert stub_retriever.called is True
    assert stub_retriever.last_query is not None
    assert stub_retriever.last_options is not None


@pytest.mark.asyncio
async def test_shadow_skipped_without_retriever(monkeypatch) -> None:
    await _enable_shadow(monkeypatch)
    orch = _build_orchestrator(structured_retriever=None)
    nothing = object()

    # sin retriever inyectado → no se ejecuta nada
    result = await orch._maybe_v2_shadow(  # type: ignore[call-arg]
        organization_id=uuid4(),
        user_id=None,
        query="hola",
        role="admin",
        query_embedding=[0.1],
        retrieval_context=RetrievalContext(),
        metadata_filters=None,
        language=None,
    )
    assert result is None
    assert nothing is not None  # noop guard


@pytest.mark.asyncio
async def test_shadow_respects_flag_off(monkeypatch) -> None:
    monkeypatch.setenv("RAG_KNOWLEDGE_V2_SHADOW", "false")
    get_settings.cache_clear()
    stub_retriever = StubStructuredRetriever(
        children=[_hash_chunk("x", "h")]
    )
    orch = _build_orchestrator(stub_retriever)

    await orch._maybe_v2_shadow(
        organization_id=uuid4(),
        user_id=None,
        query="hola",
        role="admin",
        query_embedding=[0.1],
        retrieval_context=RetrievalContext(),
        metadata_filters=None,
        language=None,
    )
    assert stub_retriever.called is False


@pytest.mark.asyncio
async def test_promote_uses_v2_retriever_as_productive_context() -> None:
    from src.rag.retrieval.config import resolve_retrieval_config

    stub_retriever = StubStructuredRetriever(
        children=[_hash_chunk("contexto v2 productivo", "h")]
    )
    orch = _build_orchestrator(stub_retriever, promote_v2=True)
    retrieval_config = resolve_retrieval_config(
        request_overrides={},
        organization_config={},
    )

    ctx = await orch._run_v2_retrieve(
        organization_id=uuid4(),
        user_id=None,
        query="¿comisión?",
        role="admin",
        query_embedding=[0.1, 0.2],
        metadata_filters=None,
        language=None,
        retrieval_config=retrieval_config,
    )
    assert stub_retriever.called is True
    assert ctx.chunks
    assert any("v2 productivo" in c.content for c in ctx.chunks)
    assert ctx.retrieval_latency_ms >= 0.0
