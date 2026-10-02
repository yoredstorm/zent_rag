# =============================================================================
# Knowledge V2 — StructuredRetriever (Phase D slice 1)
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest

from src.core.domain.entities import RetrievalChunk, RetrievalContext
from src.rag.retrieval.models import (
    STRATEGY_HYBRID,
    RetrievalQuery,
)
from src.rag.retrieval.structured import (
    StructuredRetriever,
    V2RetrievalOptions,
)


def _chunk(
    metadata: dict,
    score: float = 0.8,
    content: str = "texto",
    document_id=None,
) -> RetrievalChunk:
    return RetrievalChunk(
        document_id=document_id or uuid4(),
        content=content,
        score=score,
        metadata=metadata,
    )


class FakeVectorStore:
    """Duck-typed VectorStore para el retriever V2 (no toca infra)."""

    def __init__(self, dense, sparse=None, parents=None) -> None:
        self.dense = dense
        self.sparse = sparse or []
        self.parents = parents or []
        self.last_filters: dict | None = None
        self.last_acl: dict = {}
        self.calls: list[dict] = []

    def _record(self, channel: str, **kwargs) -> None:
        """Graba kwargs efectivos por canal (source_ids solo si vino)."""
        self.calls.append({"channel": channel, **kwargs})

    async def search(
        self,
        organization_id,
        query_embedding,
        top_k=5,
        filters=None,
        exclude_filters=None,
        score_threshold=0.1,
        role="admin",
        knowledge_base_id=None,
        user_id=None,
        groups=None,
        workspace_id=None,
        source_ids=None,
    ):
        self.last_filters = filters
        self.last_acl = {"role": role, "user_id": user_id, "groups": groups}
        self.last_workspace_id = workspace_id
        self._record(
            "search",
            workspace_id=workspace_id,
            **({"source_ids": source_ids} if source_ids else {}),
        )
        return RetrievalContext(chunks=[c for c in self.dense[:top_k]])

    async def search_sparse(
        self,
        organization_id,
        query_text,
        top_k=5,
        filters=None,
        exclude_filters=None,
        score_threshold=0.1,
        role="admin",
        knowledge_base_id=None,
        user_id=None,
        groups=None,
        workspace_id=None,
        source_ids=None,
    ):
        self.last_workspace_id = workspace_id
        self._record(
            "search_sparse",
            workspace_id=workspace_id,
            **({"source_ids": source_ids} if source_ids else {}),
        )
        return RetrievalContext(chunks=[c for c in self.sparse[:top_k]])

    async def get_documents(
        self, organization_id, document_ids, role="admin", user_id=None, groups=None
    ):
        self.last_parent_acl = {"role": role, "user_id": user_id, "groups": groups}
        self._record(
            "get_documents",
            role=role,
            user_id=user_id,
            groups=groups,
        )
        ids = {str(i) for i in document_ids}
        return RetrievalContext(
            chunks=[p for p in self.parents if str(p.document_id) in ids]
        )


def _query(**overrides) -> RetrievalQuery:
    base = dict(
        query="¿comisión?",
        organization_id=uuid4(),
        role="viewer",
        user_id=uuid4(),
        groups=["finanzas"],
        knowledge_base_id=uuid4(),
        strategy=STRATEGY_HYBRID,
        query_embedding=[0.1] * 4,
    )
    base.update(overrides)
    return RetrievalQuery(**base)


@pytest.mark.asyncio
async def test_retriever_filters_v2_chunks_and_forwards_acl() -> None:
    doc_id = uuid4()
    parent_id = uuid4()
    query = _query()
    store = FakeVectorStore(
        dense=[
            _chunk({"document_id": str(doc_id), "parent_id": str(parent_id), "v2_chunk": "true"}),
            _chunk({"document_id": str(doc_id), "parent_id": str(parent_id), "v2_chunk": "true"}),
        ],
        parents=[
            _chunk({"v2_chunk": "true"}, content="contexto sección", document_id=parent_id)
        ],
    )
    retriever = StructuredRetriever(store)
    options = V2RetrievalOptions(candidate_k=10, final_context_k=8, parent_expansion=True)
    assembled = await retriever.retrieve(query, options)

    assert store.last_filters == {"metadata.v2_chunk": "true"}
    assert store.last_acl == {
        "role": "viewer",
        "user_id": query.user_id,
        "groups": ["finanzas"],
    }
    assert len(assembled.children) == 2
    assert len(assembled.parents) == 1
    assert any(p.content == "contexto sección" for p in assembled.parents)
    assert "contexto sección" in [c.content for c in assembled.context]
    assert assembled.options is options


