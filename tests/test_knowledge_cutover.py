# =============================================================================
# LLM Judge V2 (eval) + cutover readiness (Phase H)
# =============================================================================
from __future__ import annotations

import json
from uuid import uuid4

import pytest

from src.core.domain.knowledge_v2 import KnowledgeCorpus
from src.infrastructure.postgres.knowledge_corpora import (
    PostgresKnowledgeCorpusRepository,
)
from src.infrastructure.postgres.knowledge_repos import PostgresSourceRepository
from src.infrastructure.postgres.relational_db import (
    PostgresOrganizationRepository,
    PostgresWorkspaceRepository,
)
from src.infrastructure.postgres.structured_documents import (
    PostgresStructuredDocumentRepository,
)
from src.knowledge.cutover import assess_v2_readiness
from src.knowledge.structure import TextParser
from src.rag.evaluation import V2Evaluator, judge_groundedness, make_llm_judge
from src.rag.evaluation.golden_v2 import golden_set_from_dict
from src.rag.grounding.models import (
    Citation,
    ClaimStatus,
    GroundedAnswer,
    GroundedClaim,
)


class FakeJudgeLLM:
    def __init__(self, content: str | None = None, error: Exception | None = None) -> None:
        self._content = content
        self._error = error

    async def generate(self, prompt, model=None, max_tokens=2048, temperature=0.3, system_prompt=None):
        if self._error is not None:
            raise self._error
        return type(
            "R",
            (),
            {
                "content": self._content,
                "model": model or "fake",
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "total_tokens": 2,
            },
        )()  # type: ignore[return-value]


@pytest.mark.asyncio
async def test_llm_judge_validates_verdicts_and_never_invents():
    payload = json.dumps(
        {
            "claims": [
                {
                    "text": "La comisión es 5%",
                    "verdict": "supported",
                    "justification": "contexto lo dice",
                },
                {
                    "text": "El vuelo dura tres horas",
                    "verdict": "unsupported",
                    "justification": "no aparece",
                },
            ]
        }
    )
    judge = make_llm_judge(FakeJudgeLLM(content=payload))
    verdicts = await judge("¿comisión?", "La comisión es 5%. El vuelo dura tres horas.", ("comisión 5%",))
    assert verdicts is not None
    assert judge_groundedness(verdicts) == pytest.approx(0.5)

    # JSON con verdict inválido → se descarta ese claim, resto se conserva
    bad = json.dumps(
        {"claims": [{"text": "x", "verdict": "inventado", "justification": ""}]}
    )
    judge_bad = make_llm_judge(FakeJudgeLLM(content=bad))
    verdicts_bad = await judge_bad("q", "respuesta", ("ctx",))
    assert verdicts_bad in (None, ())

    # fallo del LLM → judge devuelve None (el evaluador cae al determinista)
    judge_err = make_llm_judge(FakeJudgeLLM(error=RuntimeError("boom")))
    assert await judge_err("q", "a", ("c",)) is None


@pytest.mark.asyncio
async def test_evaluator_integrates_judge_groundedness():
    from src.rag.evaluation.judge_v2 import make_llm_judge as _make

    golden = golden_set_from_dict(
        {
            "name": "g",
            "cases": [
                {
                    "query": "q",
                    "relevant_document_ids": [],
                    "cited_document_ids": [str(uuid4())],
                    "expected_unsupported": [],
                }
            ],
        }
    )

    async def ground(_query: str) -> GroundedAnswer:
        return GroundedAnswer(
            answer="Hecho soportado por el contexto.",
            claims=(
                GroundedClaim(text="Hecho soportado", status=ClaimStatus.SUPPORTED),
            ),
            citations=(Citation(document_name="d.pdf", excerpt="Hecho soportado por el contexto."),),
        )

    judge = _make(
        FakeJudgeLLM(
            content=json.dumps(
                {
                    "claims": [
                        {
                            "text": "Hecho soportado",
                            "verdict": "partially_supported",
                            "justification": "ok",
                        }
                    ]
                }
            )
        )
    )
    evals = await V2Evaluator().evaluate_answers(golden, ground, judge=judge)
    assert len(evals) == 1
    assert evals[0].judge_groundedness == pytest.approx(1.0)
    assert "judge_groundedness" in evals[0].to_dict()


async def _seed_org(ready: bool):
    org_repo = PostgresOrganizationRepository()
    organization = await org_repo.create_organization(uuid4(), f"Cut Org {uuid4().hex[:6]}")
    if not ready:
        return organization
    workspace = await PostgresWorkspaceRepository().create_workspace(
        organization.id, "Ops", "ops"
    )
    corpus_repo = PostgresKnowledgeCorpusRepository()
    corpus = KnowledgeCorpus(
        id=uuid4(),
        organization_id=organization.id,
        workspace_id=workspace.id,
        name="Operaciones",
        slug="operaciones",
    )
    await corpus_repo.create_corpus(corpus)
    source = await PostgresSourceRepository().create_source(
        organization.id, "manual.md", "file", workspace_id=workspace.id
    )
    await corpus_repo.attach_source(organization.id, source.id, corpus.id)
    doc = TextParser().parse(
        "# Manual\n\nComisión 5%.".encode("utf-8"),
        organization_id=organization.id,
        external_id="manual.md",
        source_id=source.id,
    )
    doc.check_consistency()
    await PostgresStructuredDocumentRepository().upsert_document(doc)
    return organization


@pytest.mark.asyncio
async def test_readiness_gate_scoped_and_honest(monkeypatch) -> None:
    empty_org = await _seed_org(ready=False)
    status_empty = await assess_v2_readiness(empty_org.id)
    assert status_empty["ready"] is False
    assert status_empty["counts"]["structured_documents"] == 0

    ready_org = await _seed_org(ready=True)
    from src.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("RAG_KNOWLEDGE_V2_ENABLED", "true")
    get_settings.cache_clear()
    status = await assess_v2_readiness(ready_org.id)
    assert status["counts"]["structured_documents"] == 1
    assert status["counts"]["structured_blocks"] > 0
    assert status["counts"]["knowledge_corpora"] == 1
    assert status["flags"]["enabled"] is True

    # otro tenant: conteos reales en 0 (scoped), nunca fuga
    other = await assess_v2_readiness(uuid4())
    assert other["counts"]["structured_documents"] == 0
