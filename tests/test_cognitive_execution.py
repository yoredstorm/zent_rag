# =============================================================================
# Cognitive execution — Phase 4 slice 1 (first specialists)
# =============================================================================
# Ejecuta el DAG planificado con handlers deterministas (librarian, retrieval,
# conflict, fact-check) y LLM solo donde aporta (document_analyst,
# synthesizer). Fakes en memoria: sin DB, sin Qdrant, sin LiteLLM real.
# =============================================================================
from __future__ import annotations

from dataclasses import replace
from uuid import UUID, uuid4

import pytest

from src.core.domain.cognitive import (
    CognitiveBudget,
    CognitiveRunStatus,
    CognitiveScope,
)
from src.core.domain.evidence import ClaimRecord, ClaimVerificationStatus
from src.platform.cognitive.orchestrator import KnowledgeCognitiveOrchestrator

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class FakeCognitiveRepository:
    def __init__(self) -> None:
        self.runs: dict[str, dict] = {}
        self.tasks: dict[str, dict] = {}
        self.messages: list[dict] = []
        self.executions: dict[str, dict] = {}

    async def create_run(self, run):  # pragma: no cover - no usado aquí
        self.runs[str(run.id)] = {"id": str(run.id)}
        return run

    async def save_tasks(self, *, organization_id, tasks):  # pragma: no cover
        return None

    async def get_run(self, organization_id, run_id):
        row = self.runs.get(str(run_id))
        if row and row["organization_id"] == str(organization_id):
            return dict(row)
        return None

    async def list_tasks(self, organization_id, run_id):
        rows = [
            dict(t)
            for t in self.tasks.values()
            if t["run_id"] == str(run_id)
            and t["organization_id"] == str(organization_id)
        ]
        return sorted(rows, key=lambda t: t["position"])

    async def update_run_status(
        self, organization_id, run_id, status, *, plan_patch=None
    ):
        row = self.runs[str(run_id)]
        row["status"] = status.value if hasattr(status, "value") else str(status)
        if plan_patch:
            row["plan"] = {**(row.get("plan") or {}), **plan_patch}

    async def update_task_status(
        self, organization_id, task_id, status, *, result=None, error=None
    ):
        row = self.tasks[str(task_id)]
        row["status"] = status.value if hasattr(status, "value") else str(status)
        row["result"] = result
        row["error"] = error

    async def save_execution(self, organization_id, execution):
        self.executions[str(execution.id)] = {
            "id": str(execution.id),
            "run_id": str(execution.run_id),
            "task_id": str(execution.task_id),
            "agent_id": execution.agent_id,
            "status": execution.status.value,
            "latency_ms": execution.latency_ms,
            "llm_calls": execution.llm_calls,
            "tokens": execution.tokens,
            "cost_usd": execution.cost_usd,
            "error": execution.error,
            "result": execution.result,
        }
        return execution

    async def list_executions(self, organization_id, run_id):
        return [
            dict(e)
            for e in self.executions.values()
            if e["run_id"] == str(run_id)
        ]

    async def append_message(self, organization_id, message):
        self.messages.append(
            {
                "id": str(message.id),
                "run_id": str(message.run_id),
                "message_type": message.type.value,
                "from_agent": message.from_agent,
                "to_agent": message.to_agent,
                "text": message.text,
                "claim_ids": [str(c) for c in message.claim_ids],
                "evidence_ids": [str(e) for e in message.evidence_ids],
            }
        )
        return message

    async def list_messages(self, organization_id, run_id, limit=200):
        return [m for m in self.messages if m["run_id"] == str(run_id)][:limit]


class FakeEvidenceRepo:
    def __init__(self) -> None:
        self.records: dict[UUID, object] = {}

    async def append(self, evidence):
        self.records[evidence.id] = evidence
        return evidence

    async def get(self, organization_id, evidence_id):
        return self.records.get(evidence_id)

    async def list_for_document(self, organization_id, document_id, limit=100):
        return [
            r for r in self.records.values() if r.document_id == document_id
        ][:limit]


class FakeClaimRepo:
    def __init__(self) -> None:
        self.claims: dict[UUID, ClaimRecord] = {}

    async def upsert(self, claim):
        existing = self.claims.get(claim.id)
        if existing is not None:
            claim = replace(claim, evidence_ids=existing.evidence_ids)
        self.claims[claim.id] = claim
        return claim

    async def get(self, organization_id, claim_id):
        return self.claims.get(claim_id)

    async def list_by_subject(self, organization_id, normalized_subject, limit=50):
        return [
            c for c in self.claims.values() if c.normalized_subject == normalized_subject
        ][:limit]

    async def find_conflicting(
        self, organization_id, normalized_subject, normalized_predicate, normalized_object
    ):
        return [
            c
            for c in self.claims.values()
            if c.normalized_subject == normalized_subject
            and c.normalized_predicate == normalized_predicate
            and c.normalized_object != normalized_object
        ]

    async def attach_evidence(self, organization_id, claim_id, evidence_id):
        claim = self.claims[claim_id]
        if evidence_id not in claim.evidence_ids:
            claim = replace(claim, evidence_ids=(*claim.evidence_ids, evidence_id))
            self.claims[claim_id] = claim
        return claim


