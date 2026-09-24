# =============================================================================
# Retrieval — pin de entidades nombradas en la pregunta
# =============================================================================
# Caso real: «¿qué dice el byte 105 de la categoría 31?» con un corpus donde el
# chunk del byte 105 no aparece en la pata densa. El pin debe traerlo: primero
# por léxico con el label exacto y, si hiciera falta, por barrido de frase.
from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID, uuid4

import pytest

from src.core.domain.entities import RetrievalChunk, RetrievalContext
from src.core.ports import LLMProvider  # noqa: F401  (contrato del módulo)
from src.rag.retrieval.hybrid import HybridRetriever
from src.rag.retrieval.models import (
    STRATEGY_HYBRID,
    STRATEGY_LEXICAL,
    STRATEGY_VECTOR,
    RetrievalQuery,
)

ORG = UUID("11111111-1111-1111-1111-111111111111")


def _chunk(texto: str, score: float, doc: UUID | None = None) -> RetrievalChunk:
    return RetrievalChunk(document_id=doc or uuid4(), content=texto, score=score)


class _StoreFalso:
    """Store mínimo: la densa devuelve ruido y la léxica conoce el chunk real."""

    def __init__(self, *, dense: list[RetrievalChunk], lexical: list[RetrievalChunk], scan: list[RetrievalChunk] | None = None) -> None:
        self._dense = dense
        self._lexical = lexical
        self._scan = scan or []
        self.lexical_queries: list[str] = []
        self.scan_needles: list[list[str]] = []

    @property
    def supports_sparse(self) -> bool:
        return True

    async def search(self, **kwargs) -> RetrievalContext:
        return RetrievalContext(chunks=list(self._dense), retrieval_latency_ms=1.0)

    async def search_sparse(self, *, query_text: str, **kwargs) -> RetrievalContext:
        self.lexical_queries.append(query_text)
        return RetrievalContext(chunks=list(self._lexical), retrieval_latency_ms=1.0)

    async def search_hybrid(self, **kwargs) -> RetrievalContext:
        return RetrievalContext(chunks=list(self._dense), retrieval_latency_ms=1.0)

    async def scan_text(self, *, needles, **kwargs) -> RetrievalContext:
        self.scan_needles.append(list(needles))
        return RetrievalContext(chunks=list(self._scan), retrieval_latency_ms=2.0)


@dataclass
class _VectorStoreFalso:
    chunks: list[RetrievalChunk] = field(default_factory=list)

    async def search(self, **kwargs) -> RetrievalContext:
        return RetrievalContext(chunks=list(self.chunks), retrieval_latency_ms=1.0)


def _retriever(store) -> HybridRetriever:
    return HybridRetriever(
        vector_store=store,
        lexical_store=store if hasattr(store, "search_sparse") else None,
        hybrid_store=store if hasattr(store, "search_hybrid") else None,
    )


def _query(texto: str, strategy: str = STRATEGY_VECTOR, threshold: float = 0.0) -> RetrievalQuery:
    return RetrievalQuery(
        query=texto,
        organization_id=ORG,
        top_k=5,
        effective_top_k=5,
        score_threshold=threshold,
        strategy=strategy,
        query_embedding=[0.1, 0.2],
    )


