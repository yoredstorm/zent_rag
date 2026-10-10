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

_RERANK_BATCH_PROMPT = """You score how relevant each document is to a user question.
Return ONLY a JSON array of numbers from 0.0 to 1.0, one per document, in the
same order (example: [0.9, 0.3, 0.7]). No other text.

Question: {query}

Documents:
{documents}

Scores:"""

_NUMBER_RE = re.compile(r"0?\.\d+|1\.0|\b1\b|\b0\b")


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

        # Cap candidates to keep latency/cost bounded
        candidates = chunks[: min(len(chunks), max(top_n * 3, 40))]

        scores = await self._score_batch(query, candidates)
        scored = [
            (score, replace(chunk, score=score))
            for chunk, score in zip(candidates, scores)
        ]

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

    async def _score_batch(
        self, query: str, candidates: list[RetrievalChunk]
    ) -> list[float]:
        """UN pedido para todos los candidatos (score por documento).

        Si el parseo no devuelve un score por documento, cae al scoring por
        chunk (comportamiento viejo). Un solo pedido evita ráfagas de N
        llamadas por retrieval (límite de RPM del proveedor).
        """
        documents = "\n".join(
            f"{index + 1}. {(chunk.content or '')[:600]}"
            for index, chunk in enumerate(candidates)
        )
        prompt = _RERANK_BATCH_PROMPT.format(
            query=query[:500], documents=documents
        )
        parsed: list[float] = []
        try:
            resp = await self._llm.generate(
                prompt=prompt,
                model=self._model,
                max_tokens=max(8, 8 * len(candidates)),
                temperature=0.0,
            )
            parsed = self._parse_scores(resp.content, len(candidates))
        except Exception as exc:
            logger.warning("Rerank batch failed", error=str(exc)[:200])
        if len(parsed) != len(candidates):
            return await self._score_each(query, candidates)
        return [
            0.4 * float(chunk.score) + 0.6 * score
            for chunk, score in zip(candidates, parsed)
        ]

    async def _score_each(
        self, query: str, candidates: list[RetrievalChunk]
    ) -> list[float]:
        """Fallback: un pedido por chunk (sólo si el batch no parseó)."""
        scores: list[float] = []
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
                blended = 0.4 * float(chunk.score) + 0.6 * score
            except Exception as exc:
                logger.warning("Rerank score failed for chunk", error=str(exc))
                blended = float(chunk.score)
            scores.append(blended)
        return scores

    @staticmethod
    def _parse_scores(text: str, expected: int) -> list[float]:
        values: list[float] = []
        for match in _NUMBER_RE.findall(text or ""):
            try:
                values.append(max(0.0, min(1.0, float(match))))
            except ValueError:
                continue
            if len(values) >= expected:
                break
        return values

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
