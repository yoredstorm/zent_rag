# =============================================================================
# Retrieval Engine — tests unitarios del dominio puro (sin infraestructura)
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from src.core.domain.entities import RetrievalChunk, RetrievalContext
from src.core.ports import LexicalStore, VectorStore
from src.rag.retrieval import (
    HybridRetriever,
    classify_query,
    detect_language,
    normalize_query,
    resolve_retrieval_config,
)
from src.rag.retrieval.builders import ContextBuilder
from src.rag.retrieval.fusion import (
    apply_doc_type_priority,
    dedupe_chunks,
    filter_by_threshold,
    rrf_fusion,
    weighted_fusion,
)
from src.rag.retrieval.models import RetrievalQuery


def _chunk(doc_id: UUID, content: str, score: float, doc_type: str | None = None) -> RetrievalChunk:
    metadata = {"doc_type": doc_type} if doc_type else {}
    return RetrievalChunk(document_id=doc_id, content=content, score=score, metadata=metadata)


# -----------------------------------------------------------------------------
# Normalización / clasificación / idioma
# -----------------------------------------------------------------------------
class TestNormalizeAndClassify:
    def test_normalize_strips_accents_and_punctuation(self) -> None:
        assert normalize_query("¿Cuál es el precio del Paracetamol 500mg?") == (
            "cual es el precio del paracetamol 500mg"
        )

    def test_detect_language_spanish(self) -> None:
        assert detect_language("¿Cuál es el precio del paracetamol?") == "es"

    def test_detect_language_english(self) -> None:
        assert detect_language("What is the price of paracetamol?") == "en"

    def test_detect_language_none_for_short(self) -> None:
        assert detect_language("paracetamol") is None

    def test_classify_code_query_lexical(self) -> None:
        c = classify_query("SKU-1234 precio")
        assert c.kind in ("lexical", "mixed")
        assert c.lexical_ratio >= 0.4

    def test_classify_natural_language_semantic(self) -> None:
        c = classify_query("¿Cuál es la política de devoluciones de la tienda?")
        assert c.kind == "semantic"


# -----------------------------------------------------------------------------
# Fusión
# -----------------------------------------------------------------------------
class TestFusion:
    def test_dedupe_keeps_first(self) -> None:
        doc = uuid4()
        chunks = [_chunk(doc, "a", 0.9), _chunk(doc, "b", 0.8), _chunk(uuid4(), "c", 0.7)]
        out = dedupe_chunks(chunks)
        assert len(out) == 2
        assert out[0].content == "a"

    def test_rrf_shared_doc_ranks_first_and_scores_preserved(self) -> None:
        shared = uuid4()
        only_a = uuid4()
        only_b = uuid4()
        leg_a = [_chunk(shared, "shared", 0.95), _chunk(only_a, "only-a", 0.90)]
        leg_b = [_chunk(shared, "shared", 0.50), _chunk(only_b, "only-b", 0.40)]
        fused = rrf_fusion([leg_a, leg_b], k=60)
        assert fused[0].document_id == shared
        # score original intacto (el de la primera pata)
        assert fused[0].score == 0.95
        assert {c.document_id for c in fused} == {shared, only_a, only_b}

    def test_weighted_fusion_normalizes_per_leg(self) -> None:
        a = _chunk(uuid4(), "a", 0.9)
        b = _chunk(uuid4(), "b", 0.8)
        c = _chunk(uuid4(), "c", 5.0)  # rango distinto (sparse dot-product)
        d = _chunk(uuid4(), "d", 4.0)
        fused = weighted_fusion([[a, b], [c, d]], weights=[0.5, 0.5])
        ids = [ch.document_id for ch in fused]
        assert ids[0] in (a.document_id, c.document_id)
        assert len(ids) == 4

    def test_weighted_fusion_mismatched_weights_raises(self) -> None:
        with pytest.raises(ValueError):
            weighted_fusion([[[]]], weights=[0.5, 0.5])

    def test_doc_type_priority_aggregated_first_stable(self) -> None:
        a = _chunk(uuid4(), "agg1", 0.9, doc_type="aggregated")
        b = _chunk(uuid4(), "ind1", 0.95, doc_type="individual")
        c = _chunk(uuid4(), "agg2", 0.8, doc_type="aggregated")
        out = apply_doc_type_priority([b, a, c], ["aggregated"])
        assert [ch.content for ch in out] == ["agg1", "agg2", "ind1"]

    def test_filter_by_threshold(self) -> None:
        chunks = [_chunk(uuid4(), "high", 0.5), _chunk(uuid4(), "low", 0.05)]
        out = filter_by_threshold(chunks, 0.1)
        assert [c.content for c in out] == ["high"]


