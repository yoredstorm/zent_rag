# =============================================================================
# Evaluation Runner — orquesta dataset → target → métricas → score
# =============================================================================
# Por cada caso: ejecuta el target, computa métricas deterministas y del
# juez, y agrega un score compuesto ponderado (pesos por dataset o defaults).
# Si una componente no está disponible (p.ej. judge apagado), los pesos se
# renormalizan sobre las disponibles.
# =============================================================================
from __future__ import annotations

import time
from dataclasses import dataclass, field
from uuid import UUID, uuid4

from src.infrastructure.observability.logging_config import get_logger
from src.rag.evaluation.datasets import EvalCase, EvalDataset
from src.rag.evaluation.judge import LLMJudge
from src.rag.evaluation.metrics import (
    answer_keyword_coverage,
    citation_stats,
    latency_summary,
    mean_or,
    retrieval_precision,
    retrieval_recall,
)
from src.rag.evaluation.targets import EvalTarget

logger = get_logger(__name__)

DEFAULT_WEIGHTS = {
    "retrieval": 0.20,
    "context_relevance": 0.10,
    "answer_relevance": 0.25,
    "faithfulness": 0.25,
    "citation_accuracy": 0.10,
    "anti_hallucination": 0.10,
}


@dataclass(kw_only=True)
class CaseEval:
    """Evaluación completa de un caso."""

    case_id: str
    question: str
    answer: str
    status: str
    target: dict = field(default_factory=dict)
    metrics: dict = field(default_factory=dict)
    scores: dict = field(default_factory=dict)
    retrieved: list[dict] = field(default_factory=list)
    expected_answer: str | None = None
    expected_sources: list[str] = field(default_factory=list)
    error: str | None = None


def _context_text(chunks: list[dict]) -> str:
    return "\n\n".join(str(c.get("content") or "") for c in chunks)


def _renormalize(weights: dict, available: set[str]) -> dict:
    """Re-normaliza pesos sobre las componentes disponibles."""
    active = {k: v for k, v in weights.items() if k in available}
    total = sum(active.values())
    if total <= 0:
        return {}
    return {k: round(v / total, 4) for k, v in active.items()}


