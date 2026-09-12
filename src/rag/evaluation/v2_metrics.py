# =============================================================================
# Enterprise Evaluation — Knowledge V2 (brief §27)
# =============================================================================
# Separación explícita:
#   Retrieval Quality  → recall@k, MRR, nDCG@k, context precision/recall,
#                        reranker lift, latency, cost per query
#   Answer Quality     → groundedness, citation precision/recall,
#                        answer correctness, abstention correctness,
#                        conflict detection
#   Knowledge Quality  → composición de score/readiness (fuera de este módulo;
#                        Knowledge Score V1 + dimensiones de documento)
# Todo determinista y sin LLM obligatorio (el judge LLM es opcional, fase H).
# =============================================================================
from __future__ import annotations

import math
from dataclasses import dataclass, field
from uuid import UUID

from src.rag.grounding.models import ClaimStatus, GroundedAnswer

# ---------------------------------------------------------------------------
# Retrieval metrics
# ---------------------------------------------------------------------------

def recall_at_k(retrieved_ids: list, relevant_ids: set, k: int) -> float:
    top = retrieved_ids[:k]
    if not relevant_ids:
        return 0.0
    return len(set(top) & relevant_ids) / len(relevant_ids)


def precision_at_k(retrieved_ids: list, relevant_ids: set, k: int) -> float:
    top = retrieved_ids[:k]
    if not top:
        return 0.0
    return len(set(top) & relevant_ids) / len(top)


def mean_reciprocal_rank(retrieved_ids: list, relevant_ids: set) -> float:
    for index, doc_id in enumerate(retrieved_ids):
        if doc_id in relevant_ids:
            return 1.0 / (index + 1)
    return 0.0


def ndcg_at_k(retrieved_ids: list, relevant_ids: set, k: int) -> float:
    """nDCG@k binario (relevancia 0/1)."""
    dcg = 0.0
    for position, doc_id in enumerate(retrieved_ids[:k]):
        if doc_id in relevant_ids:
            dcg += 1.0 / math.log2(position + 2)
    idcg = sum(1.0 / math.log2(pos + 2) for pos in range(min(len(relevant_ids), k)))
    return dcg / idcg if idcg > 0 else 0.0


def context_precision(
    retrieved_ids: list,
    relevant_ids: set,
    *,
    k: int | None = None,
) -> float:
    """Fracción del contexto recuperado que es relevante (brief: context precision)."""
    top = retrieved_ids if k is None else retrieved_ids[:k]
    if not top:
        return 0.0
    return len(set(top) & relevant_ids) / len(top)


def reranker_lift(
    base_recall: float,
    reranked_recall: float,
) -> float:
    """Mejora relativa del recall del reranker (0 cuando no hay base)."""
    if base_recall <= 0:
        return 0.0
    return (reranked_recall - base_recall) / base_recall


@dataclass(frozen=True, kw_only=True)
class RetrievalEvaluation:
    query: str
    relevant_docs: tuple[UUID, ...]
    retrieved_docs: tuple[UUID, ...]
    k: int = 10

    @property
    def recall(self) -> float:
        return recall_at_k(self.retrieved_docs, set(self.relevant_docs), self.k)

    @property
    def precision(self) -> float:
        return precision_at_k(self.retrieved_docs, set(self.relevant_docs), self.k)

    @property
    def mrr(self) -> float:
        return mean_reciprocal_rank(self.retrieved_docs, set(self.relevant_docs))

    @property
    def ndcg(self) -> float:
        return ndcg_at_k(self.retrieved_docs, set(self.relevant_docs), self.k)

    @property
    def context_recall(self) -> float:
        return self.recall

    @property
    def context_precision(self) -> float:
        return precision_at_k(self.retrieved_docs, set(self.relevant_docs), self.k)

    def to_dict(self) -> dict:
        return {
            "k": self.k,
            "recall_at_k": round(self.recall, 4),
            "precision_at_k": round(self.precision, 4),
            "mrr": round(self.mrr, 4),
            "ndcg_at_k": round(self.ndcg, 4),
        }


# ---------------------------------------------------------------------------
# Answer metrics  (sobre GroundedAnswer)
# ---------------------------------------------------------------------------

def groundedness(answer: GroundedAnswer) -> float:
    """Proporción de claims verificados (SUPPORTED/PARTIALLY_SUPPORTED)."""
    if not answer.claims:
        return 0.0
    verified = sum(1 for c in answer.claims if c.verified)
    return verified / len(answer.claims)


def citation_precision(answer: GroundedAnswer, cited_ids: set[UUID]) -> float:
    """Fracción de citas cuyo documento está en el conjunto esperado."""
    citations = answer.citations
    if not citations:
        return 0.0
    hits = sum(
        1 for c in citations if c.document_id is not None and c.document_id in cited_ids
    )
    return hits / len(citations)


def citation_recall(answer: GroundedAnswer, cited_ids: set[UUID]) -> float:
    """Fracción del esperado (cited_ids) cubierto por las citas emitidas."""
    if not cited_ids:
        return 0.0
    emitted = {c.document_id for c in answer.citations if c.document_id is not None}
    return len(emitted & cited_ids) / len(cited_ids)


def abstention_correctness(answer: GroundedAnswer, expected_unsupported: tuple[str, ...]) -> float:
    """1.0 si todos los claims esperados como no soportados están UNSUPPORTED."""
    unsupported = {c.text for c in answer.claims if c.status is ClaimStatus.UNSUPPORTED}
    expected = set(expected_unsupported)
    if not expected:
        return 1.0
    hits = len(unsupported & expected)
    return hits / len(expected)


def conflict_detection(answer: GroundedAnswer) -> int:
    """Número de conflictos detectados por el pipeline (CONFLICTED claims)."""
    return sum(1 for c in answer.claims if c.status is ClaimStatus.CONFLICTED)


@dataclass(frozen=True, kw_only=True)
class AnswerEvaluation:
    question: str
    answer: GroundedAnswer
    cited_ids: set[UUID] = field(default_factory=set)
    expected_unsupported: tuple[str, ...] = ()
    judge_groundedness: float | None = None

    @property
    def groundedness(self) -> float:
        return groundedness(self.answer)

    @property
    def citation_precision(self) -> float:
        return citation_precision(self.answer, self.cited_ids)

    @property
    def citation_recall(self) -> float:
        return citation_recall(self.answer, self.cited_ids)

    @property
    def confidence(self) -> float:
        return self.answer.confidence

    @property
    def conflicts(self) -> int:
        return conflict_detection(self.answer)

    @property
    def abstention(self) -> float:
        return abstention_correctness(self.answer, self.expected_unsupported)

    def to_dict(self) -> dict:
        payload = {
            "groundedness": round(self.groundedness, 4),
            "citation_precision": round(self.citation_precision, 4),
            "citation_recall": round(self.citation_recall, 4),
            "answer_confidence": round(self.confidence, 4),
            "conflict_detections": self.conflicts,
            "abstention_correctness": round(self.abstention, 4),
        }
        if self.judge_groundedness is not None:
            payload["judge_groundedness"] = round(self.judge_groundedness, 4)
        return payload
