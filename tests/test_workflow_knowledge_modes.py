# =============================================================================
# Cognitive Workflows — Fase 1: modos de conocimiento y resultado tipado.
#
# SEARCH (compat total), ANSWER (grounded + claims), FIND_EVIDENCE (coverage),
# modos pendientes/no soportados y operación inválida. Sin errores técnicos
# cuando el flujo puede ramificar con `status`.
# =============================================================================
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from httpx import AsyncClient

from src.core.domain.entities import RetrievalChunk
from src.rag.retrieval.structured import AssembledContext, V2RetrievalOptions
from tests.test_workflows import _create_org, _headers, _owner_session

ANSWER_TEXT = "La política permite un descuento máximo del 15% para clientes recurrentes."


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


class _FakeLLM:
    def __init__(self, content: str = ANSWER_TEXT) -> None:
        self.content = content
        self.calls: list[str] = []

    async def generate(self, prompt, **kwargs):  # noqa: ANN001, ANN003
        self.calls.append(str(prompt))
        return SimpleNamespace(
            content=self.content,
            model="fake",
            prompt_tokens=120,
            completion_tokens=30,
            total_tokens=150,
            latency_ms=5.0,
            finish_reason="stop",
        )


def _chunk() -> RetrievalChunk:
    return RetrievalChunk(
        document_id=uuid4(),
        content=ANSWER_TEXT,
        score=0.9,
        metadata={
            "source_id": str(uuid4()),
            "document_id": str(uuid4()),
            "filename": "politica-descuentos.pdf",
            "page_start": "3",
            "section_path": ["Política comercial", "Descuentos"],
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


async def _kb_setup(async_client: AsyncClient, name: str) -> tuple[dict, str]:
    org = await _create_org(async_client, name)
    org["session"] = await _owner_session(async_client, org["organization_id"])
    kb = await async_client.post(
        "/api/v1/knowledge-bases",
        json={"name": f"kb-{uuid4().hex[:8]}"},
        headers=_headers(org),
    )
    assert kb.status_code == 201, kb.text
    return org, kb.json()["id"]


async def _run_kb(
    async_client: AsyncClient, org: dict, kb_id: str, config: dict, *, v2: bool = True
) -> dict:
    from src.api.deps import get_llm_provider, get_structured_retriever
    from src.api.main import app
    from src.core.config import get_settings

    fake_llm = _FakeLLM()
    app.dependency_overrides[get_structured_retriever] = lambda: _FakeStructuredRetriever([_chunk()])
    app.dependency_overrides[get_llm_provider] = lambda: fake_llm
    previous = get_settings().KNOWLEDGE_V2_ENABLED
    get_settings().KNOWLEDGE_V2_ENABLED = v2

    try:
        graph = _graph(
            [
                _node("t", "trigger_webhook"),
                _node("kb", "kb_query", {"knowledge_base_id": kb_id, **config}),
            ],
            [_edge("e1", "t", "kb")],
            ["t"],
        )
        created = await async_client.post(
            "/api/v1/workflows",
            headers={**_headers(org), "Idempotency-Key": f"km-{uuid4().hex}"},
            json={"name": f"KM {config.get('operation', 'search')}", "trigger_type": "webhook", "graph": graph},
        )
        assert created.status_code == 200, created.text
        wid = created.json()["workflow_id"]
        run = await async_client.post(
            f"/api/v1/workflows/{wid}/run",
            headers={**_headers(org), "Idempotency-Key": f"kmr-{uuid4().hex}"},
            json={"payload": {}, "simulate": True},
        )
        assert run.status_code == 200, run.text
        body = run.json()
        assert body["status"] in ("simulated", "succeeded"), body
        return body["result"]["structured_output"]["nodes"]["kb"]["output"]
    finally:
        get_settings().KNOWLEDGE_V2_ENABLED = previous


@pytest.mark.asyncio
async def test_search_default_stays_backward_compatible(async_client: AsyncClient) -> None:
    org, kb_id = await _kb_setup(async_client, "KM Search")
    output = await _run_kb(async_client, org, kb_id, {"query": "política de descuentos"})
    assert output["operation"] == "search"
    assert output["status"] == "ok"
    assert output["method"] == "knowledge_v2"
    assert output["citations"][0]["document_name"] == "politica-descuentos.pdf"
    assert output["evidence_ids"]


@pytest.mark.asyncio
async def test_answer_grounds_with_claims(async_client: AsyncClient) -> None:
    org, kb_id = await _kb_setup(async_client, "KM Answer")
    output = await _run_kb(
        async_client,
        org,
        kb_id,
        {"operation": "answer", "query": "¿cuál es el descuento máximo?"},
    )
    assert output["status"] == "ok", output
    assert output["answer"] == ANSWER_TEXT
    assert output["claims"], output
    assert output["claims"][0]["status"] in ("supported", "partially_supported")
    assert output["confidence"] > 0
    assert output["evidence_ids"]
    assert output["budget"]["llm_calls"] == 1


@pytest.mark.asyncio
async def test_answer_without_v2_is_not_supported(async_client: AsyncClient) -> None:
    org, kb_id = await _kb_setup(async_client, "KM Answer NoV2")
    output = await _run_kb(
        async_client,
        org,
        kb_id,
        {"operation": "answer", "query": "descuentos"},
        v2=False,
    )
    assert output["status"] == "not_supported"
    assert "requires_knowledge_v2" in output["reason_codes"]


@pytest.mark.asyncio
async def test_find_evidence_reports_coverage(async_client: AsyncClient) -> None:
    org, kb_id = await _kb_setup(async_client, "KM Evidence")
    output = await _run_kb(
        async_client,
        org,
        kb_id,
        {"operation": "find_evidence", "query": "descuento máximo 15%"},
    )
    assert output["status"] == "ok"
    assert output["coverage"]["supported"] is True
    assert output["coverage"]["evidence_count"] >= 1
    assert output["evidence"][0]["page"] == 3
    assert output["sources"] == ["politica-descuentos.pdf"]


@pytest.mark.asyncio
async def test_unknown_operation_is_typed_not_error(async_client: AsyncClient) -> None:
    org, kb_id = await _kb_setup(async_client, "KM Invalid")
    output = await _run_kb(async_client, org, kb_id, {"operation": "bogus", "query": "x"})
    assert output["status"] == "invalid_operation"
    assert "search" in output["allowed_operations"]


@pytest.mark.asyncio
async def test_pending_operation_is_not_supported(async_client: AsyncClient) -> None:
    org, kb_id = await _kb_setup(async_client, "KM Pending")
    output = await _run_kb(
        async_client, org, kb_id, {"operation": "investigate", "query": "investiga el caso"}
    )
    assert output["status"] == "not_supported"
    assert output["reason_codes"] == ["phase_pending"]
