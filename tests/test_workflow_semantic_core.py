# =============================================================================
# Workflow Semantic Core — primer test end-to-end (brief §20).
#
# Trigger sale.created → query_business_data → kb_query (V2) → llm → condition
# → notify. Valida: outputs tipados, propagación de contexto al agente,
# evidencia real del ledger, aislamiento por tenant y cero pegamento manual
# de strings entre Knowledge, Data y Agent.
# =============================================================================
from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from src.core.domain.entities import RetrievalChunk
from src.platform.workflows.context_store import filter_persistable_applied, load_run_context
from src.rag.retrieval.structured import AssembledContext, V2RetrievalOptions
from tests.test_workflows import _create_org, _headers, _owner_session


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


class _FakeStructuredRetriever:
    def __init__(self, chunks: list[RetrievalChunk]) -> None:
        self._chunks = chunks

    async def retrieve(self, query, options=None):  # noqa: ANN001
        return AssembledContext(
            children=tuple(self._chunks),
            parents=(),
            context=tuple(self._chunks),
            options=options or V2RetrievalOptions(),
        )


class _FakeAgentRuntime:
    """Runtime de agente fake: captura el request (contexto ensamblado)."""

    def __init__(self) -> None:
        self.requests: list = []

    async def run(self, request):  # noqa: ANN001
        from src.agents.runtime.agent_runtime import AgentRunResult

        self.requests.append(request)
        answer = '{"risk": "high", "reason": "stock crítico", "recommendation": "reponer"}'
        return AgentRunResult(
            run_id=uuid4(),
            agent_id=request.agent.id,
            organization_id=request.agent.organization_id,
            status="completed",
            answer=answer,
            message=request.message,
            user_id=request.user_id,
            role=request.role,
            total_latency_ms=10.0,
            total_tokens=40,
            cost=0.0003,
            model="fake",
            provider="fake",
        )


class _FakeOrchestrator:
    """Orquestador RAG fake con SQL-first + answerability."""

    def __init__(self, organization_id: UUID) -> None:
        self.organization_id = organization_id

    async def execute(self, **kwargs):  # noqa: ANN003
        return SimpleNamespace(
            query_id=uuid4(),
            organization_id=self.organization_id,
            llm_response=SimpleNamespace(content="Hay 3 unidades del producto A."),
            method="sql",
            sql_query="SELECT producto, stock FROM inventario LIMIT 10",
            total_latency_ms=25.0,
            structured_output={
                "rows": [{"producto": "A", "stock": 3}],
                "columns": ["producto", "stock"],
                "row_count": 1,
                "truncated": False,
            },
            answerability=SimpleNamespace(
                status="answerable",
                answerable=True,
                confidence_level="high",
                reason_codes=["data_found"],
                evidence_ids=[str(uuid4())],
                sources=["managed_db:inventario"],
            ),
            retrieval_context=None,
            lazy_ingested=False,
            lazy_rows_indexed=0,
        )


def _chunk() -> RetrievalChunk:
    return RetrievalChunk(
        document_id=uuid4(),
        content="La política permite un descuento máximo del 15% para clientes recurrentes.",
        score=0.9,
        metadata={
            "source_id": str(uuid4()),
            "document_id": str(uuid4()),
            "filename": "politica-reposicion.pdf",
            "page_start": "2",
            "section_path": ["Política comercial", "Reposición"],
            "chunk_id": str(uuid4()),
        },
    )


