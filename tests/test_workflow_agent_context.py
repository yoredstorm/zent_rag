# =============================================================================
# Cognitive Workflows — Fase 4: contexto del agente, presets y DecisionResult.
#
# context_mode auto/manual/none, selectores por sección/nodo, presets de
# resultado, enum de fallo del agente y Data Catalog desde output_schema.
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from src.core.domain.entities import RetrievalChunk
from src.rag.retrieval.structured import AssembledContext, V2RetrievalOptions
from tests.test_workflows import _create_org, _headers, _owner_session

KNOWLEDGE_TEXT = "La política permite un descuento máximo del 15%."


class _FakeRetriever:
    async def retrieve(self, query, options=None):  # noqa: ANN001
        chunk = RetrievalChunk(
            document_id=uuid4(),
            content=KNOWLEDGE_TEXT,
            score=0.9,
            metadata={
                "source_id": str(uuid4()),
                "document_id": str(uuid4()),
                "filename": "politica.pdf",
                "page_start": "1",
                "chunk_id": str(uuid4()),
            },
        )
        return AssembledContext(
            children=(chunk,), parents=(), context=(chunk,), options=options or V2RetrievalOptions()
        )


class _FakeRuntime:
    def __init__(self, answer: str = "ok", status: str = "completed") -> None:
        self.answer = answer
        self.status = status
        self.requests: list = []

    async def run(self, request):  # noqa: ANN001
        from src.agents.runtime.agent_runtime import AgentRunResult

        self.requests.append(request)
        return AgentRunResult(
            run_id=uuid4(),
            agent_id=request.agent.id,
            organization_id=request.agent.organization_id,
            status=self.status,
            answer=self.answer,
            message=request.message,
            total_latency_ms=5.0,
            total_tokens=20,
            cost=0.0,
            model="fake",
            provider="fake",
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
    agent = await async_client.post(
        "/api/v1/agents",
        headers=_headers(org),
        json={"name": "Analista", "system_prompt": "responde corto", "tools": []},
    )
    assert agent.status_code == 201, agent.text
    return org, agent.json()["id"], ""


async def _run(
    async_client: AsyncClient,
    org: dict,
    graph: dict,
    *,
    runtime: _FakeRuntime,
    kb_id: str | None = None,
    v2: bool = True,
) -> tuple[dict, dict]:
    from src.api.deps import get_agent_runtime, get_structured_retriever
    from src.api.main import app
    from src.core.config import get_settings

    app.dependency_overrides[get_agent_runtime] = lambda: runtime
    app.dependency_overrides[get_structured_retriever] = lambda: _FakeRetriever()
    previous = get_settings().KNOWLEDGE_V2_ENABLED
    get_settings().KNOWLEDGE_V2_ENABLED = v2
    try:
        created = await async_client.post(
            "/api/v1/workflows",
            headers={**_headers(org), "Idempotency-Key": f"ac-{uuid4().hex}"},
            json={"name": "Agent Context", "trigger_type": "webhook", "graph": graph},
        )
        assert created.status_code == 200, created.text
        run = await async_client.post(
            f"/api/v1/workflows/{created.json()['workflow_id']}/run",
            headers={**_headers(org), "Idempotency-Key": f"acr-{uuid4().hex}"},
            json={"payload": {"message": "analiza"}, "simulate": True},
        )
        assert run.status_code == 200, run.text
        body = run.json()
        assert body["status"] in ("simulated", "succeeded"), body
        return body, body["result"]["structured_output"]["nodes"]
    finally:
        get_settings().KNOWLEDGE_V2_ENABLED = previous


@pytest.mark.asyncio
async def test_auto_context_includes_knowledge(async_client: AsyncClient) -> None:
    org, agent_id, _ = await _setup(async_client, "AC Auto")
    kb = await async_client.post(
        "/api/v1/knowledge-bases", json={"name": f"kb-{uuid4().hex[:6]}"}, headers=_headers(org)
    )
    kb_id = kb.json()["id"]
    graph = _graph(
        [
            _node("t", "trigger_webhook"),
            _node("kb", "kb_query", {"knowledge_base_id": kb_id, "query": "descuentos"}),
            _node("ask", "llm", {"agent_id": agent_id, "prompt": "Analiza {{nodes.kb.output.count}}"}),
        ],
        [_edge("e1", "t", "kb"), _edge("e2", "kb", "ask")],
        ["t"],
    )
    runtime = _FakeRuntime()
    body, _ = await _run(async_client, org, graph, runtime=runtime, kb_id=kb_id)

    request = runtime.requests[0]
    assert request.context is not None
    assert "knowledge" in request.context
    assert request.context["knowledge"]["kb"]["count"] == 1
    output = body["result"]["structured_output"]["nodes"]["ask"]["output"]
    assert output["status"] == "ok"
    assert "knowledge" in output["context_summary"]["sections"]


@pytest.mark.asyncio
async def test_manual_selectors_scope_context(async_client: AsyncClient) -> None:
    org, agent_id, _ = await _setup(async_client, "AC Selectors")
    kb = await async_client.post(
        "/api/v1/knowledge-bases", json={"name": f"kb-{uuid4().hex[:6]}"}, headers=_headers(org)
    )
    kb_id = kb.json()["id"]
    graph = _graph(
        [
            _node("t", "trigger_webhook"),
            _node("kb", "kb_query", {"knowledge_base_id": kb_id, "query": "descuentos"}),
            _node(
                "ask",
                "llm",
                {
                    "agent_id": agent_id,
                    "prompt": "Analiza",
                    "context_mode": "manual",
                    "context_selectors": [f"knowledge:{'kb'}"],
                },
            ),
        ],
        [_edge("e1", "t", "kb"), _edge("e2", "kb", "ask")],
        ["t"],
    )
    runtime = _FakeRuntime()
    _, _ = await _run(async_client, org, graph, runtime=runtime, kb_id=kb_id)
    request = runtime.requests[0]
    assert request.context is not None
    assert set(request.context) == {"knowledge"}
    assert set(request.context["knowledge"]) == {"kb"}


@pytest.mark.asyncio
async def test_preset_decision_builds_decision_result(async_client: AsyncClient) -> None:
    org, agent_id, _ = await _setup(async_client, "AC Decision")
    answer = '{"decision": "approve", "reason": "dentro de política", "confidence": 0.9}'
    graph = _graph(
        [
            _node("t", "trigger_webhook"),
            _node(
                "ask",
                "llm",
                {"agent_id": agent_id, "prompt": "Decide", "output_type": "decision"},
            ),
        ],
        [_edge("e1", "t", "ask")],
        ["t"],
    )
    runtime = _FakeRuntime(answer=answer)
    body, _ = await _run(async_client, org, graph, runtime=runtime)
    output = body["result"]["structured_output"]["nodes"]["ask"]["output"]
    assert output["structured"] is True
    assert output["decision"] == "approve"
    assert output["status"] == "ok"

    decisions = body["result"]["context"]["decisions"]
    assert decisions[0]["value"]["decision"] == "approve"
    assert decisions[0]["value"]["decision_result"]["decision"] == "approve"
    assert decisions[0]["value"]["decision_result"]["reasons"] == ["dentro de política"]


@pytest.mark.asyncio
async def test_invalid_preset_json_is_typed(async_client: AsyncClient) -> None:
    org, agent_id, _ = await _setup(async_client, "AC Invalid")
    graph = _graph(
        [
            _node("t", "trigger_webhook"),
            _node(
                "ask",
                "llm",
                {"agent_id": agent_id, "prompt": "Decide", "output_type": "decision"},
            ),
        ],
        [_edge("e1", "t", "ask")],
        ["t"],
    )
    runtime = _FakeRuntime(answer="no soy json")
    body, _ = await _run(async_client, org, graph, runtime=runtime)
    output = body["result"]["structured_output"]["nodes"]["ask"]["output"]
    assert output["status"] == "invalid_output"
    assert output["structured"] is False
    assert output["schema_errors"]
    assert not body["result"]["context"]["decisions"]


@pytest.mark.asyncio
async def test_low_confidence_status(async_client: AsyncClient) -> None:
    org, agent_id, _ = await _setup(async_client, "AC LowConf")
    answer = '{"decision": "review", "reason": "datos parciales", "confidence": 0.2}'
    graph = _graph(
        [
            _node("t", "trigger_webhook"),
            _node(
                "ask",
                "llm",
                {"agent_id": agent_id, "prompt": "Decide", "output_type": "decision"},
            ),
        ],
        [_edge("e1", "t", "ask")],
        ["t"],
    )
    runtime = _FakeRuntime(answer=answer)
    body, _ = await _run(async_client, org, graph, runtime=runtime)
    output = body["result"]["structured_output"]["nodes"]["ask"]["output"]
    assert output["status"] == "low_confidence"
    assert "low_confidence" in output["reason_codes"]


@pytest.mark.asyncio
async def test_budget_exceeded_status(async_client: AsyncClient) -> None:
    org, agent_id, _ = await _setup(async_client, "AC Budget")
    graph = _graph(
        [
            _node("t", "trigger_webhook"),
            _node("ask", "llm", {"agent_id": agent_id, "prompt": "Analiza"}),
        ],
        [_edge("e1", "t", "ask")],
        ["t"],
    )
    runtime = _FakeRuntime(answer="parcial", status="limit_reached")
    body, _ = await _run(async_client, org, graph, runtime=runtime)
    output = body["result"]["structured_output"]["nodes"]["ask"]["output"]
    assert output["status"] == "budget_exceeded"
    assert output["reason_codes"] == ["agent_budget_limit"]


@pytest.mark.asyncio
async def test_manual_reads_without_context_is_typed(async_client: AsyncClient) -> None:
    org, agent_id, _ = await _setup(async_client, "AC Insufficient")
    graph = _graph(
        [
            _node("t", "trigger_webhook"),
            _node(
                "ask",
                "llm",
                {
                    "agent_id": agent_id,
                    "prompt": "Analiza",
                    "context_mode": "manual",
                    "context_reads": ["knowledge"],
                },
            ),
        ],
        [_edge("e1", "t", "ask")],
        ["t"],
    )
    runtime = _FakeRuntime()
    body, _ = await _run(async_client, org, graph, runtime=runtime)
    output = body["result"]["structured_output"]["nodes"]["ask"]["output"]
    assert output["status"] == "insufficient_context"
    assert output["reason_codes"] == ["no_context_sections"]
    assert runtime.requests[0].context is None


@pytest.mark.asyncio
async def test_data_catalog_reads_output_schema(async_client: AsyncClient) -> None:
    org, agent_id, _ = await _setup(async_client, "AC Catalog")
    graph = _graph(
        [
            _node("t", "trigger_webhook"),
            _node(
                "ask",
                "llm",
                {
                    "agent_id": agent_id,
                    "prompt": "Evalúa",
                    "output_type": "business_assessment",
                    "output_schema": {
                        "type": "object",
                        "properties": {
                            "risk": {
                                "type": "string",
                                "enum": ["LOW", "MEDIUM", "HIGH"],
                                "title": "Riesgo",
                            },
                            "recommendation": {"type": "string", "title": "Recomendación"},
                        },
                    },
                },
            ),
        ],
        [_edge("e1", "t", "ask")],
        ["t"],
    )
    created = await async_client.post(
        "/api/v1/workflows",
        headers={**_headers(org), "Idempotency-Key": f"ac-cat-{uuid4().hex}"},
        json={"name": "AC Catalog", "trigger_type": "webhook", "graph": graph},
    )
    assert created.status_code == 200, created.text
    wid = created.json()["workflow_id"]

    catalog = await async_client.get(f"/api/v1/workflows/{wid}/data-catalog", headers=_headers(org))
    assert catalog.status_code == 200, catalog.text
    sources = {source["id"]: source for source in catalog.json()["sources"]}
    llm_source = sources["ask"]
    fields = {field["key"]: field for field in llm_source["fields"]}
    assert fields["risk"]["label"] == "Riesgo"
    assert fields["risk"]["ref"] == "{{nodes.ask.output.risk}}"
    assert fields["risk"]["enum"] == ["LOW", "MEDIUM", "HIGH"]
    assert fields["recommendation"]["label"] == "Recomendación"