class FakeEmbedding:
    async def embed(self, text, model=None):
        if isinstance(text, list):
            return [[0.1] * 4 for _ in text]
        return [0.1] * 4


class FakeRetriever:
    def __init__(self) -> None:
        self.calls = 0

    async def retrieve(self, query):
        from src.core.domain.entities import RetrievalChunk, RetrievalContext

        self.calls += 1
        document_id = uuid4()
        return RetrievalContext(
            chunks=[
                RetrievalChunk(
                    document_id=document_id,
                    content="La penalidad del contrato ACME es 5%.",
                    score=0.9,
                    metadata={
                        "source_id": str(uuid4()),
                        "chunk_id": str(uuid4()),
                        "page_start": 18,
                        "section_path": ["5", "5.2"],
                    },
                ),
                RetrievalChunk(
                    document_id=uuid4(),
                    content="La adenda 2025 cambia la penalidad a 7%.",
                    score=0.85,
                    metadata={
                        "source_id": str(uuid4()),
                        "chunk_id": str(uuid4()),
                        "page_start": 3,
                        "section_path": ["2"],
                    },
                ),
            ],
            retrieval_latency_ms=5.0,
        )


_FINDINGS_JSON = """{
  "findings": [
    {"subject": "penalidad contrato ACME", "predicate": "es", "object": "5%",
     "text": "La penalidad del contrato ACME es 5%.", "evidence_indexes": [0]},
    {"subject": "penalidad contrato ACME", "predicate": "es", "object": "7%",
     "text": "La adenda 2025 cambia la penalidad a 7%.", "evidence_indexes": [1]}
  ]
}"""


_L4_FINDINGS_JSON = """{
  "findings": [
    {"subject": "penalidad contrato ACME", "predicate": "es", "object": "5%",
     "text": "La penalidad del contrato ACME es 5%.", "evidence_indexes": [0]},
    {"subject": "penalidad contrato ACME", "predicate": "es", "object": "7%",
     "text": "La adenda 2025 cambia la penalidad a 7%.", "evidence_indexes": [1]},
    {"subject": "clausula de penalidad", "predicate": "aplica", "object": "contrato acme",
     "text": "La penalidad del contrato ACME es 5%.", "evidence_indexes": [0]}
  ]
}"""

_TEMPORAL_FINDINGS_JSON = """{
  "findings": [
    {"subject": "penalidad contrato ACME", "predicate": "es", "object": "5%",
     "text": "La penalidad del contrato ACME es 5%.", "evidence_indexes": [0],
     "temporal_scope": "2024"},
    {"subject": "penalidad contrato ACME", "predicate": "es", "object": "7%",
     "text": "La adenda 2025 cambia la penalidad a 7%.", "evidence_indexes": [1],
     "temporal_scope": "2099"},
    {"subject": "clausula de penalidad", "predicate": "aplica", "object": "contrato acme",
     "text": "La penalidad del contrato ACME es 5%.", "evidence_indexes": [0],
     "temporal_scope": "2024"}
  ]
}"""


