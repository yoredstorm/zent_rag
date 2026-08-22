# =============================================================================
# VectorRetriever — búsqueda semántica pura con prioridad de doc_type
# =============================================================================
from __future__ import annotations

from src.core.domain.entities import RetrievalContext
from src.core.ports import VectorStore
from src.rag.retrieval.base import Retriever
from src.rag.retrieval.fusion import dedupe_chunks
from src.rag.retrieval.models import RetrievalQuery


class VectorRetriever(Retriever):
    """Implementación semántica del Retriever sobre el puerto VectorStore.

    Reproduce el comportamiento histórico del orchestrator (aggregated
    first + fill con el resto) vía `doc_type_priority`, generalizado a
    N tipos de documento.
    """

    def __init__(self, vector_store: VectorStore) -> None:
        self._store = vector_store

    async def retrieve(self, query: RetrievalQuery) -> RetrievalContext:
        effective = query.effective_top_k or query.top_k
        collected: list = []
        seen: set = set()
        total_latency = 0.0
        query_embedding = query.query_embedding
        if query_embedding is None:
            raise ValueError("VectorRetriever requires query_embedding")

        # Pasada 1: tipos de documento priorizados (uno por uno, en orden).
        budget = query.top_k
        for doc_type in query.doc_type_priority:
            ctx = await self._store.search(
                organization_id=query.organization_id,
                query_embedding=query_embedding,
                top_k=budget,
                filters={"metadata.doc_type": doc_type},
                score_threshold=query.score_threshold,
                role=query.role,
                knowledge_base_id=query.knowledge_base_id,
            )
            total_latency += ctx.retrieval_latency_ms
            for chunk in ctx.chunks:
                if chunk.document_id in seen:
                    continue
                seen.add(chunk.document_id)
                collected.append(chunk)
            budget = max(effective - len(collected), 0)
            if budget <= 0:
                break

        # Pasada 2: rellenar el presupuesto restante con el resto.
        if budget > 0:
            # exclude_filters es dict key->value; con un solo tipo priorizado
            # se excluye para no gastar quota. Con varios, el dedupe protege
            # la corrección aunque el fill devuelva duplicados.
            exclude = None
            if len(query.doc_type_priority) == 1:
                exclude = {"metadata.doc_type": query.doc_type_priority[0]}
            ctx = await self._store.search(
                organization_id=query.organization_id,
                query_embedding=query_embedding,
                top_k=budget,
                exclude_filters=exclude,
                score_threshold=query.score_threshold,
                role=query.role,
                knowledge_base_id=query.knowledge_base_id,
            )
            total_latency += ctx.retrieval_latency_ms
            for chunk in ctx.chunks:
                if chunk.document_id in seen:
                    continue
                seen.add(chunk.document_id)
                collected.append(chunk)

        return RetrievalContext(
            chunks=dedupe_chunks(collected),
            query_embedding=query_embedding,
            retrieval_latency_ms=total_latency,
        )
