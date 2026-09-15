# =============================================================================
# Cognitive Workflows — Fase 3: INVESTIGATE vía Cognitive OS.
#
# Scope derivado del NodeContext, budget del nodo, gate por flag, permiso
# knowledge:write y mapeo de answer/findings/claims/evidence/conflicts.
# =============================================================================
from __future__ import annotations

import hashlib
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from tests.test_workflows import _create_org, _headers, _owner_session


class _FakeCognitiveService:
    def __init__(self, run_id: UUID | None = None, *, plan: bool = True) -> None:
        self.run_id = run_id or uuid4()
        self.plan = plan
        self.calls: list[dict] = []

    async def create_run(self, **kwargs):  # noqa: ANN003
        self.calls.append(kwargs)
        if not self.plan:
            return {}
        return {"run": {"id": str(self.run_id), "status": "planned"}, "tasks": [], "agents": []}


class _FakeCognitiveExecutor:
    def __init__(self, run_id: UUID, *, claim_id: str, evidence_id: str) -> None:
        self.run_id = run_id
        self.claim_id = claim_id
        self.evidence_id = evidence_id
        self.calls: list[dict] = []

    async def execute_run(self, **kwargs):  # noqa: ANN003
        self.calls.append(kwargs)
        return {
            "run": {
                "id": str(self.run_id),
                "status": "completed",
                "failure_mode": None,
                "plan_patch": {
                    "conflicts": [{"subject": "descuento", "severity": "high", "objects": ["15%", "20%"]}]
                },
            },
            "tasks": [],
            "messages": [
                {"type": "finding", "content": "Hay dos políticas distintas."},
                {
                    "type": "final_candidate",
                    "content": "La política vigente permite 20%.",
                    "claim_ids": [self.claim_id],
                    "evidence_ids": [self.evidence_id],
                },
            ],
            "executions": [],
            "metrics": {
                "evidence_count": 1,
                "claims": 1,
                "has_answer": True,
                "tokens": 321,
                "cost_usd": 0.02,
                "specialists": 3,
                "confidence": 0.8,
            },
        }


def _node(nid: str, ntype: str, config: dict | None = None, **extra) -> dict:
    node: dict = {
        "id": nid,
        "type": ntype,
        "label": ntype,
        "config": config or {},
        "input_ports": [{"name": "in", "type": "json"}],
        "output_ports": [{"name": "out", "type": "json"}],
        "retry_policy": {"max_attempts": 1},
        "timeout_ms": 60_000,
        "error_policy": "fail",
    }
    node.update(extra)
    return node


def _edge(eid: str, frm: str, to: str, **extra) -> dict:
    edge: dict = {"id": eid, "from_node": frm, "from_port": "out", "to_node": to, "to_port": "in"}
    edge.update(extra)
    return edge


def _graph(nodes: list[dict], edges: list[dict], entrypoints: list[str]) -> dict:
    return {
        "workflow_version": 2,
        "nodes": nodes,
        "edges": edges,
        "variables": {},
        "entrypoints": entrypoints,
        "metadata": {},
    }


