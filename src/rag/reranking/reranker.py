# =============================================================================
# LLM Reranker — post-retrieval scoring via LiteLLM
# =============================================================================
from __future__ import annotations

import re
import time
from dataclasses import replace

from src.core.config import get_settings
from src.core.domain.entities import RetrievalChunk
from src.core.ports import LLMProvider
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.observability.metrics import rag_rerank_latency, rag_rerank_top_score
from src.rag.reranking.base import Reranker, register_reranker

logger = get_logger(__name__)

_RERANK_PROMPT = """You score how relevant a document is to a user question.
Return ONLY a number from 0.0 to 1.0 (one decimal is fine). No other text.

Question: {query}

Document:
{document}

Relevance score:"""


class LLMReranker(Reranker):
    """Cheap LLM-based reranker. Uses a low-temp completion to score each chunk."""

    def __init__(self, llm_provider: LLMProvider, model: str | None = None) -> None:
        self._llm = llm_provider
        settings = get_settings()
        self._model = model or settings.RAG_RERANK_MODEL or None

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
        scored: list[tuple[float, RetrievalChunk]] = []

        # Cap candidates to keep latency/cost bounded
        candidates = chunks[: min(len(chunks), max(top_n * 3, 40))]

        for chunk in candidates:
            snippet = (chunk.content or "")[:800]
            prompt = _RERANK_PROMPT.format(query=query[:500], document=snippet)
            try:
                resp = await self._llm.generate(
                    prompt=prompt,
                    model=self._model,
                    max_tokens=8,
                    temperature=0.0,
                )
                score = self._parse_score(resp.content)
                # Blend retrieval score with LLM score
                blended = 0.4 * float(chunk.score) + 0.6 * score
            except Exception as exc:
                logger.warning("Rerank score failed for chunk", error=str(exc))
                blended = float(chunk.score)

            scored.append((blended, replace(chunk, score=blended)))

        scored.sort(key=lambda x: x[0], reverse=True)
        result = [chunk for _, chunk in scored[:top_n]]

        elapsed = time.perf_counter() - start
        if organization_id:
            rag_rerank_latency.labels(organization_id=organization_id).observe(elapsed)
            if result:
                rag_rerank_top_score.labels(organization_id=organization_id).set(result[0].score)

        logger.info(
            "Rerank complete",
            candidates=len(candidates),
            top_n=len(result),
            latency_ms=round(elapsed * 1000, 2),
        )
        return result

    @staticmethod
    def _parse_score(text: str) -> float:
        match = re.search(r"0?\.\d+|1\.0|1|0", (text or "").strip())
        if not match:
            return 0.0
        try:
            val = float(match.group(0))
            return max(0.0, min(1.0, val))
        except ValueError:
            return 0.0


register_reranker("llm", LLMReranker)