# -----------------------------------------------------------------------------
# ContextBuilder
# -----------------------------------------------------------------------------
class TestContextBuilder:
    def test_fit_budget_keeps_order_and_respects_budget(self) -> None:
        chunks = [
            _chunk(uuid4(), "x" * 100, 0.9),
            _chunk(uuid4(), "y" * 900, 0.85),
            _chunk(uuid4(), "z" * 100, 0.8),
        ]
        builder = ContextBuilder(max_context_tokens=250)  # ~1000 chars
        out = builder.fit_budget(chunks)
        assert [c.content for c in out] == [chunks[0].content, chunks[1].content]


# -----------------------------------------------------------------------------
# Config por tenant
# -----------------------------------------------------------------------------
class TestResolveConfig:
    def test_defaults_from_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.core.config import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "RAG_RETRIEVAL_STRATEGY", "vector")
        monkeypatch.setattr(settings, "RAG_TOP_K", 200)
        monkeypatch.setattr(settings, "RAG_RERANKER", "")
        cfg = resolve_retrieval_config()
        assert cfg.strategy == "vector"
        assert cfg.top_k == 200

    def test_org_overrides(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.core.config import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "RAG_RETRIEVAL_STRATEGY", "vector")
        cfg = resolve_retrieval_config(
            organization_config={"retrieval": {"strategy": "hybrid", "rrf_k": 120}}
        )
        assert cfg.strategy == "hybrid"
        assert cfg.rrf_k == 120

    def test_request_wins_over_org(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.core.config import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "RAG_RETRIEVAL_STRATEGY", "vector")
        cfg = resolve_retrieval_config(
            request_overrides={"strategy": "lexical"},
            organization_config={"retrieval": {"strategy": "hybrid"}},
        )
        assert cfg.strategy == "lexical"

    def test_invalid_values_fall_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.core.config import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "RAG_RETRIEVAL_STRATEGY", "bogus")
        cfg = resolve_retrieval_config()
        assert cfg.strategy == "vector"

    def test_unknown_keys_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.core.config import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "RAG_RETRIEVAL_STRATEGY", "vector")
        cfg = resolve_retrieval_config(
            organization_config={"retrieval": {"business_rule": "farmacia", "top_k": 50}}
        )
        assert cfg.top_k == 50

    def test_doc_type_priority_from_org(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.core.config import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "RAG_RETRIEVAL_STRATEGY", "vector")
        cfg = resolve_retrieval_config(
            organization_config={"retrieval": {"doc_type_priority": ["manual", "aggregated"]}}
        )
        assert cfg.doc_type_priority == ["manual", "aggregated"]

    def test_rerank_top_k_capped_to_top_k(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.core.config import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "RAG_RETRIEVAL_STRATEGY", "vector")
        cfg = resolve_retrieval_config(
            organization_config={"retrieval": {"top_k": 10, "rerank_top_k": 50}}
        )
        assert cfg.rerank_top_k == 10


# -----------------------------------------------------------------------------
# HybridRetriever (fakes en memoria)
# -----------------------------------------------------------------------------
class FakeVectorStore(VectorStore):
    def __init__(self, results: dict[tuple, list[RetrievalChunk]]) -> None:
        self._results = results
        self.calls: list[dict] = []

    async def search(
        self,
        organization_id: UUID,
        query_embedding: list[float],
        top_k: int = 5,
        filters: dict[str, str] | None = None,
        exclude_filters: dict[str, str] | None = None,
        score_threshold: float = 0.1,
        role: str = "admin",
        knowledge_base_id: UUID | None = None,
    ) -> RetrievalContext:
        self.calls.append(
            {"top_k": top_k, "filters": filters, "exclude": exclude_filters}
        )
        chunks = self._results.get(("vector",), [])
        return RetrievalContext(
            chunks=[c for c in chunks if c.score >= score_threshold],
            query_embedding=query_embedding,
            retrieval_latency_ms=1.0,
        )

    async def upsert(self, *args, **kwargs) -> None: ...
    async def upsert_batch(self, *args, **kwargs) -> None: ...
    async def delete_by_organization(self, organization_id: UUID) -> None: ...
    async def delete_by_knowledge_base(self, organization_id: UUID, knowledge_base_id: UUID) -> None: ...
    async def delete_points(self, organization_id: UUID, point_ids: list[str]) -> None: ...
    async def get_documents(
        self,
        organization_id: UUID,
        document_ids: list[UUID],
        role: str = "admin",
    ) -> RetrievalContext:
        return RetrievalContext(chunks=[], retrieval_latency_ms=0.0)


