# =============================================================================
# P1 remediation tests — retrieval correctness (F4, F6, F18)
# =============================================================================
# - F4: workspace_id debe viajar del query al store (filtro pre-LLM).
# - F6: la fusión server-side devuelve scores RRF; el umbral coseno no debe
#   aplicarse ni la fusión server-side debe preferirse sobre la client-side.
# - F18: fetch por ID debe respetar ACL (visibility/acl_users/acl_groups).
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest

from src.core.domain.entities import RetrievalChunk, RetrievalContext
from src.rag.retrieval.hybrid import HybridRetriever
from src.rag.retrieval.models import (
    STRATEGY_HYBRID,
    STRATEGY_VECTOR,
    RetrievalQuery,
)
from src.rag.retrieval.structured import StructuredRetriever, V2RetrievalOptions


def _chunk(score: float = 0.9, content: str = "texto") -> RetrievalChunk:
    return RetrievalChunk(document_id=uuid4(), content=content, score=score)


class _RecordingVectorStore:
    def __init__(self, chunks: list[RetrievalChunk] | None = None) -> None:
        self.chunks = chunks or [_chunk(0.9)]
        self.search_kwargs: list[dict] = []
        self.get_documents_kwargs: list[dict] = []

    async def search(self, **kwargs) -> RetrievalContext:
        self.search_kwargs.append(kwargs)
        return RetrievalContext(chunks=list(self.chunks), retrieval_latency_ms=1.0)

    async def search_sparse(self, **kwargs) -> RetrievalContext:
        return RetrievalContext(chunks=list(self.chunks), retrieval_latency_ms=1.0)

    async def get_documents(self, organization_id, document_ids, **kwargs) -> RetrievalContext:
        self.get_documents_kwargs.append(
            {"organization_id": organization_id, "document_ids": document_ids, **kwargs}
        )
        return RetrievalContext(chunks=[], retrieval_latency_ms=0.0)

    async def upsert(self, *args, **kwargs) -> None: ...
    async def upsert_batch(self, *args, **kwargs) -> None: ...
    async def delete_by_organization(self, *args, **kwargs) -> None: ...
    async def delete_by_knowledge_base(self, *args, **kwargs) -> None: ...
    async def delete_points(self, *args, **kwargs) -> None: ...


class _RecordingLexicalStore:
    def __init__(self, chunks: list[RetrievalChunk] | None = None) -> None:
        self.chunks = chunks or [_chunk(0.7, "lexical")]
        self.calls = 0

    async def search_sparse(self, **kwargs) -> RetrievalContext:
        self.calls += 1
        return RetrievalContext(chunks=list(self.chunks), retrieval_latency_ms=1.0)


class _ServerRrfStore:
    """Devuelve scores RRF (~0.016) como los de Qdrant server-side."""

    def __init__(self) -> None:
        self.calls = 0

    async def search_hybrid(self, **kwargs) -> RetrievalContext:
        self.calls += 1
        return RetrievalContext(
            chunks=[_chunk(1.0 / 61.0, "rrf")], retrieval_latency_ms=1.0
        )


def _query(**overrides) -> RetrievalQuery:
    base = dict(
        query="penalidad",
        organization_id=uuid4(),
        strategy=STRATEGY_HYBRID,
        query_embedding=[0.1, 0.2],
        score_threshold=0.1,
    )
    base.update(overrides)
    return RetrievalQuery(**base)


@pytest.mark.asyncio
async def test_vector_retriever_forwards_workspace_id() -> None:
    from src.rag.retrieval.vector_retriever import VectorRetriever

    store = _RecordingVectorStore()
    workspace_id = uuid4()
    query = _query(strategy=STRATEGY_VECTOR, workspace_id=workspace_id)
    await VectorRetriever(store).retrieve(query)
    assert store.search_kwargs
    assert all(
        kwargs.get("workspace_id") == workspace_id
        for kwargs in store.search_kwargs
    )


@pytest.mark.asyncio
async def test_structured_retriever_forwards_workspace_and_parent_acl() -> None:
    store = _RecordingVectorStore()
    workspace_id = uuid4()
    user_id = uuid4()
    query = _query(
        workspace_id=workspace_id,
        user_id=user_id,
        groups=["legal"],
        strategy=STRATEGY_VECTOR,
    )
    retriever = StructuredRetriever(vector_store=store)
    await retriever.retrieve(query, V2RetrievalOptions(parent_expansion=False))
    assert store.search_kwargs
    assert all(
        kwargs.get("workspace_id") == workspace_id
        for kwargs in store.search_kwargs
    )
    assert all(kwargs.get("user_id") == user_id for kwargs in store.search_kwargs)


@pytest.mark.asyncio
async def test_structured_retriever_parent_fetch_receives_acl() -> None:
    parent_id = uuid4()
    child = RetrievalChunk(
        document_id=uuid4(),
        content="child",
        score=0.9,
        metadata={"parent_id": str(parent_id)},
    )
    store = _RecordingVectorStore(chunks=[child])
    user_id = uuid4()
    query = _query(
        workspace_id=uuid4(),
        user_id=user_id,
        groups=["legal"],
        strategy=STRATEGY_VECTOR,
    )
    retriever = StructuredRetriever(vector_store=store)
    await retriever.retrieve(query, V2RetrievalOptions(parent_expansion=True))
    assert store.get_documents_kwargs
    kwargs = store.get_documents_kwargs[0]
    assert kwargs["role"] == query.role
    assert kwargs["user_id"] == user_id
    assert kwargs["groups"] == ["legal"]


@pytest.mark.asyncio
async def test_server_side_hybrid_falls_back_only_without_lexical() -> None:
    lexical = _RecordingLexicalStore()
    server = _ServerRrfStore()
    retriever = HybridRetriever(
        vector_store=_RecordingVectorStore(),
        lexical_store=lexical,
        hybrid_store=server,
    )
    await retriever.retrieve(_query())
    assert lexical.calls == 1
    assert server.calls == 0  # client-side fusion tiene prioridad


@pytest.mark.asyncio
async def test_server_side_rrf_scores_survive_cosine_threshold() -> None:
    server = _ServerRrfStore()
    retriever = HybridRetriever(
        vector_store=_RecordingVectorStore(),
        lexical_store=None,
        hybrid_store=server,
    )
    result = await retriever.retrieve(_query(score_threshold=0.1))
    assert server.calls == 1
    assert len(result.chunks) == 1  # score RRF 0.016 no debe ser descartado


# ---------------------------------------------------------------------------
# F18 — visibilidad de payload por ACL
# ---------------------------------------------------------------------------

def test_payload_visible_acl_rules() -> None:
    from src.infrastructure.qdrant.vector_store import payload_visible

    user_id = uuid4()
    restricted = {
        "visibility": "admin",
        "acl_users": [],
        "acl_groups": ["legal"],
    }
    assert payload_visible({"visibility": "public"}, role="customer")
    assert payload_visible(restricted, role="admin")
    assert payload_visible(restricted, role="customer", groups=["legal"])
    assert payload_visible(restricted, role="member", user_id=user_id) is False
    assert not payload_visible(restricted, role="viewer")
    assert payload_visible(
        {"visibility": "admin", "acl_users": [str(user_id)]},
        role="viewer",
        user_id=user_id,
    )
    assert not payload_visible(
        {"visibility": "admin", "acl_groups": ["legal"]},
        role="viewer",
        groups=["finanzas"],
    )
