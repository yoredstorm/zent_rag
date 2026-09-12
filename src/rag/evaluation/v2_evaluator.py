# =============================================================================
# V2 Evaluator — Enterprise Evaluation runner (brief §27)
# =============================================================================
# Evalúa el pipeline Knowledge V2 contra golden sets:
#   evaluate_retrieval  → RetrievalEvaluation por caso + aggregate
#   evaluate_answers    → AnswerEvaluation por caso sobre GroundedAnswer
# Determinista; el judge LLM es opcional (fase más adelante).
# =============================================================================
from __future__ import annotations

import time
from dataclasses import dataclass, field
from dataclasses import replace as _replace
from typing import Awaitable, Callable
from uuid import UUID

from src.rag.evaluation.golden_v2 import GoldenSet
from src.rag.evaluation.judge_v2 import JudgeFn
from src.rag.evaluation.v2_metrics import (
    AnswerEvaluation,
    RetrievalEvaluation,
    reranker_lift,
)
from src.rag.grounding.models import GroundedAnswer

RetrieveFn = Callable[[str], Awaitable[tuple[list[UUID], float]]]
"""Devuelve (document_ids ordenados por relevancia, latency_ms)."""

GroundFn = Callable[[str], Awaitable[GroundedAnswer]]


def _replace_judge(evaluation: AnswerEvaluation, score: float) -> AnswerEvaluation:
    return _replace(evaluation, judge_groundedness=score)


@dataclass(frozen=True, kw_only=True)
class RetrievalAggregate:
    cases: int
    avg_recall_at_k: float = 0.0
    avg_precision_at_k: float = 0.0
    avg_mrr: float = 0.0
    avg_ndcg_at_k: float = 0.0
    avg_latency_ms: float = 0.0
    reranker_lift: float = 0.0

    def to_dict(self) -> dict:
        return {
            "cases": self.cases,
            "avg_recall_at_k": round(self.avg_recall_at_k, 4),
            "avg_precision_at_k": round(self.avg_precision_at_k, 4),
            "avg_mrr": round(self.avg_mrr, 4),
            "avg_ndcg_at_k": round(self.avg_ndcg_at_k, 4),
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "reranker_lift": round(self.reranker_lift, 4),
        }


@dataclass(frozen=True, kw_only=True)
class EvaluationReport:
    golden_set: str
    retrieval: dict[str, object]
    answers: dict[str, object] = field(default_factory=dict)
    total_latency_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "golden_set": self.golden_set,
            "retrieval_quality": self.retrieval,
            "answer_quality": self.answers,
            "total_latency_ms": round(self.total_latency_ms, 2),
        }


class V2Evaluator:
    """Runner determinista de la evaluación enterprise sobre el pipeline V2."""

    def __init__(self, *, k: int = 10) -> None:
        self._k = k

    async def evaluate_retrieval(
        self,
        golden_set: GoldenSet,
        retrieve: RetrieveFn,
        *,
        k: int | None = None,
    ) -> tuple[list[RetrievalEvaluation], RetrievalAggregate]:
        k = k or self._k
        evaluations: list[RetrievalEvaluation] = []
        total_latency = 0.0
        for case in golden_set.cases:
            start = time.perf_counter()
            retrieved_ids, latency_ms = await retrieve(case.query)
            total_latency += latency_ms
            evaluations.append(
                RetrievalEvaluation(
                    query=case.query,
                    relevant_docs=case.relevant_document_ids,
                    retrieved_docs=tuple(retrieved_ids),
                    k=k,
                )
            )
        if not evaluations:
            aggregate = RetrievalAggregate(cases=0)
        else:
            count = len(evaluations)
            aggregate = RetrievalAggregate(
                cases=count,
                avg_recall_at_k=sum(e.recall for e in evaluations) / count,
                avg_precision_at_k=sum(e.precision for e in evaluations) / count,
                avg_mrr=sum(e.mrr for e in evaluations) / count,
                avg_ndcg_at_k=sum(e.ndcg for e in evaluations) / count,
                avg_latency_ms=total_latency / count,
                reranker_lift=0.0,
            )
        return evaluations, aggregate

    async def evaluate_retrieval_with_rerank(
        self,
        golden_set: GoldenSet,
        retrieve_base: RetrieveFn,
        retrieve_reranked: RetrieveFn,
        *,
        k: int | None = None,
    ) -> RetrievalAggregate:
        k = k or self._k
        _, aggregate = await self.evaluate_retrieval(
            golden_set, retrieve_base, k=k
        )
        _, reranked = await self.evaluate_retrieval(
            golden_set, retrieve_reranked, k=k
        )
        return RetrievalAggregate(
            cases=aggregate.cases,
            avg_recall_at_k=reranked.avg_recall_at_k,
            avg_precision_at_k=reranked.avg_precision_at_k,
            avg_mrr=reranked.avg_mrr,
            avg_ndcg_at_k=reranked.avg_ndcg_at_k,
            avg_latency_ms=reranked.avg_latency_ms,
            reranker_lift=reranker_lift(
                aggregate.avg_recall_at_k, reranked.avg_recall_at_k
            ),
        )

    async def evaluate_answers(
        self,
        golden_set: GoldenSet,
        ground: GroundFn,
        *,
        judge: JudgeFn | None = None,
    ) -> list[AnswerEvaluation]:
        evaluations: list[AnswerEvaluation] = []
        for case in golden_set.cases:
            answer = await ground(case.query)
            evaluation = AnswerEvaluation(
                question=case.query,
                answer=answer,
                cited_ids=set(case.cited_document_ids),
                expected_unsupported=case.expected_unsupported,
            )
            if judge is not None:
                excerpt_ctx = tuple(
                    c.excerpt
                    for c in answer.citations[:12]
                    if c.excerpt
                ) or tuple(
                    c.supporting_citations[0].excerpt
                    for c in answer.claims
                    if c.supporting_citations and c.supporting_citations[0].excerpt
                )
                from src.rag.evaluation.judge_v2 import judge_groundedness

                verdicts = await judge(
                    case.query, answer.answer, excerpt_ctx
                )
                scored = judge_groundedness(verdicts)
                if scored is not None:
                    evaluation = _replace_judge(evaluation, scored)
            evaluations.append(evaluation)
        return evaluations

    async def report(
        self,
        golden_set: GoldenSet,
        *,
        retrieval: dict[str, object],
        answers: dict[str, object] | None = None,
        total_latency_ms: float = 0.0,
    ) -> EvaluationReport:
        return EvaluationReport(
            golden_set=golden_set.name,
            retrieval=retrieval,
            answers=answers or {},
            total_latency_ms=total_latency_ms,
        )