class FakeLexicalStore(LexicalStore):
    def __init__(self, results: dict[tuple, list[RetrievalChunk]]) -> None:
        self._results = results

    async def search_sparse(
        self,
        organization_id: UUID,
        query_text: str,
        top_k: int = 5,
        filters: dict[str, str] | None = None,
        exclude_filters: dict[str, str] | None = None,
        score_threshold: float = 0.1,
        role: str = "admin",
        knowledge_base_id: UUID | None = None,
    ) -> RetrievalContext:
        chunks = self._results.get(("sparse",), [])
        return RetrievalContext(
            chunks=[c for c in chunks if c.score >= score_threshold],
            retrieval_latency_ms=1.0,
        )


class TestHybridRetriever:
    def _query(self, strategy: str = "hybrid", **overrides) -> RetrievalQuery:
        params = {
            "query": "paracetamol 500mg",
            "organization_id": uuid4(),
            "query_embedding": [0.1, 0.2],
            "strategy": strategy,
            "score_threshold": 0.0,
        }
        params.update(overrides)
        return RetrievalQuery(**params)

    @pytest.mark.asyncio
    async def test_hybrid_fuses_both_legs(self) -> None:
        shared = uuid4()
        vec_only = uuid4()
        lex_only = uuid4()
        vector = FakeVectorStore(
            {("vector",): [
                _chunk(shared, "shared", 0.95),
                _chunk(vec_only, "vector-only", 0.90),
            ]}
        )
        lexical = FakeLexicalStore(
            {("sparse",): [
                _chunk(shared, "shared", 3.0),
                _chunk(lex_only, "lexical-only", 2.0),
            ]}
        )
        retriever = HybridRetriever(vector_store=vector, lexical_store=lexical)
        ctx = await retriever.retrieve(self._query())
        ids = {c.document_id for c in ctx.chunks}
        assert ids == {shared, vec_only, lex_only}
        assert ctx.chunks[0].document_id == shared  # RRF: aparece en ambas

    @pytest.mark.asyncio
    async def test_vector_strategy_uses_only_vector_leg(self) -> None:
        vector = FakeVectorStore(
            {("vector",): [_chunk(uuid4(), "only-vector", 0.9)]}
        )
        lexical = FakeLexicalStore(
            {("sparse",): [_chunk(uuid4(), "never", 2.0)]}
        )
        retriever = HybridRetriever(vector_store=vector, lexical_store=lexical)
        ctx = await retriever.retrieve(self._query(strategy="vector"))
        assert [c.content for c in ctx.chunks] == ["only-vector"]

    @pytest.mark.asyncio
    async def test_lexical_strategy_uses_only_lexical_leg(self) -> None:
        vector = FakeVectorStore(
            {("vector",): [_chunk(uuid4(), "never", 0.9)]}
        )
        lexical = FakeLexicalStore(
            {("sparse",): [_chunk(uuid4(), "only-lexical", 2.0)]}
        )
        retriever = HybridRetriever(vector_store=vector, lexical_store=lexical)
        ctx = await retriever.retrieve(self._query(strategy="lexical"))
        assert [c.content for c in ctx.chunks] == ["only-lexical"]

    @pytest.mark.asyncio
    async def test_unknown_strategy_raises(self) -> None:
        vector = FakeVectorStore({})
        retriever = HybridRetriever(vector_store=vector)
        with pytest.raises(ValueError):
            await retriever.retrieve(self._query(strategy="bogus"))

    @pytest.mark.asyncio
    async def test_score_threshold_filters_after_fusion(self) -> None:
        vector = FakeVectorStore(
            {("vector",): [_chunk(uuid4(), "high", 0.9), _chunk(uuid4(), "low", 0.02)]}
        )
        lexical = FakeLexicalStore({})
        retriever = HybridRetriever(vector_store=vector, lexical_store=lexical)
        ctx = await retriever.retrieve(self._query(score_threshold=0.1))
        assert [c.content for c in ctx.chunks] == ["high"]

    @pytest.mark.asyncio
    async def test_doc_type_priority_applied_in_hybrid(self) -> None:
        vector = FakeVectorStore(
            {("vector",): [
                _chunk(uuid4(), "ind", 0.95, doc_type="individual"),
                _chunk(uuid4(), "agg", 0.9, doc_type="aggregated"),
            ]}
        )
        lexical = FakeLexicalStore({})
        retriever = HybridRetriever(vector_store=vector, lexical_store=lexical)
        ctx = await retriever.retrieve(self._query(strategy="vector"))
        assert ctx.chunks[0].content == "agg"