class EvalRunner:
    """Runner de evaluación end-to-end sobre un dataset."""

    def __init__(
        self,
        target: EvalTarget,
        judge: LLMJudge | None = None,
    ) -> None:
        self._target = target
        self._judge = judge

    async def evaluate_case(self, case: EvalCase) -> CaseEval:
        start = time.perf_counter()
        target_result = await self._target.execute(case.question, case.metadata)
        wall_ms = round((time.perf_counter() - start) * 1000, 2)

        retrieved = target_result.retrieved
        context_text = _context_text(retrieved)

        # --- Métricas deterministas ---
        precision = retrieval_precision(retrieved, case.expected_sources)
        recall = retrieval_recall(retrieved, case.expected_sources)
        citations = citation_stats(
            target_result.answer, retrieved, case.expected_sources or None
        )
        keyword_coverage = answer_keyword_coverage(
            target_result.answer, case.legacy_keywords
        )

        # --- Métricas del juez (None si apagado/falla) ---
        context_relevance: float | None = None
        answer_relevance: float | None = None
        faithfulness: float | None = None
        hallucinated: bool | None = None
        if self._judge is not None:
            context_relevance = await self._judge.context_relevance(
                case.question, context_text
            )
            answer_relevance = await self._judge.answer_relevance(
                case.question, target_result.answer
            )
            faithfulness, hallucinated = await self._judge.faithfulness(
                case.question, context_text, target_result.answer
            )

        # Fallback determinista si el juez no respondió (solo relevancia de
        # respuesta vía keywords legacy).
        if answer_relevance is None and keyword_coverage is not None:
            answer_relevance = keyword_coverage

        cost = target_result.cost
        if cost <= 0 and target_result.model:
            cost = await _estimate_cost(target_result)

        metrics = {
            "retrieval_precision": precision,
            "retrieval_recall": recall,
            "context_relevance": context_relevance,
            "answer_relevance": answer_relevance,
            "faithfulness": faithfulness,
            "citation_accuracy": citations["accuracy"],
            "hallucinated": hallucinated,
            "latency_ms": wall_ms if not target_result.total_latency_ms else target_result.total_latency_ms,
            "retrieval_latency_ms": target_result.retrieval_latency_ms,
            "llm_latency_ms": target_result.llm_latency_ms,
            "prompt_tokens": target_result.prompt_tokens,
            "completion_tokens": target_result.completion_tokens,
            "total_tokens": target_result.total_tokens,
            "cost": round(cost, 6),
        }

        scores = self._case_scores(metrics)
        return CaseEval(
            case_id=case.id,
            question=case.question,
            answer=target_result.answer,
            status=target_result.status,
            target={
                "model": target_result.model,
                "method": target_result.method,
                "chunks": len(retrieved),
            },
            metrics=metrics,
            scores=scores,
            retrieved=retrieved,
            expected_answer=case.expected_answer,
            expected_sources=list(case.expected_sources or []),
            error=target_result.error,
        )

    def _case_scores(self, metrics: dict) -> dict:
        scores = {
            "retrieval": round(
                (metrics["retrieval_precision"] + metrics["retrieval_recall"]) / 2,
                4,
            ),
            "context_relevance": metrics["context_relevance"],
            "answer_relevance": metrics["answer_relevance"],
            "faithfulness": metrics["faithfulness"],
            "citation_accuracy": metrics["citation_accuracy"],
            "anti_hallucination": (
                None
                if metrics["hallucinated"] is None
                else round(0.0 if metrics["hallucinated"] else 1.0, 4)
            ),
        }
        available = {k for k, v in scores.items() if v is not None}
        weights = _renormalize(DEFAULT_WEIGHTS, available)
        composite = round(
            sum(scores[k] * w for k, w in weights.items()), 4
        ) if weights else 0.0
        return {**scores, "composite": composite}

    async def run(
        self,
        dataset: EvalDataset,
        *,
        run_id: UUID | None = None,
        version_snapshot: dict | None = None,
        version_id: str | None = None,
    ) -> dict:
        """Ejecuta el dataset completo y devuelve el summary del run."""
        run_id = run_id or uuid4()
        results: list[CaseEval] = []
        for case in dataset.cases:
            logger.info("Eval case started", case_id=case.id, question=case.question[:80])
            case_eval = await self.evaluate_case(case)
            results.append(case_eval)

        return self.build_summary(
            dataset=dataset,
            results=results,
            run_id=run_id,
            version_snapshot=version_snapshot or {},
            version_id=version_id,
            judge_model=self._judge.model if self._judge else None,
            judge_enabled=bool(self._judge and self._judge.enabled),
        )

    def build_summary(
        self,
        *,
        dataset: EvalDataset,
        results: list[CaseEval],
        run_id: UUID,
        version_snapshot: dict,
        version_id: str | None,
        judge_model: str | None,
        judge_enabled: bool,
    ) -> dict:
        total = len(results)
        cases_payload = [_case_payload(r) for r in results]

        quality = {
            "composite_score": round(mean_or([r.scores["composite"] for r in results]), 4),
            "retrieval_precision": mean_or(
                [r.metrics["retrieval_precision"] for r in results]
            ),
            "retrieval_recall": mean_or(
                [r.metrics["retrieval_recall"] for r in results]
            ),
            "context_relevance": _mean_none_ok(
                [r.metrics["context_relevance"] for r in results]
            ),
            "answer_relevance": _mean_none_ok(
                [r.metrics["answer_relevance"] for r in results]
            ),
            "faithfulness": _mean_none_ok(
                [r.metrics["faithfulness"] for r in results]
            ),
            "citation_accuracy": _mean_none_ok(
                [r.metrics["citation_accuracy"] for r in results]
            ),
            "hallucination_rate": _hallucination_rate(results),
            "judge_enabled": judge_enabled,
            "judge_model": judge_model,
        }

        latencies = [r.metrics["latency_ms"] for r in results]
        retrieval_latencies = [
            r.metrics["retrieval_latency_ms"] for r in results if r.metrics["retrieval_latency_ms"]
        ]
        llm_latencies = [
            r.metrics["llm_latency_ms"] for r in results if r.metrics["llm_latency_ms"]
        ]
        costs = [r.metrics["cost"] for r in results if r.metrics["cost"] > 0]

        performance = {
            "latency": latency_summary(latencies),
            "retrieval_latency": latency_summary(retrieval_latencies),
            "llm_latency": latency_summary(llm_latencies),
            "total_tokens": sum(r.metrics["total_tokens"] for r in results),
            "avg_tokens": round(
                sum(r.metrics["total_tokens"] for r in results) / total, 2
            ) if total else 0.0,
            "total_cost": round(sum(costs), 6),
            "avg_cost": round(sum(costs) / len(costs), 6) if costs else 0.0,
        }

        summary = {
            "run_id": str(run_id),
            "dataset_name": dataset.name,
            "schema_version": dataset.schema_version,
            "total_cases": total,
            "failed_cases": sum(1 for r in results if r.status != "completed"),
            "target_type": self._target.target_type,
            "target_name": self._target.target_name,
            "target_id": str(self._target.target_id) if self._target.target_id else None,
            "version_snapshot": version_snapshot,
            "version_id": version_id,
            "quality": quality,
            "performance": performance,
            "cases": cases_payload,
        }
        return summary


def _compact_retrieved(chunks: list[dict], *, limit: int = 8) -> list[dict]:
    compact: list[dict] = []
    for chunk in chunks[:limit]:
        content = str(chunk.get("content") or "")[:400]
        compact.append(
            {
                "content": content,
                "score": chunk.get("score"),
                "metadata": chunk.get("metadata") or {},
            }
        )
    return compact


def _case_payload(case_eval: CaseEval) -> dict:
    return {
        "case_id": case_eval.case_id,
        "question": case_eval.question,
        "answer": case_eval.answer[:4000],
        "actual": case_eval.answer[:4000],
        "expected_answer": case_eval.expected_answer,
        "expected_sources": list(case_eval.expected_sources or []),
        "retrieved": _compact_retrieved(case_eval.retrieved),
        "status": case_eval.status,
        "target": case_eval.target,
        "metrics": case_eval.metrics,
        "scores": case_eval.scores,
        "latency_ms": case_eval.metrics.get("latency_ms"),
        "cost": case_eval.metrics.get("cost"),
        "error": case_eval.error,
    }


def _mean_none_ok(values: list[float | None]) -> float | None:
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return round(sum(vals) / len(vals), 4)


def _hallucination_rate(results: list[CaseEval]) -> float | None:
    flagged = [r for r in results if r.metrics["hallucinated"] is not None]
    if not flagged:
        return None
    return round(
        sum(1 for r in flagged if r.metrics["hallucinated"]) / len(flagged), 4
    )


async def _estimate_cost(target_result) -> float:
    try:
        from src.platform.billing.pricing import estimate_cost

        return float(
            await estimate_cost(
                target_result.model,
                prompt_tokens=target_result.prompt_tokens,
                completion_tokens=target_result.completion_tokens,
            )
        )
    except Exception as exc:
        logger.warning("Cost estimation failed", error=str(exc))
        return 0.0
