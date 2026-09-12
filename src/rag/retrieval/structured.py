# =============================================================================
# Knowledge V2 — StructuredRetriever (Phase D slice 1)
# =============================================================================
# Retrieval sobre los chunks V2 (v2_chunk=true) con el MISMO contrato ACL
# pre-LLM: dense + sparse opcional + fusión RRF + rerank + parent expansion
# (contexto de sección) + dedupe + diversidad + token budget → AssembledContext.
#
# Inerte: no está conectado al orchestrator (eso es Phase F). Los fallos
# degradan a retrieval V1 sin romper el flujo productivo.
# =============================================================================
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, replace
from uuid import UUID

from src.core.domain.entities import RetrievalChunk
from src.core.ports import HybridStore, LexicalStore, VectorStore
from src.infrastructure.observability.logging_config import get_logger
from src.rag.reranking.base import Reranker
from src.rag.retrieval.builders import ContextBuilder
from src.rag.retrieval.fusion import (
    dedupe_chunks,
    filter_by_threshold,
    rrf_fusion,
)
from src.rag.retrieval.models import (
    FUSION_RRF,
    STRATEGY_HYBRID,
    STRATEGY_VECTOR,
    RetrievalQuery,
)

logger = get_logger(__name__)

V2_CHUNK_FILTER_KEY = "metadata.v2_chunk"
V2_CHUNK_FILTER = {V2_CHUNK_FILTER_KEY: "true"}


@dataclass(frozen=True, kw_only=True)
class V2RetrievalOptions:
    """Presupuestos del pipeline V2 (brief §13)."""

    candidate_k: int = 40
    rerank_k: int = 12
    final_context_k: int = 8
    parent_expansion: bool = True
    max_context_tokens: int = 8000
    source_diversity: bool = True
    max_per_document: int = 4


@dataclass(frozen=True, kw_only=True)
class AssembledContext:
    """Contexto ensamblado (no una concatenación arbitraria)."""

    children: tuple[RetrievalChunk, ...]
    parents: tuple[RetrievalChunk, ...]
    context: tuple[RetrievalChunk, ...]
    options: V2RetrievalOptions
    retrieval_latency_ms: float = 0.0
    deduped_count: int = 0

    @property
    def total_chars(self) -> int:
        return sum(len(c.content) for c in self.context)


