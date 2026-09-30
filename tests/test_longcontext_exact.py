# =============================================================================
# Long-Context Fase 0 — normalización triple, tokens exactos y MUST_KEEP
# =============================================================================
# TEST 1: `&&&F` sobrevive intacto a la extracción exacta y a la pata exacta.
# TEST 2: normalize_query no destruye anchors técnicos.
# TEST 3: un exact anchor match sobrevive umbral, reranking y presupuesto.
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from src.core.domain.entities import RetrievalChunk, RetrievalContext
from src.rag.longcontext.exact_tokens import (
    exact_needles_for_query,
    extract_exact_tokens,
)
from src.rag.longcontext.must_keep import is_must_keep
from src.rag.longcontext.normalize import (
    normalize_for_exact_search,
    normalize_for_lexical_search,
)
from src.rag.retrieval.builders import ContextBuilder
from src.rag.retrieval.classify import normalize_query
from src.rag.retrieval.hybrid import HybridRetriever
from src.rag.retrieval.models import RetrievalQuery

ORG = UUID("11111111-1111-1111-1111-111111111111")

QUESTION = "consulta si FCLAS &&&F acepta QNNF0SME"


def _chunk(texto: str, score: float) -> RetrievalChunk:
    return RetrievalChunk(document_id=uuid4(), content=texto, score=score)


class _StoreExacto:
    """Store mínimo: densa con ruido, léxica vacía, scan literal con la máscara."""

    def __init__(
        self,
        *,
        dense: list[RetrievalChunk] | None = None,
        exact: list[RetrievalChunk] | None = None,
    ) -> None:
        self._dense = dense or []
        self._exact = exact or []
        self.literal_needles: list[list[str]] = []

    async def search(self, **kwargs) -> RetrievalContext:
        return RetrievalContext(chunks=list(self._dense), retrieval_latency_ms=1.0)

    async def search_sparse(self, **kwargs) -> RetrievalContext:
        return RetrievalContext(chunks=[], retrieval_latency_ms=1.0)

    async def scan_text_literal(self, *, needles, limit=5, **kwargs) -> RetrievalContext:
        """Semántica del store real: ANY needle + limit + orden de scroll."""
        self.literal_needles.append(list(needles))
        agujas = [str(needle).lower() for needle in needles if str(needle or "").strip()]
        encontrados = [
            chunk
            for chunk in self._scan_corpus()
            if any(aguja in (chunk.content or "").lower() for aguja in agujas)
        ]
        return RetrievalContext(
            chunks=encontrados[: max(1, int(limit))], retrieval_latency_ms=2.0
        )

    def _scan_corpus(self) -> list[RetrievalChunk]:
        return list(self._exact)


class _RerankerQueOlvida:
    """Reranker hostil: devuelve sólo el ruido denso."""

    async def rerank(self, query, chunks, top_n=20, organization_id="") -> list:
        return [chunk for chunk in chunks if not is_must_keep(chunk)][:top_n]


def _query(**overrides) -> RetrievalQuery:
    params = {
        "query": QUESTION,
        "organization_id": ORG,
        "top_k": 5,
        "effective_top_k": 5,
        "score_threshold": 0.5,
        "strategy": "hybrid",
        "query_embedding": [0.1, 0.2],
    }
    params.update(overrides)
    return RetrievalQuery(**params)


class TestExactTokens:
    def test_mask_survives_extraction(self) -> None:
        tokens = extract_exact_tokens(QUESTION)
        values = {token.value for token in tokens}
        assert "&&&F" in values
        assert "FCLAS" in values
        assert "QNNF0SME" in values

    def test_mask_survives_needles(self) -> None:
        needles = exact_needles_for_query(QUESTION)
        assert "&&&F" in needles
        assert "FCLAS" in needles
        assert "QNNF0SME" in needles

    def test_html_entities_unescaped(self) -> None:
        needles = exact_needles_for_query("máscara &amp;&amp;&amp;F")
        assert "&&&F" in needles