class FakeLLM:
    def __init__(self, contents: list[str]) -> None:
        self.contents = contents
        self.calls = 0

    async def generate(self, prompt, **kwargs):
        from src.core.domain.entities import LLMResponse

        idx = min(self.calls, len(self.contents) - 1)
        self.calls += 1
        return LLMResponse(
            content=self.contents[idx],
            model="fake",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
        )

    async def generate_stream(self, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError

    async def embed(self, text, model=None):  # pragma: no cover
        raise NotImplementedError

    async def rerank(self, query, documents, model=None, top_n=None):  # pragma: no cover
        return []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def seed_run(repo: FakeCognitiveRepository, plan) -> None:
    run = plan.run
    repo.runs[str(run.id)] = {
        "id": str(run.id),
        "organization_id": str(run.organization_id),
        "workspace_id": str(run.workspace_id) if run.workspace_id else None,
        "query": run.query,
        "complexity": run.complexity.value,
        "status": run.status.value,
        "budget": run.budget.to_dict(),
        "scope": run.scope,
        "plan": run.plan,
    }
    for task in plan.graph.tasks:
        repo.tasks[str(task.id)] = {
            "id": str(task.id),
            "run_id": str(task.run_id),
            "organization_id": str(run.organization_id),
            "task_key": task.key,
            "description": task.description,
            "agent_id": task.agent_id,
            "status": task.status.value,
            "depends_on": list(task.depends_on),
            "position": task.position,
        }


def make_executor(repo, **deps_overrides):
    from src.platform.cognitive.executor import CognitiveExecutor, SpecialistDeps

    deps = SpecialistDeps(
        llm=deps_overrides.get("llm"),
        embedding=deps_overrides.get("embedding", FakeEmbedding()),
        retriever=deps_overrides.get("retriever"),
        evidence_repo=deps_overrides.get("evidence_repo"),
        claim_repo=deps_overrides.get("claim_repo"),
        sql_executor=deps_overrides.get("sql_executor"),
        authority_resolver=deps_overrides.get("authority_resolver"),
    )
    return CognitiveExecutor(repository=repo, deps=deps, task_timeout_seconds=10)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_execute_l1_runs_librarian_and_retrieval() -> None:
    repo = FakeCognitiveRepository()
    evidence_repo = FakeEvidenceRepo()
    plan = KnowledgeCognitiveOrchestrator().plan(
        query="¿Dónde aparece la política de vacaciones?",
        scope=CognitiveScope(organization_id=uuid4()),
    )
    seed_run(repo, plan)
    executor = make_executor(
        repo, retriever=FakeRetriever(), evidence_repo=evidence_repo
    )

    result = await executor.execute_run(
        organization_id=plan.run.organization_id,
        run_id=plan.run.id,
        scope=CognitiveScope(organization_id=plan.run.organization_id),
    )

    assert result["run"]["status"] == CognitiveRunStatus.COMPLETED.value
    statuses = {t["task_key"]: t["status"] for t in result["tasks"]}
    assert statuses == {"locate_sources": "completed", "retrieve": "completed"}
    assert len(evidence_repo.records) == 2
    message_types = {m["message_type"] for m in result["messages"]}
    assert {"handoff", "evidence"} <= message_types


@pytest.mark.asyncio
async def test_execute_l2_creates_claims_and_final_answer() -> None:
    repo = FakeCognitiveRepository()
    evidence_repo = FakeEvidenceRepo()
    claim_repo = FakeClaimRepo()
    plan = KnowledgeCognitiveOrchestrator().plan(
        query="Resume las obligaciones de este contrato.",
        scope=CognitiveScope(organization_id=uuid4()),
    )
    seed_run(repo, plan)
    llm = FakeLLM([_FINDINGS_JSON, "La penalidad vigente es 7% según la adenda."])
    executor = make_executor(
        repo,
        llm=llm,
        retriever=FakeRetriever(),
        evidence_repo=evidence_repo,
        claim_repo=claim_repo,
    )

    result = await executor.execute_run(
        organization_id=plan.run.organization_id,
        run_id=plan.run.id,
        scope=CognitiveScope(organization_id=plan.run.organization_id),
    )

    assert result["run"]["status"] == CognitiveRunStatus.COMPLETED.value
    assert len(claim_repo.claims) == 2
    assert all(c.status is ClaimVerificationStatus.PROPOSED for c in claim_repo.claims.values())
    assert all(c.evidence_ids for c in claim_repo.claims.values())
    assert result["run"]["plan"]["final_answer"] == (
        "La penalidad vigente es 7% según la adenda."
    )
    types = [m["message_type"] for m in result["messages"]]
    assert "finding" in types
    assert "final_candidate" in types


@pytest.mark.asyncio
async def test_execute_l4_detects_conflicts_verifies_and_skips_unimplemented() -> None:
    repo = FakeCognitiveRepository()
    evidence_repo = FakeEvidenceRepo()
    claim_repo = FakeClaimRepo()
    plan = KnowledgeCognitiveOrchestrator().plan(
        query=(
            "Analiza todos los contratos de proveedores, identifica riesgos, "
            "contradicciones y cambios en los últimos tres años."
        ),
        scope=CognitiveScope(organization_id=uuid4()),
    )
    seed_run(repo, plan)
    llm = FakeLLM([_L4_FINDINGS_JSON, "Respuesta final con evidencia."])
    executor = make_executor(
        repo,
        llm=llm,
        retriever=FakeRetriever(),
        evidence_repo=evidence_repo,
        claim_repo=claim_repo,
    )

    result = await executor.execute_run(
        organization_id=plan.run.organization_id,
        run_id=plan.run.id,
        scope=CognitiveScope(organization_id=plan.run.organization_id),
    )

    assert result["run"]["status"] == CognitiveRunStatus.COMPLETED.value
    statuses = {t["task_key"]: t["status"] for t in result["tasks"]}
    assert statuses["detect_conflicts"] == "completed"
    assert statuses["verify"] == "completed"
    assert statuses["resolve_temporal"] == "completed"
    for key in ("analyze_policy", "analyze_relationships", "critique"):
        assert statuses[key] == "skipped"
    assert any(
        c.status is ClaimVerificationStatus.CONFLICTED for c in claim_repo.claims.values()
    )
    verified = [c for c in claim_repo.claims.values()]
    assert any(
        c.status
        in (ClaimVerificationStatus.SUPPORTED, ClaimVerificationStatus.PARTIALLY_SUPPORTED)
        for c in verified
    )
    assert any(m["message_type"] == "conflict" for m in result["messages"])


@pytest.mark.asyncio
async def test_execute_fails_run_when_budget_exceeded() -> None:
    repo = FakeCognitiveRepository()
    evidence_repo = FakeEvidenceRepo()
    claim_repo = FakeClaimRepo()
    strict_budget = replace(CognitiveBudget(max_tokens=1), max_agents=4)
    plan = KnowledgeCognitiveOrchestrator().plan(
        query="Resume las obligaciones de este contrato.",
        scope=CognitiveScope(organization_id=uuid4()),
        budget=strict_budget,
    )
    seed_run(repo, plan)
    executor = make_executor(
        repo,
        llm=FakeLLM([_FINDINGS_JSON, "fin"]),
        retriever=FakeRetriever(),
        evidence_repo=evidence_repo,
        claim_repo=claim_repo,
    )

    result = await executor.execute_run(
        organization_id=plan.run.organization_id,
        run_id=plan.run.id,
        scope=CognitiveScope(organization_id=plan.run.organization_id),
    )

    assert result["run"]["status"] == CognitiveRunStatus.FAILED.value
    assert "budget" in (result["run"]["plan"].get("error") or "").lower()


@pytest.mark.asyncio
async def test_execute_temporal_conflict_intelligence() -> None:
    repo = FakeCognitiveRepository()
    evidence_repo = FakeEvidenceRepo()
    claim_repo = FakeClaimRepo()
    plan = KnowledgeCognitiveOrchestrator().plan(
        query=(
            "Analiza todos los contratos de proveedores, identifica riesgos, "
            "contradicciones y cambios en los últimos tres años."
        ),
        scope=CognitiveScope(organization_id=uuid4()),
    )
    seed_run(repo, plan)

    async def authority_resolver(organization_id, concept):
        return "authoritative"

    executor = make_executor(
        repo,
        llm=FakeLLM([_TEMPORAL_FINDINGS_JSON, "Respuesta final temporal."]),
        retriever=FakeRetriever(),
        evidence_repo=evidence_repo,
        claim_repo=claim_repo,
        authority_resolver=authority_resolver,
    )

    result = await executor.execute_run(
        organization_id=plan.run.organization_id,
        run_id=plan.run.id,
        scope=CognitiveScope(organization_id=plan.run.organization_id),
    )

    assert result["run"]["status"] == CognitiveRunStatus.COMPLETED.value
    statuses = {t["task_key"]: t["status"] for t in result["tasks"]}
    assert statuses["resolve_temporal"] == "completed"
    assert statuses["detect_conflicts"] == "completed"
    assert statuses["verify"] == "completed"

    temporal_exec = next(
        e for e in result["executions"] if e["agent_id"] == "temporal_analyst"
    )
    assert temporal_exec["status"] == "completed"
    assert temporal_exec["result"]["historical"] == 2
    assert temporal_exec["result"]["current"] == 1

    conflicts = result["run"]["plan"]["conflicts"]
    assert conflicts
    assert conflicts[0]["conflict_type"] == "temporal_update"
    assert conflicts[0]["resolution"]["winning_claim_id"]
    assert conflicts[0]["resolution"]["requires_review"] is True

    # el claim histórico sin conflicto queda OUTDATED (no mezcla versiones)
    assert any(
        c.status is ClaimVerificationStatus.OUTDATED
        for c in claim_repo.claims.values()
    )


@pytest.mark.asyncio
async def test_execute_without_deps_skips_handlers_gracefully() -> None:
    repo = FakeCognitiveRepository()
    plan = KnowledgeCognitiveOrchestrator().plan(
        query="¿Dónde aparece la política de vacaciones?",
        scope=CognitiveScope(organization_id=uuid4()),
    )
    seed_run(repo, plan)
    executor = make_executor(repo)  # sin retriever/LLM

    result = await executor.execute_run(
        organization_id=plan.run.organization_id,
        run_id=plan.run.id,
        scope=CognitiveScope(organization_id=plan.run.organization_id),
    )

    assert result["run"]["status"] == CognitiveRunStatus.COMPLETED.value
    statuses = {t["task_key"]: t["status"] for t in result["tasks"]}
    assert statuses["locate_sources"] == "completed"  # determinista
    assert statuses["retrieve"] == "skipped"
    executions = result["executions"]
    assert len(executions) == 2
