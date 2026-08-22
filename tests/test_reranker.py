# =============================================================================
# Rerankers — tests de abstracción, registry y fallbacks
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest

from src.core.domain.entities import LLMResponse, RetrievalChunk
from src.core.ports import LLMProvider
from src.rag.reranking import get_reranker  # noqa: F401 (importa base)
from src.rag.reranking.base import NoopReranker, Reranker
from src.rag.reranking.cross_encoder import CrossEncoderReranker  # noqa: F401 (register)
from src.rag.reranking.reranker import LLMReranker  # noqa: F401 (register)


def _chunk(content: str, score: float) -> RetrievalChunk:
    return RetrievalChunk(document_id=uuid4(), content=content, score=score)


class FakeLLM(LLMProvider):
    def __init__(self, scores: list[str] | None = None, fail: bool = False) -> None:
        self.scores = scores or []
        self.fail = fail

    async def generate(self, prompt: str, model=None, **kwargs) -> LLMResponse:
        if self.fail:
            raise RuntimeError("LLM down")
        score = self.scores.pop(0) if self.scores else "0.5"
        return LLMResponse(content=score, model=model or "test")

    async def generate_stream(self, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError

    async def embed(self, text, model=None):
        raise NotImplementedError

    async def rerank(self, query, documents, model=None, top_n=None):
        return [(0, 0.9), (1, 0.5)]


class TestRegistry:
    def test_noop_for_empty_name(self) -> None:
        assert isinstance(get_reranker(None), NoopReranker)

    def test_unknown_name_falls_back_noop(self) -> None:
        assert isinstance(get_reranker("not_registered"), NoopReranker)

    def test_llm_reranker_registered(self) -> None:
        reranker = get_reranker("llm", llm_provider=FakeLLM())
        assert isinstance(reranker, Reranker)

    def test_cross_encoder_registered(self) -> None:
        reranker = get_reranker("cross_encoder", llm_provider=FakeLLM())
        assert isinstance(reranker, CrossEncoderReranker)


class TestNoopReranker:
    @pytest.mark.asyncio
    async def test_passthrough_preserves_order(self) -> None:
        chunks = [_chunk("a", 0.9), _chunk("b", 0.8), _chunk("c", 0.7)]
        out = await NoopReranker().rerank("q", chunks, top_n=2)
        assert [c.content for c in out] == ["a", "b"]


class TestLLMReranker:
    @pytest.mark.asyncio
    async def test_blend_and_reorder(self) -> None:
        llm = FakeLLM(scores=["0.9", "0.1"])
        chunks = [_chunk("low", 0.5), _chunk("high", 0.5)]
        reranker = LLMReranker(llm_provider=llm, model="test-model")
        out = await reranker.rerank("q", chunks, top_n=2)
        assert out[0].content == "low"  # blend 0.4*0.5+0.6*0.9 > 0.4*0.5+0.6*0.1
        assert out[0].score > out[1].score

    @pytest.mark.asyncio
    async def test_llm_failure_keeps_original_order_and_score(self) -> None:
        llm = FakeLLM(fail=True)
        chunks = [_chunk("a", 0.9), _chunk("b", 0.8)]
        reranker = LLMReranker(llm_provider=llm, model="test-model")
        out = await reranker.rerank("q", chunks, top_n=2)
        assert [c.content for c in out] == ["a", "b"]
        assert out[0].score == 0.9

    def test_parse_score(self) -> None:
        assert LLMReranker._parse_score("0.7") == 0.7
        assert LLMReranker._parse_score("1.0") == 1.0
        assert LLMReranker._parse_score("garbage") == 0.0
        assert LLMReranker._parse_score("1.5") == 1.0


class TestCrossEncoderReranker:
    @pytest.mark.asyncio
    async def test_reorders_by_api_scores(self) -> None:
        llm = FakeLLM()
        chunks = [_chunk("a", 0.5), _chunk("b", 0.5)]
        reranker = CrossEncoderReranker(llm_provider=llm, model="test-model")
        out = await reranker.rerank("q", chunks, top_n=2)
        assert [c.content for c in out] == ["a", "b"]
        assert out[0].score == 0.9

    @pytest.mark.asyncio
    async def test_failure_keeps_original_order(self) -> None:
        class FailingLLM(FakeLLM):
            async def rerank(self, query, documents, model=None, top_n=None):
                raise RuntimeError("rerank api down")

        chunks = [_chunk("a", 0.9), _chunk("b", 0.8)]
        reranker = CrossEncoderReranker(llm_provider=FailingLLM(), model="test-model")
        out = await reranker.rerank("q", chunks, top_n=2)
        assert [c.content for c in out] == ["a", "b"]
        assert out[0].score == 0.9
