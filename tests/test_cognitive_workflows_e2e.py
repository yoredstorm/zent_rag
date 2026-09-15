# =============================================================================
# Cognitive Workflows — E2E 1–3 (brief §31–§33).
#
# 1. Venta > 40k: condition → (datos ∥ conocimiento) → join → agente →
#    condition → aprobación humana con evidencia → notify.
# 2. Contrato nuevo: compare + conflicts → condition → agente legal → notify.
# 3. Diario: schedule → datos → conocimiento → agente → business_result → notify.
# =============================================================================
from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from src.core.domain.entities import RetrievalChunk
from src.rag.retrieval.structured import AssembledContext, V2RetrievalOptions
from tests.test_workflows import _create_org, _headers, _owner_session

COND_PORTS = [
    {"name": "out", "type": "boolean"},
    {"name": "then", "type": "json"},
    {"name": "else", "type": "json"},
]


class _FakeRetriever:
    def __init__(self, by_query: dict[str, RetrievalChunk]) -> None:
        self._by_query = by_query

    async def retrieve(self, query, options=None):  # noqa: ANN001
        chunk = self._by_query.get(query.query) or next(iter(self._by_query.values()))
        return AssembledContext(
            children=(chunk,),
            parents=(),
            context=(chunk,),
            options=options or V2RetrievalOptions(),
        )


class _FakeLLM:
    def __init__(self, content: str) -> None:
        self.content = content

    async def generate(self, prompt, **kwargs):  # noqa: ANN001, ANN003
        return SimpleNamespace(
            content=self.content,
            model="fake",
            prompt_tokens=40,
            completion_tokens=20,
            total_tokens=60,
            latency_ms=2.0,
            finish_reason="stop",
        )


class _FakeAgentRuntime:
    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.requests: list = []

    async def run(self, request):  # noqa: ANN001
        from src.agents.runtime.agent_runtime import AgentRunResult

        self.requests.append(request)
        return AgentRunResult(
            run_id=uuid4(),
            agent_id=request.agent.id,
            organization_id=request.agent.organization_id,
            status="completed",
            answer=self.answer,
            message=request.message,
            user_id=request.user_id,
            role=request.role,
            total_latency_ms=5.0,
            total_tokens=30,
            cost=0.0002,
            model="fake",
            provider="fake",
        )


class _FakeOrchestrator:
    def __init__(self, organization_id: UUID) -> None:
        self.organization_id = organization_id

    async def execute(self, **kwargs):  # noqa: ANN003
        return SimpleNamespace(
            query_id=uuid4(),
            organization_id=self.organization_id,
            llm_response=SimpleNamespace(content="El cliente gastó 45000."),
            method="sql",
            sql_query="SELECT total FROM ventas",
            total_latency_ms=20.0,
            structured_output={
                "rows": [{"cliente": "ACME", "total": 45000}],
                "columns": ["cliente", "total"],
                "row_count": 1,
                "truncated": False,
            },
            answerability=SimpleNamespace(
                status="answerable",
                answerable=True,
                confidence_level="high",
                reason_codes=["data_found"],
                evidence_ids=[str(uuid4())],
                sources=["managed_db:ventas"],
            ),
            retrieval_context=None,
            lazy_ingested=False,
            lazy_rows_indexed=0,
        )


def _chunk(text: str, name: str = "doc.pdf") -> RetrievalChunk:
    return RetrievalChunk(
        document_id=uuid4(),
        content=text,
        score=0.9,
        metadata={
            "source_id": str(uuid4()),
            "document_id": str(uuid4()),
            "filename": name,
            "page_start": "1",
            "chunk_id": str(uuid4()),
        },
    )


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


async def _setup(async_client: AsyncClient, name: str) -> tuple[dict, str, str]:
    org = await _create_org(async_client, name)
    org["session"] = await _owner_session(async_client, org["organization_id"])
    kb = await async_client.post(
        "/api/v1/knowledge-bases",
        json={"name": f"kb-{uuid4().hex[:6]}"},
        headers=_headers(org),
    )
    assert kb.status_code == 201, kb.text
    agent = await async_client.post(
        "/api/v1/agents",
        headers=_headers(org),
        json={"name": "Analista", "system_prompt": "responde corto", "tools": []},
    )
    assert agent.status_code == 201, agent.text
    return org, kb.json()["id"], agent.json()["id"]


