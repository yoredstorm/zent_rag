# =============================================================================
# Enterprise Evaluation V2 — metrics + golden sets + runner
# =============================================================================
from __future__ import annotations

import json
from uuid import uuid4

import pytest

from src.rag.evaluation.golden_v2 import GoldenCase, GoldenSet, golden_set_from_dict, load_golden_set
from src.rag.evaluation.v2_evaluator import V2Evaluator
from src.rag.evaluation.v2_metrics import (
    mean_reciprocal_rank,
    ndcg_at_k,
    recall_at_k,
    reranker_lift,
)
from src.rag.grounding.models import (
    Citation,
    ClaimStatus,
    GroundedAnswer,
    GroundedClaim,
)


def test_retrieval_metrics_are_exact() -> None:
    relevant = {uuid4(), uuid4()}
    retrieved = list(relevant) + [uuid4(), uuid4()]

    assert recall_at_k(retrieved, relevant, k=2) == 1.0
    assert recall_at_k(retrieved, relevant, k=1) == 0.5
    assert mean_reciprocal_rank(retrieved, relevant) == 1.0
    # reversed: primer relevante en posición 2
    assert mean_reciprocal_rank([retrieved[2], retrieved[0], retrieved[1]], relevant) == pytest.approx(0.5)
    assert ndcg_at_k(retrieved, relevant, k=2) == 1.0
    assert reranker_lift(0.5, 0.8) == pytest.approx(0.6)
    assert reranker_lift(0.0, 0.8) == 0.0


def test_golden_set_json_roundtrip(tmp_path) -> None:
    doc_ids = [uuid4(), uuid4()]
    golden = GoldenSet(
        name="ops",
        cases=(
            GoldenCase(
                query="¿comisión?",
                relevant_document_ids=tuple(doc_ids),
                cited_document_ids=(doc_ids[0],),
                expected_unsupported=("vuelo dura tres horas",),
            ),
        ),
    )
    path = tmp_path / "golden.json"
    path.write_text(json.dumps(golden.to_dict()), encoding="utf-8")
    loaded = load_golden_set(path)
    assert loaded.name == "ops"
    assert loaded.cases[0].relevant_document_ids == tuple(doc_ids)
    assert loaded.cases[0].expected_unsupported == ("vuelo dura tres horas",)
    from_dict = golden_set_from_dict(golden.to_dict())
    assert from_dict.cases[0].query == "¿comisión?"


@pytest.mark.asyncio
async def test_v2_evaluator_runs_retrieval_and_answers() -> None:
    doc_a, doc_b = uuid4(), uuid4()
    golden = golden_set_from_dict(
        {
            "name": "demo",
            "cases": [
                {
                    "query": "q1",
                    "relevant_document_ids": [str(doc_a)],
                    "cited_document_ids": [str(doc_a)],
                    "expected_unsupported": ["no en contexto"],
                },
                {
                    "query": "q2",
                    "relevant_document_ids": [str(doc_b)],
                    "cited_document_ids": [],
                    "expected_unsupported": [],
                },
            ],
        }
    )

    ordered = [doc_a, doc_b]

    async def fake_retrieve(query: str):
        return list(ordered), 12.5

    evaluator = V2Evaluator(k=5)
    evaluations, aggregate = await evaluator.evaluate_retrieval(golden, fake_retrieve)
    assert len(evaluations) == 2
    assert aggregate.cases == 2
    assert aggregate.avg_recall_at_k == 1.0
    # q1 mrr=1.0 (posición 1), q2 mrr=0.5 (posición 2) → promedio 0.75
    assert aggregate.avg_mrr == pytest.approx(0.75)
    assert aggregate.avg_latency_ms == pytest.approx(12.5)

    def make_answer(query: str) -> GroundedAnswer:
        supported = query == "q1"
        return GroundedAnswer(
            answer=f"respuesta a {query}",
            claims=(
                GroundedClaim(
                    text="hecho soportado",
                    status=ClaimStatus.SUPPORTED if supported else ClaimStatus.UNSUPPORTED,
                    confidence=0.9,
                ),
            ),
            citations=(
                (Citation(document_id=doc_a, document_name="A.pdf"),)
                if supported
                else ()
            ),
            confidence=1.0 if supported else 0.0,
        )

    async def fake_ground(query: str):
        return make_answer(query)

    answer_evals = await evaluator.evaluate_answers(golden, fake_ground)
    assert len(answer_evals) == 2
    first = answer_evals[0]
    assert first.groundedness == 1.0
    assert first.citation_precision == 1.0
    assert first.citation_recall == 1.0