class StructuredRetriever:
    """Retrieval V2 reutilizando dense+sparse+fusion+rerank del motor V1."""

    def __init__(
        self,
        vector_store: VectorStore,
        *,
        lexical_store: LexicalStore | None = None,
        hybrid_store: HybridStore | None = None,
        reranker: Reranker | None = None,
        context_builder: ContextBuilder | None = None,
    ) -> None:
        self._vector = vector_store
        self._lexical = lexical_store
        self._hybrid = hybrid_store
        self._reranker = reranker
        self._builder = context_builder or ContextBuilder(
            max_context_tokens=8000
        )

    async def retrieve(
        self,
        query: RetrievalQuery,
        options: V2RetrievalOptions | None = None,
    ) -> AssembledContext:
        start = time.perf_counter()
        options = options or V2RetrievalOptions()
        v2_query = replace(
            query,
            filters={**query.filters, **V2_CHUNK_FILTER},
            top_k=options.candidate_k,
            rerank_top_k=options.rerank_k,
        )
        strategy = query.strategy
        if strategy not in (STRATEGY_HYBRID, STRATEGY_VECTOR):
            strategy = STRATEGY_HYBRID if self._lexical is not None else STRATEGY_VECTOR
            v2_query = replace(v2_query, strategy=strategy)

        children = await self._candidates(v2_query, options)
        before_dedupe = len(children)
        children = dedupe_chunks(children)
        children = filter_by_threshold(children, v2_query.score_threshold)
        if options.source_diversity:
            children = self._diversify(children, options)

        if self._reranker is not None and children:
            try:
                children = await self._reranker.rerank(
                    query=query.query,
                    chunks=children,
                    top_n=options.rerank_k,
                    organization_id=str(query.organization_id),
                )
            except Exception as exc:
                logger.warning(
                    "V2 rerank failed, using retrieval order",
                    error=str(exc),
                    organization_id=str(query.organization_id),
                )

        parents: tuple[RetrievalChunk, ...] = ()
        if options.parent_expansion:
            parents = tuple(
                await self._expand_parents(query, children)
            )

        combined = list(children) + list(parents)
        bounded = self._builder.fit_budget(combined)
        context = tuple(bounded[: options.final_context_k])

        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "V2 structured retrieval completed",
            strategy=strategy,
            candidates=before_dedupe,
            deduped=len(children),
            parents=len(parents),
            context=len(context),
            retrieval_latency_ms=round(elapsed_ms, 2),
            organization_id=str(query.organization_id),
        )
        return AssembledContext(
            children=tuple(children),
            parents=parents,
            context=context,
            options=options,
            retrieval_latency_ms=elapsed_ms,
            deduped_count=before_dedupe - len(children),
        )

    # ------------------------------------------------------------------
    # Candidatos (dense + sparse + fusión), ACL pre-LLM siempre presente
    # ------------------------------------------------------------------
    async def _candidates(
        self, query: RetrievalQuery, options: V2RetrievalOptions
    ) -> list[RetrievalChunk]:
        if self._hybrid is not None and query.query_embedding is not None:
            ctx = await self._hybrid.search_hybrid(
                organization_id=query.organization_id,
                query_text=query.query,
                query_embedding=query.query_embedding,
                top_k=options.candidate_k,
                filters=query.filters or None,
                exclude_filters=query.exclude_filters or None,
                score_threshold=query.score_threshold,
                role=query.role,
                user_id=query.user_id,
                groups=query.groups,
                knowledge_base_id=query.knowledge_base_id,
            )
            return ctx.chunks

        if query.query_embedding is None:
            raise ValueError("StructuredRetriever requires query_embedding")

        dense_task = asyncio.ensure_future(
            self._vector.search(
                organization_id=query.organization_id,
                query_embedding=query.query_embedding,
                top_k=options.candidate_k,
                filters=query.filters or None,
                exclude_filters=query.exclude_filters or None,
                score_threshold=query.score_threshold,
                role=query.role,
                user_id=query.user_id,
                groups=query.groups,
                knowledge_base_id=query.knowledge_base_id,
            )
        )
        if self._lexical is not None and query.query:
            lexical_task = asyncio.ensure_future(
                self._lexical.search_sparse(
                    organization_id=query.organization_id,
                    query_text=query.query,
                    top_k=options.candidate_k,
                    filters=query.filters or None,
                    exclude_filters=query.exclude_filters or None,
                    score_threshold=query.score_threshold,
                    role=query.role,
                    user_id=query.user_id,
                    groups=query.groups,
                    knowledge_base_id=query.knowledge_base_id,
                )
            )
            dense_ctx, lexical_ctx = await asyncio.gather(dense_task, lexical_task)
            if query.fusion == FUSION_RRF:
                return rrf_fusion(
                    [dense_ctx.chunks, lexical_ctx.chunks],
                    k=query.rrf_k,
                )
            return dedupe_chunks(list(dense_ctx.chunks) + lexical_ctx.chunks)

        dense_ctx = await dense_task
        return dense_ctx.chunks

    # ------------------------------------------------------------------
    # Parent expansion (contexto de sección) — verificado por tenant
    # ------------------------------------------------------------------
    async def _expand_parents(
        self,
        query: RetrievalQuery,
        children: list[RetrievalChunk],
    ) -> list[RetrievalChunk]:
        parent_ids: list[UUID] = []
        for chunk in children:
            raw = chunk.metadata.get("parent_id") or chunk.metadata.get("section_id")
            if raw:
                try:
                    uuid_value = UUID(str(raw))
                except (ValueError, TypeError):
                    continue
                if uuid_value not in parent_ids:
                    parent_ids.append(uuid_value)
        if not parent_ids:
            return []

        try:
            ctx = await self._vector.get_documents(
                query.organization_id,
                parent_ids[:16],
                role=query.role,
            )
        except Exception as exc:
            logger.warning(
                "V2 parent expansion failed, degrading to children only",
                error=str(exc),
                organization_id=str(query.organization_id),
            )
            return []

        by_id = {chunk.document_id: chunk for chunk in ctx.chunks}
        ordered: list[RetrievalChunk] = []
        for pid in parent_ids:
            parent = by_id.get(pid)
            if parent is not None:
                ordered.append(parent)
        return ordered

    # ------------------------------------------------------------------
    # Diversidad por documento
    # ------------------------------------------------------------------
    @staticmethod
    def _diversify(
        children: list[RetrievalChunk],
        options: V2RetrievalOptions,
    ) -> list[RetrievalChunk]:
        seen_counts: dict[str, int] = {}
        diversified: list[RetrievalChunk] = []
        for chunk in children:
            doc_key = chunk.metadata.get("document_id") or str(chunk.document_id)
            count = seen_counts.get(doc_key, 0)
            if count >= options.max_per_document:
                continue
            seen_counts[doc_key] = count + 1
            diversified.append(chunk)
        return diversified
