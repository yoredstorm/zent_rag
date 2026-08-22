# =============================================================================
# HybridRetriever — pipeline completo: clasificar, fusionar, deduplicar,
# rerankear, filtrar por umbral y recortar al presupuesto de contexto.
# =============================================================================
from __future__ import annotations

import asyncio
import time

from src.core.domain.entities import RetrievalContext
from src.core.ports import HybridStore, LexicalStore, VectorStore
from src.infrastructure.observability.logging_config import get_logger
from src.rag.reranking.base import Reranker
from src.rag.retrieval.base import Retriever
from src.rag.retrieval.builders import ContextBuilder
from src.rag.retrieval.classify import classify_query, normalize_query
from src.rag.retrieval.fusion import (
    apply_doc_type_priority,
    dedupe_chunks,
    filter_by_threshold,
    rrf_fusion,
    weighted_fusion,
)
from src.rag.retrieval.lexical_retriever import LexicalRetriever
from src.rag.retrieval.models import (
    FUSION_RRF,
    STRATEGY_HYBRID,
    STRATEGY_LEXICAL,
    STRATEGY_VECTOR,
    RetrievalQuery,
)
from src.rag.retrieval.vector_retriever import VectorRetriever

logger = get_logger(__name__)


class HybridRetriever(Retriever):
    """Motor de retrieval por tenant. Sin acoplamiento a negocio vertical.

    Rutas:
      - vector:  VectorRetriever (comportamiento histórico, aggregated first).
      - lexical: LexicalRetriever (BM25).
      - hybrid:  fusión server-side (HybridStore) o client-side (dos patas
                 en paralelo + RRF/weighted), luego rerank + threshold +
                 budget de contexto.
    """

    def __init__(
        self,
        vector_store: VectorStore,
        lexical_store: LexicalStore | None = None,
        hybrid_store: HybridStore | None = None,
        reranker: Reranker | None = None,
        context_builder: ContextBuilder | None = None,
    ) -> None:
        self._vector = VectorRetriever(vector_store)
        self._lexical = (
            LexicalRetriever(lexical_store) if lexical_store is not None else None
        )
        self._hybrid_store = hybrid_store
        self._reranker = reranker
        self._builder = context_builder or ContextBuilder(max_context_tokens=32000)

    async def retrieve(self, query: RetrievalQuery) -> RetrievalContext:
        start = time.perf_counter()
        classification = classify_query(query.query)
        normalized = normalize_query(query.query)

        context: RetrievalContext
        if query.strategy == STRATEGY_HYBRID:
            context = await self._retrieve_hybrid(query, normalized, classification)
        elif query.strategy == STRATEGY_LEXICAL:
            context = await self._retrieve_lexical(query, normalized)
        elif query.strategy == STRATEGY_VECTOR:
            context = await self._vector.retrieve(query)
        else:
            raise ValueError(f"Unknown retrieval strategy: {query.strategy}")

        chunks = dedupe_chunks(context.chunks)
        chunks = apply_doc_type_priority(chunks, query.doc_type_priority)
        chunks = filter_by_threshold(chunks, query.score_threshold)

        if self._reranker is not None and chunks:
            try:
                chunks = await self._reranker.rerank(
                    query=query.query,
                    chunks=chunks,
                    top_n=query.rerank_top_k,
                    organization_id=str(query.organization_id),
                )
            except Exception as exc:
                logger.warning(
                    "Rerank failed, using retrieval order",
                    error=str(exc),
                    organization_id=str(query.organization_id),
                )

        chunks = self._builder.fit_budget(chunks)
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "Hybrid retrieval completed",
            strategy=query.strategy,
            classification=classification.kind,
            results_count=len(chunks),
            retrieval_latency_ms=round(elapsed_ms, 2),
            organization_id=str(query.organization_id),
        )
        return RetrievalContext(
            chunks=chunks,
            query_embedding=query.query_embedding,
            retrieval_latency_ms=context.retrieval_latency_ms,
        )

    async def _retrieve_lexical(
        self, query: RetrievalQuery, normalized: str
    ) -> RetrievalContext:
        if self._lexical is None:
            raise ValueError("Lexical strategy requires a LexicalStore")
        return await self._lexical.retrieve(query)

    async def _retrieve_hybrid(
        self,
        query: RetrievalQuery,
        normalized: str,
        classification,
    ) -> RetrievalContext:
        # Server-side fusion (un solo round-trip) si el adaptador lo soporta.
        if self._hybrid_store is not None and query.query_embedding is not None:
            return await self._hybrid_store.search_hybrid(
                organization_id=query.organization_id,
                query_text=normalized,
                query_embedding=query.query_embedding,
                top_k=query.top_k,
                filters=query.filters or None,
                exclude_filters=query.exclude_filters or None,
                score_threshold=query.score_threshold,
                role=query.role,
                knowledge_base_id=query.knowledge_base_id,
                fusion_weights={
                    "dense": 1.0 - classification.lexical_ratio,
                    "sparse": classification.lexical_ratio,
                },
            )

        # Fallback client-side: ambas patas en paralelo + fusión local.
        if self._lexical is None:
            return await self._vector.retrieve(query)

        vector_task = asyncio.ensure_future(self._vector.retrieve(query))
        lexical_task = asyncio.ensure_future(self._lexical.retrieve(query))
        vector_ctx, lexical_ctx = await asyncio.gather(vector_task, lexical_task)

        if query.fusion == FUSION_RRF:
            fused = rrf_fusion([vector_ctx.chunks, lexical_ctx.chunks], k=query.rrf_k)
        else:
            fused = weighted_fusion(
                [vector_ctx.chunks, lexical_ctx.chunks],
                weights=[1.0 - query.lexical_weight, query.lexical_weight],
            )
        return RetrievalContext(
            chunks=fused,
            query_embedding=query.query_embedding,
            retrieval_latency_ms=vector_ctx.retrieval_latency_ms
            + lexical_ctx.retrieval_latency_ms,
        )