class TestNormalizeTriple:
    def test_normalize_query_keeps_technical_symbols(self) -> None:
        assert normalize_query("FCLAS &&&F") == "fclas &&&f"

    def test_normalize_for_exact_search_is_faithful(self) -> None:
        assert normalize_for_exact_search("FCLAS &&&F") == "FCLAS &&&F"

    def test_lexical_removes_prose_punctuation_only(self) -> None:
        assert normalize_for_lexical_search("¿Qué es FCLAS?") == "que es fclas"

    def test_old_behavior_would_have_destroyed_mask(self) -> None:
        # La normalización vieja (`[^a-z0-9\s]+`) reducía `&&&F` a `f`.
        assert "&&&" in normalize_query("&&&F")
        assert "&&&" in normalize_for_lexical_search("&&&F")


class TestExactLeg:
    @pytest.mark.asyncio
    async def test_exact_match_survives_threshold(self) -> None:
        ruido = _chunk("texto denso sin la mascara", 0.9)
        exacto = _chunk("El patrón &&&F acepta sólo las clases indicadas.", 0.0)
        store = _StoreExacto(dense=[ruido], exact=[exacto])
        retriever = HybridRetriever(vector_store=store)

        ctx = await retriever.retrieve(_query())

        ids = {chunk.document_id for chunk in ctx.chunks}
        assert exacto.document_id in ids
        assert any("&&&F" in needle for needle in store.literal_needles[0])
        keep = next(chunk for chunk in ctx.chunks if chunk.document_id == exacto.document_id)
        assert is_must_keep(keep)
        assert keep.metadata.get("exact_needle") == "&&&F"

    @pytest.mark.asyncio
    async def test_must_keep_survives_reranker(self) -> None:
        ruido = _chunk("texto denso sin la mascara", 0.9)
        exacto = _chunk("El patrón &&&F acepta sólo las clases indicadas.", 0.0)
        store = _StoreExacto(dense=[ruido], exact=[exacto])
        retriever = HybridRetriever(
            vector_store=store,
            reranker=_RerankerQueOlvida(),
        )

        ctx = await retriever.retrieve(_query())

        assert ctx.chunks[0].document_id == exacto.document_id
        assert is_must_keep(ctx.chunks[0])

    @pytest.mark.asyncio
    async def test_exact_search_off_disables_leg(self) -> None:
        ruido = _chunk("texto denso", 0.9)
        store = _StoreExacto(dense=[ruido], exact=[_chunk("&&&F", 0.0)])
        retriever = HybridRetriever(vector_store=store)

        ctx = await retriever.retrieve(_query(exact_search=False))

        assert store.literal_needles == []
        assert [c.content for c in ctx.chunks] == ["texto denso"]

    @pytest.mark.asyncio
    async def test_caller_needles_win_over_rewritten_query(self) -> None:
        store = _StoreExacto(dense=[], exact=[_chunk("mascara &&&F", 0.0)])
        retriever = HybridRetriever(vector_store=store)

        ctx = await retriever.retrieve(
            _query(query="consulta reescrita sin simbolos", exact_needles=["&&&F"])
        )

        assert ctx.chunks and is_must_keep(ctx.chunks[0])
        assert any("&&&F" in needle for needle in store.literal_needles[0])


class TestBudgetMustKeep:
    def test_must_keep_wins_over_score_in_budget(self) -> None:
        exacto = RetrievalChunk(
            document_id=uuid4(),
            content="x" * 500,
            score=0.0,
            metadata={"must_keep": "true"},
        )
        alto_score = _chunk("y" * 500, 0.99)
        builder = ContextBuilder(max_context_tokens=100)  # 400 chars de presupuesto

        out = builder.fit_budget([alto_score, exacto])

        assert out == [exacto]

    def test_budget_override_from_request(self) -> None:
        a = _chunk("x" * 100, 0.9)
        b = _chunk("y" * 900, 0.8)
        builder = ContextBuilder(max_context_tokens=250)

        out = builder.fit_budget([a, b], max_context_tokens=25)  # 100 chars

        assert out == [a]