def _overrides(*, retriever, llm=None, runtime=None, orchestrator=None, v2=True, monkeypatch=None):
    from src.api.deps import (
        get_agent_runtime,
        get_llm_provider,
        get_rag_orchestrator,
        get_structured_retriever,
    )
    from src.api.main import app
    from src.core.config import get_settings

    app.dependency_overrides[get_structured_retriever] = lambda: retriever
    if llm is not None:
        app.dependency_overrides[get_llm_provider] = lambda: llm
    if runtime is not None:
        app.dependency_overrides[get_agent_runtime] = lambda: runtime
    if orchestrator is not None:
        app.dependency_overrides[get_rag_orchestrator] = lambda: orchestrator
    if monkeypatch is not None:
        monkeypatch.setattr(get_settings(), "KNOWLEDGE_V2_ENABLED", v2)


async def _create_workflow(async_client: AsyncClient, org: dict, graph: dict, name: str) -> str:
    created = await async_client.post(
        "/api/v1/workflows",
        headers={**_headers(org), "Idempotency-Key": f"e2e-{uuid4().hex}"},
        json={"name": name, "trigger_type": "event", "graph": graph},
    )
    assert created.status_code == 200, created.text
    return created.json()["workflow_id"]


@pytest.mark.asyncio
async def test_e2e_sales_over_threshold_with_approval(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    org, kb_id, agent_id = await _setup(async_client, "E2E Sales")
    headers = _headers(org)
    retriever = _FakeRetriever(
        {
            "política de descuentos": _chunk(
                "La política permite un descuento máximo del 15%.", "politica.pdf"
            )
        }
    )
    runtime = _FakeAgentRuntime(
        '{"risk": "HIGH", "reason": "monto alto", "recommendation": "aprobar", '
        '"confidence": 0.9, "requires_review": true}'
    )
    from src.api.deps import get_agent_runtime, get_rag_orchestrator, get_structured_retriever
    from src.api.main import app
    from src.core.config import get_settings

    app.dependency_overrides[get_structured_retriever] = lambda: retriever
    app.dependency_overrides[get_agent_runtime] = lambda: runtime
    app.dependency_overrides[get_rag_orchestrator] = lambda: _FakeOrchestrator(
        UUID(org["organization_id"])
    )
    monkeypatch.setattr(get_settings(), "KNOWLEDGE_V2_ENABLED", True)

    graph = _graph(
        [
            _node("t", "trigger_event", {"event_type": "sales.closed", "filters": {}}),
            _node(
                "cond1",
                "condition",
                {"field": "trigger.total", "operator": ">", "value": 40000},
                output_ports=COND_PORTS,
            ),
            _node("q", "query_business_data", {"ask": "gasto del cliente ACME"}, label="Datos de venta"),
            _node(
                "kb",
                "kb_query",
                {"knowledge_base_id": kb_id, "query": "política de descuentos"},
                label="Política comercial",
            ),
            _node("j", "join", label="Unir"),
            _node(
                "ask",
                "llm",
                {
                    "agent_id": agent_id,
                    "prompt": "Analiza la venta por {{trigger.total}} y decide",
                    "output_type": "business_assessment",
                    "context_mode": "auto",
                },
                label="Análisis del agente",
            ),
            _node(
                "cond2",
                "condition",
                {"field": "{{nodes.ask.output.risk}}", "operator": "==", "value": "HIGH"},
                output_ports=COND_PORTS,
            ),
            _node("ha", "human_approval", {"action": "Aprobar venta de alto monto"}),
            _node("n", "notify", {"channel": "in_app", "title": "ok", "message": "ok"}),
        ],
        [
            _edge("e1", "t", "cond1"),
            _edge("e2", "cond1", "q", from_port="then"),
            _edge("e3", "cond1", "kb", from_port="then"),
            _edge("e4", "q", "j"),
            _edge("e5", "kb", "j"),
            _edge("e6", "j", "ask"),
            _edge("e7", "ask", "cond2"),
            _edge("e8", "cond2", "ha", from_port="then"),
            _edge("e9", "ha", "n"),
        ],
        ["t"],
    )
    wid = await _create_workflow(async_client, org, graph, "E2E Sales")

    run = await async_client.post(
        f"/api/v1/workflows/{wid}/run",
        headers={**headers, "Idempotency-Key": f"e2er-{uuid4().hex}"},
        json={"payload": {"total": 45000, "customer": "ACME"}},
    )
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["status"] == "pending_approval", body
    run_id = body["run_id"]

    # El agente recibió contexto fusionado (datos + conocimiento).
    request = runtime.requests[0]
    assert request.context and "data" in request.context and "knowledge" in request.context

    approvals = await async_client.get(
        f"/api/v1/workflows/runs/{run_id}/approvals", headers=headers
    )
    approval = approvals.json()["approvals"][0]
    context = approval["context"]
    assert context["decisions"][0]["risk"] == "HIGH"
    assert len(context["evidence_refs"]) >= 2
    assert context["citations"][0]["document_name"] == "politica.pdf"

    decided = await async_client.post(
        f"/api/v1/workflows/runs/{run_id}/approvals/{approval['id']}/decide",
        headers={**headers, "Idempotency-Key": f"e2ed-{uuid4().hex}"},
        json={"decision": "approved", "comment": "ok"},
    )
    assert decided.status_code == 200, decided.text

    detail = await async_client.get(f"/api/v1/workflows/runs/{run_id}", headers=headers)
    inspector = detail.json()
    assert inspector["status"] != "pending_approval", inspector["status"]
    story = " ".join(inspector["story"])
    assert "El agente analizó la situación: HIGH" in story
    assert "aprobación humana: Aprobar venta de alto monto" in story
    assert inspector["decisions"][0]["value"]["risk"] == "HIGH"


@pytest.mark.asyncio
async def test_e2e_new_contract_conflicts(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    org, kb_id, agent_id = await _setup(async_client, "E2E Contract")
    headers = _headers(org)
    organization_id = UUID(org["organization_id"])

    from src.api.deps import get_claim_ledger_repo
    from src.core.domain.catalog import CatalogProvenance
    from src.core.domain.evidence import ClaimRecord, ClaimVerificationStatus

    repo = get_claim_ledger_repo()
    for value in ("15%", "20%"):
        await repo.upsert(
            ClaimRecord(
                organization_id=organization_id,
                text=f"descuento máximo: {value}",
                normalized_subject="descuento maximo",
                normalized_predicate="maximo",
                normalized_object=value,
                status=ClaimVerificationStatus.PROPOSED,
                confidence=0.8,
                provenance=CatalogProvenance.INFERRED,
            )
        )

    retriever = _FakeRetriever(
        {
            "contrato nuevo": _chunk("El contrato permite descuento máximo del 25%.", "contrato.pdf"),
            "política vigente": _chunk("La política permite descuento máximo del 15%.", "politica.pdf"),
        }
    )
    llm = _FakeLLM(
        '{"differences": [{"topic": "descuento", "left": "25%", "right": "15%", "impact": "alto"}]}'
    )
    legal = _FakeAgentRuntime(
        '{"decision": "revisar", "reason": "contradicción de descuento", "confidence": 0.85}'
    )

    from src.api.deps import get_agent_runtime, get_llm_provider, get_structured_retriever
    from src.api.main import app
    from src.core.config import get_settings

    app.dependency_overrides[get_structured_retriever] = lambda: retriever
    app.dependency_overrides[get_llm_provider] = lambda: llm
    app.dependency_overrides[get_agent_runtime] = lambda: legal
    monkeypatch.setattr(get_settings(), "KNOWLEDGE_V2_ENABLED", True)

    # El kb_query usa el mismo provider LLM para compare y el agente usa runtime.
    graph = _graph(
        [
            _node("t", "trigger_event", {"event_type": "document.processed", "filters": {}}),
            _node(
                "cmp",
                "kb_query",
                {
                    "operation": "compare",
                    "knowledge_base_id": kb_id,
                    "compare_left": "contrato nuevo",
                    "compare_right": "política vigente",
                },
                label="Comparar",
            ),
            _node(
                "cc",
                "kb_query",
                {"operation": "check_conflicts", "subject": "descuento maximo"},
                label="Contradicciones",
            ),
            _node(
                "cond",
                "condition",
                {"field": "{{nodes.cc.output.has_conflicts}}", "operator": "==", "value": True},
                output_ports=COND_PORTS,
            ),
            _node(
                "legal",
                "llm",
                {
                    "agent_id": agent_id,
                    "prompt": "Analiza las contradicciones del contrato",
                    "output_type": "decision",
                },
                label="Análisis legal",
            ),
            _node("n", "notify", {"channel": "in_app", "title": "Contrato", "message": "ok"}),
        ],
        [
            _edge("e1", "t", "cmp"),
            _edge("e2", "cmp", "cc"),
            _edge("e3", "cc", "cond"),
            _edge("e4", "cond", "legal", from_port="then"),
            _edge("e5", "legal", "n"),
        ],
        ["t"],
    )
    wid = await _create_workflow(async_client, org, graph, "E2E Contract")

    run = await async_client.post(
        f"/api/v1/workflows/{wid}/run",
        headers={**headers, "Idempotency-Key": f"e2ec-{uuid4().hex}"},
        json={"payload": {"document": "contrato.pdf"}, "simulate": True},
    )
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["status"] == "simulated", body
    nodes = body["result"]["structured_output"]["nodes"]
    assert nodes["cmp"]["output"]["differences"][0]["topic"] == "descuento"
    assert nodes["cc"]["output"]["has_conflicts"] is True
    assert nodes["legal"]["output"]["decision"] == "revisar"
    context = body["result"]["context"]
    assert context["claim_refs"]
    detail = await async_client.get(
        f"/api/v1/workflows/runs/{body['run_id']}",
        headers={**headers, "Idempotency-Key": f"e2ecl-{uuid4().hex}"},
    )
    assert detail.json()["story"]


@pytest.mark.asyncio
async def test_e2e_daily_business_report(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    org, kb_id, agent_id = await _setup(async_client, "E2E Daily")
    headers = _headers(org)
    retriever = _FakeRetriever(
        {"objetivos del negocio": _chunk("La meta diaria es S/ 40000.", "metas.pdf")}
    )
    runtime = _FakeAgentRuntime(
        '{"risk": "MEDIUM", "reason": "avance parcial", "recommendation": "seguir", "confidence": 0.7}'
    )
    from src.api.deps import get_agent_runtime, get_rag_orchestrator, get_structured_retriever
    from src.api.main import app
    from src.core.config import get_settings

    app.dependency_overrides[get_structured_retriever] = lambda: retriever
    app.dependency_overrides[get_agent_runtime] = lambda: runtime
    app.dependency_overrides[get_rag_orchestrator] = lambda: _FakeOrchestrator(
        UUID(org["organization_id"])
    )
    monkeypatch.setattr(get_settings(), "KNOWLEDGE_V2_ENABLED", True)

    graph = _graph(
        [
            _node("t", "trigger_schedule", {"daily": "18:00", "timezone": "America/Lima"}),
            _node("q", "query_business_data", {"ask": "ventas de hoy"}),
            _node(
                "kb",
                "kb_query",
                {"knowledge_base_id": kb_id, "query": "objetivos del negocio"},
            ),
            _node(
                "ask",
                "llm",
                {
                    "agent_id": agent_id,
                    "prompt": "Analiza anomalías del día",
                    "output_type": "business_assessment",
                },
            ),
            _node("br", "business_result", {"title": "Resumen diario", "section": "reports"}),
            _node("n", "notify", {"channel": "in_app", "title": "Resumen", "message": "ok"}),
        ],
        [
            _edge("e1", "t", "q"),
            _edge("e2", "q", "kb"),
            _edge("e3", "kb", "ask"),
            _edge("e4", "ask", "br"),
            _edge("e5", "br", "n"),
        ],
        ["t"],
    )
    wid = await _create_workflow(async_client, org, graph, "E2E Daily")

    run = await async_client.post(
        f"/api/v1/workflows/{wid}/run",
        headers={**headers, "Idempotency-Key": f"e2ed2-{uuid4().hex}"},
        json={"payload": {}, "simulate": True},
    )
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["status"] == "simulated", body
    detail = await async_client.get(
        f"/api/v1/workflows/runs/{body['run_id']}",
        headers={**headers, "Idempotency-Key": f"e2ed3-{uuid4().hex}"},
    )
    story = " ".join(detail.json()["story"])
    assert "El agente analizó la situación: MEDIUM" in story
    assert "Se simuló publicar un resultado de negocio." in story
