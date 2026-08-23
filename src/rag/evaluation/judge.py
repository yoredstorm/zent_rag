# =============================================================================
# Evaluation Judge — LLM-as-judge para métricas de calidad
# =============================================================================
# Usa el puerto LLMProvider (LiteLLM) con temperature 0 para puntuar:
#   - context_relevance: ¿el contexto recuperado responde a la pregunta?
#   - answer_relevance:  ¿la respuesta responde a la pregunta?
#   - faithfulness:      ¿toda afirmación de la respuesta está soportada
#                        por el contexto? (0 = ninguna, 1 = todas)
#   - hallucination:     ¿la respuesta afirma algo que contradice o no
#                        está en el contexto?
# Fallos de parseo/LLM devuelven None (la métrica queda null; el runner
# renormaliza el score compuesto sin ella).
# =============================================================================
from __future__ import annotations

import json
import re
from typing import Any, cast

from src.core.config import get_settings
from src.core.ports import LLMProvider
from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)
_MAX_ATTEMPTS = 2

_CONTEXT_RELEVANCE_PROMPT = """You evaluate retrieval quality. Given a user question and the retrieved context chunks, judge how relevant the context is for answering the question.

Question:
{question}

Retrieved context:
{context}

Reply with a single JSON object only:
{{"score": <float 0.0 to 1.0>}} where 1.0 = the context fully answers the question and 0.0 = it is useless for it."""

_ANSWER_RELEVANCE_PROMPT = """You evaluate answer quality. Given a user question and the assistant's answer, judge how well the answer addresses the question.

Question:
{question}

Answer:
{answer}

Reply with a single JSON object only:
{{"score": <float 0.0 to 1.0>}} where 1.0 = fully and correctly answers and 0.0 = does not answer at all."""

_FAITHFULNESS_PROMPT = """You evaluate hallucination. Given a user question, the retrieved context, and the assistant's answer, judge whether every claim in the answer is supported by the context.

Question:
{question}

Retrieved context:
{context}

Answer:
{answer}

Reply with a single JSON object only:
{{"score": <float 0.0 to 1.0>, "hallucinated": <true|false>}} where:
- score = fraction of the answer's claims that are supported by the context (1.0 = all supported, 0.0 = none supported).
- hallucinated = true if the answer contains any claim not supported by the context."""


class LLMJudge:
    """Juez de calidad basado en LLM. No rompe el run si el LLM falla."""

    def __init__(
        self,
        llm_provider: LLMProvider,
        model: str | None = None,
        max_tokens: int | None = None,
        enabled: bool = True,
    ) -> None:
        settings = get_settings()
        self._llm = llm_provider
        self._model = model or settings.EVAL_JUDGE_MODEL
        self._max_tokens = max_tokens or settings.EVAL_JUDGE_MAX_TOKENS
        self.enabled = enabled and bool(settings.EVAL_JUDGE_ENABLED)

    @property
    def model(self) -> str:
        return self._model

    async def _judge_json(self, prompt: str) -> dict | None:
        for attempt in range(_MAX_ATTEMPTS):
            try:
                resp = await self._llm.generate(
                    prompt=prompt,
                    model=self._model,
                    max_tokens=self._max_tokens,
                    temperature=0.0,
                )
                parsed = _extract_json(resp.content)
                if parsed is not None:
                    return parsed
                logger.warning(
                    "Judge JSON parse failed", attempt=attempt + 1,
                )
            except Exception as exc:
                logger.warning(
                    "Judge LLM call failed",
                    attempt=attempt + 1,
                    error=str(exc),
                )
        return None

    async def context_relevance(self, question: str, context: str) -> float | None:
        if not self.enabled:
            return None
        if not context.strip():
            return 0.0
        result = await self._judge_json(
            _CONTEXT_RELEVANCE_PROMPT.format(
                question=question[:2000], context=context[:8000]
            )
        )
        return _score_from(result)

    async def answer_relevance(self, question: str, answer: str) -> float | None:
        if not self.enabled:
            return None
        if not answer.strip():
            return 0.0
        result = await self._judge_json(
            _ANSWER_RELEVANCE_PROMPT.format(
                question=question[:2000], answer=answer[:8000]
            )
        )
        return _score_from(result)

    async def faithfulness(
        self, question: str, context: str, answer: str
    ) -> tuple[float | None, bool | None]:
        if not self.enabled:
            return None, None
        if not answer.strip():
            return 0.0, False
        if not context.strip():
            return 0.0, True
        result = await self._judge_json(
            _FAITHFULNESS_PROMPT.format(
                question=question[:2000],
                context=context[:8000],
                answer=answer[:8000],
            )
        )
        if result is None:
            return None, None
        raw_score = cast(Any, result.get("score"))
        score_value: float | None = None
        if isinstance(raw_score, (int, float, str)):
            try:
                score_value = float(raw_score)
            except ValueError:
                score_value = None
        hallucinated = bool(result.get("hallucinated", False))
        return score_value, hallucinated


def _score_from(result: dict | None) -> float | None:
    if result is None:
        return None
    raw_score = cast(Any, result.get("score"))
    if not isinstance(raw_score, (int, float, str)):
        return None
    try:
        score = float(raw_score)
    except ValueError:
        return None
    return round(max(0.0, min(1.0, score)), 4)


def _extract_json(content: str) -> dict | None:
    """Extrae el primer objeto JSON válido del texto del juez."""
    text = (content or "").strip()
    match = _JSON_RE.search(text)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    return None