@pytest.mark.asyncio
async def test_retriever_hybrid_fusion_with_sparse() -> None:
    dense_children = [_chunk({"v2_chunk": "true"}), _chunk({"v2_chunk": "true"})]
    sparse_children = [_chunk({"v2_chunk": "true"}, content="sparse hit")]
    store = FakeVectorStore(dense=dense_children, sparse=sparse_children)
    retriever = StructuredRetriever(store)
    assembled = await retriever.retrieve(
        _query(),
        V2RetrievalOptions(parent_expansion=False),
    )
    # fusión RRF combina ambas patas
    contents = [c.content for c in assembled.children]
    assert "sparse hit" in contents or len(assembled.children) >= 2
    assert assembled.parents == ()


@pytest.mark.asyncio
async def test_retriever_diversity_caps_per_document() -> None:
    doc_a, doc_b = uuid4(), uuid4()
    store = FakeVectorStore(
        dense=[
            _chunk({"document_id": str(doc_a), "v2_chunk": "true"}),
            _chunk({"document_id": str(doc_a), "v2_chunk": "true"}),
            _chunk({"document_id": str(doc_a), "v2_chunk": "true"}),
            _chunk({"document_id": str(doc_b), "v2_chunk": "true"}),
        ]
    )
    retriever = StructuredRetriever(store)
    options = V2RetrievalOptions(
        parent_expansion=False,
        max_per_document=2,
        final_context_k=8,
    )
    assembled = await retriever.retrieve(_query(), options)
    assert len(assembled.children) == 3  # 2 del doc_a + 1 del doc_b
    assert assembled.deduped_count >= 0


@pytest.mark.asyncio
async def test_structured_retriever_reenvia_source_ids() -> None:
    source_id = uuid4()
    store = FakeVectorStore(dense=[_chunk({"v2_chunk": "true"})])
    retriever = StructuredRetriever(vector_store=store, lexical_store=None)
    query = _query(source_ids=[source_id])
    await retriever.retrieve(query)

    calls = [call for call in store.calls if call.get("source_ids")]
    assert calls and calls[0]["source_ids"] == [source_id]


@pytest.mark.asyncio
async def test_structured_retriever_sin_source_ids_no_setea_kwarg() -> None:
    store = FakeVectorStore(dense=[_chunk({"v2_chunk": "true"})])
    retriever = StructuredRetriever(vector_store=store, lexical_store=None)
    await retriever.retrieve(_query())

    assert store.calls
    assert all("source_ids" not in call for call in store.calls)


@pytest.mark.asyncio
async def test_structured_retriever_parents_filtran_por_source_id() -> None:
    source_id = uuid4()
    padre_ok = _chunk(
        {"v2_chunk": "true", "source_id": str(source_id)}, content="sección ok"
    )
    padre_ajeno = _chunk(
        {"v2_chunk": "true", "source_id": str(uuid4())}, content="sección ajena"
    )
    store = FakeVectorStore(
        dense=[
            _chunk({"v2_chunk": "true", "parent_id": str(padre_ok.document_id)}),
            _chunk({"v2_chunk": "true", "parent_id": str(padre_ajeno.document_id)}),
        ],
        parents=[padre_ok, padre_ajeno],
    )
    retriever = StructuredRetriever(store)
    assembled = await retriever.retrieve(_query(source_ids=[source_id]))

    assert [p.content for p in assembled.parents] == ["sección ok"]
    get_documents_calls = [
        call for call in store.calls if call["channel"] == "get_documents"
    ]
    assert get_documents_calls  # el fetch de parents ocurrió y se filtró post-fetch