@pytest.mark.asyncio
async def test_semantic_core_end_to_end(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    org = await _create_org(async_client, "Semantic Core E2E")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    kb = await async_client.post(
        "/api/v1/knowledge-bases",
        json={"name": f"kb-{uuid4().hex[:8]}"},
        headers=h,
    )
    assert kb.status_code == 201, kb.text
    kb_id = kb.json()["id"]

    agent = await async_client.post(
        "/api/v1/agents",
        headers=h,
        json={"name": "Analista de riesgo", "system_prompt": "responde corto", "tools": []},
    )
    assert agent.status_code == 201, agent.text
    agent_id = agent.json()["id"]

    from src.api.deps import get_agent_runtime, get_rag_orchestrator, get_structured_retriever
    from src.api.main import app
    from src.core.config import get_settings

    fake_runtime = _FakeAgentRuntime()
    app.dependency_overrides[get_agent_runtime] = lambda: fake_runtime
    app.dependency_overrides[get_structured_retriever] = lambda: _FakeStructuredRetriever([_chunk()])
    app.dependency_overrides[get_rag_orchestrator] = lambda: _FakeOrchestrator(
        UUID(org["organization_id"])
    )
    monkeypatch.setattr(get_settings(), "KNOWLEDGE_V2_ENABLED", True)

    graph = _graph(
        [
            _node("t", "trigger_event", {"event_type": "sales.closed", "filters": {}}),
            _node("q", "query_business_data", {"ask": "stock del producto A"}),
            _node(
                "kb",
                "kb_query",
                {"knowledge_base_id": kb_id, "query": "política de reposición", "limit": 3},
            ),
            _node(
                "ask",
                "llm",
                {
                    "agent_id": agent_id,
                    "prompt": "Analiza la venta {{trigger.total}} y recomienda próximos pasos",
                    "output_schema": {
                        "type": "object",
                        "properties": {
                            "risk": {"type": "string"},
                            "reason": {"type": "string"},
                            "recommendation": {"type": "string"},
                        },
                    },
                    "context_reads": ["data", "knowledge", "evidence"],
                },
            ),
            _node(
                "cond",
                "condition",
                {"field": "{{nodes.ask.output.risk}}", "operator": "==", "value": "high"},
                output_ports=[
                    {"name": "out", "type": "boolean"},
                    {"name": "then", "type": "json"},
                    {"name": "else", "type": "json"},
                ],
            ),
            _node(
                "notify",
                "notify",
                {
                    "channel": "in_app",
                    "title": "Riesgo alto",
                    "message": "{{nodes.ask.output.recommendation}}",
                },
            ),
        ],
        [
            _edge("e1", "t", "q"),
            _edge("e2", "q", "kb"),
            _edge("e3", "kb", "ask"),
            _edge("e4", "ask", "cond"),
            _edge("e5", "cond", "notify", from_port="then"),
        ],
        ["t"],
    )
    created = await async_client.post(
        "/api/v1/workflows",
        headers={**h, "Idempotency-Key": f"sc-{uuid4().hex}"},
        json={"name": "Semantic Core E2E", "trigger_type": "event", "graph": graph},
    )
    assert created.status_code == 200, created.text
    wid = created.json()["workflow_id"]

    run = await async_client.post(
        f"/api/v1/workflows/{wid}/run",
        headers=h,
        json={"payload": {"total": 18500, "customer": "ACME"}, "simulate": True},
    )
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["status"] == "simulated", body

    # 1) Outputs crudos intactos y tipados por nodo.
    outputs = body["result"]["structured_output"]["nodes"]
    assert outputs["q"]["output"]["rows"] == [{"producto": "A", "stock": 3}]
    assert outputs["q"]["output"]["columns"] == ["producto", "stock"]
    assert outputs["q"]["output"]["evidence_ids"], outputs["q"]["output"]
    assert outputs["kb"]["output"]["method"] == "knowledge_v2"
    assert outputs["kb"]["output"]["citations"][0]["document_name"] == "politica-reposicion.pdf"
    assert outputs["kb"]["output"]["evidence_ids"], outputs["kb"]["output"]
    assert outputs["ask"]["output"]["risk"] == "high"  # output_schema inyectado
    assert outputs["ask"]["output"]["structured"] is True
    assert outputs["cond"]["output"]["result"] is True
    assert outputs["notify"]["status"] == "simulated"

    # 2) Contexto compartido: data + knowledge + evidence + decisions.
    context = body["result"]["context"]
    assert "security" not in context
    assert context["data"]["q"]["value"]["rows"][0]["stock"] == 3
    assert context["knowledge"]["kb"]["value"]["citations"][0]["document_name"] == "politica-reposicion.pdf"
    assert len(context["evidence_refs"]) >= 2
    origins = {ref["provenance"]["origin_kind"] for ref in context["evidence_refs"]}
    assert {"datasource", "knowledge"} <= origins
    assert context["decisions"][0]["value"]["risk"] == "high"

    # 3) El agente recibe contexto estructurado ensamblado, sin concatenación manual.
    request = fake_runtime.requests[0]
    assert request.context is not None
    assert "security" not in request.context
    assert request.context["data"]["q"]["rows"][0]["stock"] == 3
    assert request.context["knowledge"]["kb"]["citations"][0]["document_name"] == "politica-reposicion.pdf"
    assert request.context["evidence_refs"]
    assert "18500" in request.message  # referencia {{trigger.total}} resuelta por el runtime

    # 4) Evidencia real del ledger, validada por tenant.
    q_evidence = outputs["q"]["output"]["evidence_ids"][0]
    item = {"section": "evidence_refs", "payload": {"value": {"evidence_id": q_evidence}}}
    assert await filter_persistable_applied(uuid4(), [item]) == []
    assert await filter_persistable_applied(UUID(org["organization_id"]), [item]) == [item]
    stored = await load_run_context(UUID(org["organization_id"]), UUID(body["run_id"]))
    assert stored is not None and stored["evidence_refs"]

    # 5) Inspector: acciones y contribuciones visibles, sin CoT.
    detail = await async_client.get(f"/api/v1/workflows/runs/{body['run_id']}", headers=h)
    inspector = detail.json()
    assert inspector["chain_of_thought_exposed"] is False
    assert any(action["node_id"] == "notify" for action in inspector["actions"])
    assert {c["node_id"] for c in inspector["contributions"]} >= {"q", "kb", "ask"}
    assert inspector["decisions"][0]["value"]["risk"] == "high"