class TestPinDeEntidades:
    @pytest.mark.asyncio
    async def test_el_chunk_del_byte_105_entra_aunque_la_densa_no_lo_traiga(self) -> None:
        real = _chunk("4.6.2 Fee Application (byte 105)\nValue | Definition\n1 | highest fee", 0.9)
        store = _StoreFalso(
            dense=[_chunk("byte 50 change indicator domestic international", 0.8)],
            lexical=[real],
        )
        contexto = await _retriever(store).retrieve(_query("¿qué dice el byte 105 de la categoría 31?"))

        textos = [c.content for c in contexto.chunks]
        assert any("byte 105" in texto for texto in textos)
        assert store.lexical_queries, "debe consultar la pata léxica con el label"

    @pytest.mark.asyncio
    async def test_la_consulta_lexica_usa_solo_el_label(self) -> None:
        store = _StoreFalso(
            dense=[_chunk("otra cosa", 0.7)],
            lexical=[_chunk("byte 105 = fee application", 0.5)],
        )
        await _retriever(store).retrieve(_query("explicame sobre la categoría 31 y el byte 105"))

        assert store.lexical_queries, "debe consultar por cada entidad nombrada"
        assert set(store.lexical_queries) <= {"categoria 31", "byte 105"}, (
            "sólo los labels: la pregunta completa diluye el token exacto"
        )
        assert all("explicame" not in consulta for consulta in store.lexical_queries)

    @pytest.mark.asyncio
    async def test_escalada_a_barrido_por_frase_cuando_la_lexica_no_alcanza(self) -> None:
        store = _StoreFalso(
            dense=[_chunk("sin la entidad pedida", 0.6)],
            lexical=[],
            scan=[_chunk("Value | Definition\n5 | highest change fee (byte 105)", 0.0)],
        )
        contexto = await _retriever(store).retrieve(_query("¿y el byte 105?"))

        assert store.scan_needles, "debe barrer por frase al no cubrir la entidad"
        assert any("byte 105" in c.content for c in contexto.chunks)

    @pytest.mark.asyncio
    async def test_el_pin_sobrevive_al_umbral(self) -> None:
        real = _chunk("byte 105 fee application", 0.9)
        store = _StoreFalso(dense=[_chunk("ruido", 0.35)], lexical=[real])
        contexto = await _retriever(store).retrieve(_query("byte 105", threshold=0.3))

        assert any("byte 105" in c.content for c in contexto.chunks)

    @pytest.mark.asyncio
    async def test_sin_entidades_no_hay_pin(self) -> None:
        store = _StoreFalso(dense=[_chunk("texto general", 0.5)], lexical=[_chunk("otro", 0.4)])
        context = await _retriever(store).retrieve(_query("¿cómo funciona la reemisión?"))

        assert store.lexical_queries == [], "sin entidad nombrada no hay etapa léxica"
        assert store.scan_needles == []
        assert len(context.chunks) == 1

    @pytest.mark.asyncio
    async def test_flag_off_reproduce_el_comportamiento_previo(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.core.config import get_settings

        monkeypatch.setattr(get_settings(), "RAG_RETRIEVAL_ENTITY_PIN", "off")
        store = _StoreFalso(
            dense=[_chunk("byte 50", 0.8)],
            lexical=[_chunk("byte 105 fee application", 0.9)],
        )
        contexto = await _retriever(store).retrieve(_query("¿qué dice el byte 105?"))

        assert store.lexical_queries == []
        assert not any("byte 105" in c.content for c in contexto.chunks)

    @pytest.mark.asyncio
    async def test_sin_store_de_barrido_no_rompe(self) -> None:
        store = _VectorStoreFalso(chunks=[_chunk("solo densa", 0.5)])
        contexto = await _retriever(store).retrieve(_query("¿qué dice el byte 105?"))

        assert any("solo densa" in c.content for c in contexto.chunks)

    @pytest.mark.asyncio
    async def test_la_estrategia_hybrid_tambien_pinea(self) -> None:
        real = _chunk("byte 105 fee application", 0.9)
        store = _StoreFalso(dense=[_chunk("ruido semántico", 0.7)], lexical=[real])
        contexto = await _retriever(store).retrieve(
            _query("¿qué dice el byte 105?", strategy=STRATEGY_HYBRID)
        )

        assert any("byte 105" in c.content for c in contexto.chunks)

    @pytest.mark.asyncio
    async def test_estrategia_lexical_no_se_duplica_el_pin(self) -> None:
        real = _chunk("byte 105 fee application", 0.9)
        store = _StoreFalso(dense=[], lexical=[real])
        contexto = await _retriever(store).retrieve(
            _query("¿qué dice el byte 105?", strategy=STRATEGY_LEXICAL)
        )

        docs = [c.document_id for c in contexto.chunks]
        assert docs.count(real.document_id) == 1, "el chunk pineado no se duplica"
