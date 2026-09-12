# =============================================================================
# Enterprise Evaluation — Knowledge V2 (brief §27)
# =============================================================================
from __future__ import annotations

from src.rag.evaluation.golden_v2 import (
    GoldenCase,
    GoldenSet,
    build_corpus_golden_set,
    golden_set_from_dict,
    load_golden_set,
)
from src.rag.evaluation.judge_v2 import (
    JudgeFn,
    JudgeVerdict,
    judge_groundedness,
    make_llm_judge,
)
from src.rag.evaluation.v2_evaluator import (
    EvaluationReport,
    RetrievalAggregate,
    V2Evaluator,
)
from src.rag.evaluation.v2_metrics import (
    AnswerEvaluation,
    RetrievalEvaluation,
    abstention_correctness,
    citation_precision,
    citation_recall,
    conflict_detection,
    context_precision,
    groundedness,
    mean_reciprocal_rank,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reranker_lift,
)

__all__ = [
    "GoldenCase",
    "GoldenSet",
    "build_corpus_golden_set",
    "golden_set_from_dict",
    "load_golden_set",
    "JudgeFn",
    "JudgeVerdict",
    "judge_groundedness",
    "make_llm_judge",
    "EvaluationReport",
    "RetrievalAggregate",
    "V2Evaluator",
    "AnswerEvaluation",
    "RetrievalEvaluation",
    "abstention_correctness",
    "citation_precision",
    "citation_recall",
    "conflict_detection",
    "context_precision",
    "groundedness",
    "mean_reciprocal_rank",
    "ndcg_at_k",
    "precision_at_k",
    "recall_at_k",
    "reranker_lift",
]