@pytest.mark.asyncio
async def test_investigate_runs_cognitive_with_scope_and_budget(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    org = await _create_org(async_client, "CW Investigate")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    organization_id = UUID(org["organization_id"])
    headers = _headers(org)

    kb = await async_client.post(
        "/api/v1/knowledge-bases",
        json={"name": f"kb-{uuid4().hex[:8]}"},
        headers=headers,
    )
    assert kb.status_code == 201, kb.text
    kb_id = kb.json()["id"]

    from src.api.deps import (
        get_claim_ledger_repo,
        get_cognitive_executor,
        get_cognitive_service,
        get_evidence_ledger_repo,
    )
    from src.api.main import app
    from src.core.config import get_settings
    from src.core.domain.catalog import CatalogProvenance
    from src.core.domain.evidence import ClaimRecord, ClaimVerificationStatus, EvidenceRecord

    excerpt = "La política permite un descuento máximo del 15%."
    evidence = await get_evidence_ledger_repo().append(
        EvidenceRecord(
            organization_id=organization_id,
            excerpt=excerpt,
            content_hash=hashlib.sha256(excerpt.encode()).hexdigest(),
        )
    )
    claim = await get_claim_ledger_repo().upsert(
        ClaimRecord(
            organization_id=organization_id,
            text="descuento máximo: 15%",
            normalized_subject="descuento maximo",
            normalized_predicate="maximo",
            normalized_object="15%",
            status=ClaimVerificationStatus.PROPOSED,
            confidence=0.8,
            provenance=CatalogProvenance.INFERRED,
        )
    )

    cognitive_run_id = uuid4()
    service = _FakeCognitiveService(cognitive_run_id)
    executor = _FakeCognitiveExecutor(
        cognitive_run_id, claim_id=str(claim.id), evidence_id=str(evidence.id)
    )
    app.dependency_overrides[get_cognitive_service] = lambda: service
    app.dependency_overrides[get_cognitive_executor] = lambda: executor
    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "limited")

    graph = _graph(
        [
            _node("t", "trigger_webhook"),
            _node(
                "kb",
                "kb_query",
                {
                    "operation": "investigate",
                    "knowledge_base_id": kb_id,
                    "query": "¿hay conflicto entre políticas de descuento?",
                    "budget": {"max_llm_calls": 5, "max_cost_usd": 0.5},
                },
            ),
        ],
        [_edge("e1", "t", "kb")],
        ["t"],
    )
    created = await async_client.post(
        "/api/v1/workflows",
        headers={**headers, "Idempotency-Key": f"ci-{uuid4().hex}"},
        json={"name": "CW Investigate", "trigger_type": "webhook", "graph": graph},
    )
    assert created.status_code == 200, created.text
    run = await async_client.post(
        f"/api/v1/workflows/{created.json()['workflow_id']}/run",
        headers={**headers, "Idempotency-Key": f"cir-{uuid4().hex}"},
        json={"payload": {}, "simulate": True},
    )
    assert run.status_code == 200, run.text
    body = run.json()
    output = body["result"]["structured_output"]["nodes"]["kb"]["output"]

    assert output["status"] == "ok", output
    assert output["answer"] == "La política vigente permite 20%."
    assert output["findings"][0]["text"] == "Hay dos políticas distintas."
    assert output["claim_ids"] == [str(claim.id)]
    assert output["evidence_ids"] == [str(evidence.id)]
    assert output["has_conflicts"] is True
    assert output["metrics"]["tokens"] == 321
    assert output["cognitive_run_id"] == str(cognitive_run_id)
    assert output["method"] == "cognitive_os"

    # Scope y budget derivados del run/nodo.
    create_kwargs = service.calls[0]
    assert create_kwargs["scope"].organization_id == organization_id
    assert str(create_kwargs["scope"].knowledge_base_id) == kb_id
    assert create_kwargs["scope"].user_id is not None  # actor del run
    assert create_kwargs["budget"].max_llm_calls == 5
    assert create_kwargs["budget"].max_cost_usd == 0.5
    assert executor.calls[0]["run_id"] == cognitive_run_id

    # Contexto: knowledge + refs reales validadas por org.
    context = body["result"]["context"]
    assert context["knowledge"]["kb"]["value"]["operation"] == "investigate"
    assert context["evidence_refs"]
    assert context["claim_refs"]


@pytest.mark.asyncio
async def test_investigate_requires_knowledge_write_permission() -> None:
    from src.platform.workflows.ir import WorkflowNode
    from src.platform.workflows.nodes import NodeContext, NodeTypeDef, _exec_kb_query
    from src.platform.workflows.runtime import ExecutionContext

    execution = ExecutionContext(
        organization_id=uuid4(),
        workflow_id=uuid4(),
        run_id=uuid4(),
        actor_type="user",
        trigger_type="manual",
        permissions=frozenset(),
    )
    rctx = NodeContext(
        execution=execution,
        node=WorkflowNode(
            id="kb",
            type="kb_query",
            config={"operation": "investigate", "query": "investiga"},
        ),
        node_type=NodeTypeDef(
            node_type="kb_query",
            version=1,
            label="Consultar knowledge base",
            category="data",
            risk_level="normal",
            capabilities=frozenset(),
        ),
        node_id="kb",
        inputs={},
        trigger={},
        payload={},
        variables={},
        node_outputs={},
        idempotency_key=None,
    )
    outcome = await _exec_kb_query(rctx)
    assert outcome.error is None
    assert outcome.output["status"] == "permission_restricted"
    assert outcome.output["reason_codes"] == ["requires_knowledge_write"]


@pytest.mark.asyncio
async def test_investigate_plan_failure_is_typed(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.api.deps import get_cognitive_service
    from src.api.main import app
    from src.core.config import get_settings
    from src.platform.workflows.ir import WorkflowNode
    from src.platform.workflows.nodes import NodeContext, NodeTypeDef, _exec_kb_query
    from src.platform.workflows.runtime import ExecutionContext

    app.dependency_overrides[get_cognitive_service] = lambda: _FakeCognitiveService(plan=False)
    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "limited")

    execution = ExecutionContext(
        organization_id=uuid4(),
        workflow_id=uuid4(),
        run_id=uuid4(),
        actor_type="user",
        trigger_type="manual",
        permissions=frozenset({"knowledge:write"}),
    )
    rctx = NodeContext(
        execution=execution,
        node=WorkflowNode(
            id="kb",
            type="kb_query",
            config={"operation": "investigate", "query": "investiga"},
        ),
        node_type=NodeTypeDef(
            node_type="kb_query",
            version=1,
            label="Consultar knowledge base",
            category="data",
            risk_level="normal",
            capabilities=frozenset(),
        ),
        node_id="kb",
        inputs={},
        trigger={},
        payload={},
        variables={},
        node_outputs={},
        idempotency_key=None,
    )
    outcome = await _exec_kb_query(rctx)
    assert outcome.error is None
    assert outcome.output["status"] == "insufficient_evidence"
    assert outcome.output["reason_codes"] == ["cognitive_plan_failed"]
