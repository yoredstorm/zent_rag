# =============================================================================
# CrossEncoderReranker — rerank vía API de rerank de LiteLLM
# (cohere / jina / azure-ai / voyage). Un solo call por lote, no por chunk.
# =============================================================================
from __future__ import annotations

import time
from dataclasses import replace

from src.core.config import get_settings
from src.core.domain.entities import RetrievalChunk
from src.core.ports import LLMProvider
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.observability.metrics import rag_rerank_latency, rag_rerank_top_score
from src.rag.reranking.base import Reranker, register_reranker

logger = get_logger(__name__)


class CrossEncoderReranker(Reranker):
    """Reranker cross-encoder vía `LLMProvider.rerank` (LiteLLM areank).

    Mejor relevancia que el reranker LLM por chunk y menor costo: un solo
    batch call. Si el proveedor no soporta rerank, devuelve el orden
    original sin fallar.
    """

    def __init__(self, llm_provider: LLMProvider, model: str | None = None) -> None:
        self._llm = llm_provider
        settings = get_settings()
        self._model = model or settings.RAG_CROSS_ENCODER_MODEL or None

    async def rerank(
        self,
        query: str,
        chunks: list[RetrievalChunk],
        top_n: int = 20,
        organization_id: str = "",
    ) -> list[RetrievalChunk]:
        if not chunks:
            return chunks

        start = time.perf_counter()
        candidates = chunks[: min(len(chunks), max(top_n * 3, 40))]
        documents = [(c.content or "")[:1000] for c in candidates]
        try:
            ranked = await self._llm.rerank(
                query=query[:500],
                documents=documents,
                model=self._model,
                top_n=top_n,
            )
        except Exception as exc:
            logger.warning("Cross-encoder rerank failed, keeping order", error=str(exc))
            return chunks[:top_n]

        ordered: list[RetrievalChunk] = []
        for index, score in ranked:
            if 0 <= index < len(candidates):
                ordered.append(replace(candidates[index], score=float(score)))

        elapsed = time.perf_counter() - start
        if organization_id:
            rag_rerank_latency.labels(organization_id=organization_id).observe(elapsed)
            if ordered:
                rag_rerank_top_score.labels(organization_id=organization_id).set(ordered[0].score)

        logger.info(
            "Cross-encoder rerank complete",
            candidates=len(candidates),
            top_n=len(ordered),
            latency_ms=round(elapsed * 1000, 2),
        )
        return ordered


register_reranker("cross_encoder", CrossEncoderReranker)
