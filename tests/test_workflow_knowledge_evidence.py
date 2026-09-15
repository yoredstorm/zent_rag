# =============================================================================
# Workflow Semantic Core — Fase 7: Knowledge V2 + Evidence Ledger en kb_query.
#
# Con RAG_KNOWLEDGE_V2_ENABLED: citations + evidence_ids reales del ledger;
# el contexto del run transporta las refs y la persistencia las valida por org.
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from src.core.domain.entities import RetrievalChunk
from src.platform.workflows.context_store import filter_persistable_applied, load_run_context
from src.rag.retrieval.structured import AssembledContext, V2RetrievalOptions
from tests.test_workflows import _create_org, _headers, _owner_session


class FakeStructuredRetriever:
    def __init__(self, chunks: list[RetrievalChunk]) -> None:
        self._chunks = chunks

    async def retrieve(self, query, options=None):  # noqa: ANN001
        return AssembledContext(
            children=tuple(self._chunks),
            parents=(),
            context=tuple(self._chunks),
            options=options or V2RetrievalOptions(),
        )


def _chunk() -> RetrievalChunk:
    return RetrievalChunk(
        document_id=uuid4(),
        content="La política permite un descuento máximo del 15% para clientes recurrentes.",
        score=0.91,
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


@pytest.mark.asyncio
async def test_kb_query_v2_records_citations_and_evidence(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    org = await _create_org(async_client, "Knowledge Evidence")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    kb = await async_client.post(
        "/api/v1/knowledge-bases",
        json={"name": f"kb-{uuid4().hex[:8]}"},
        headers=h,
    )
    assert kb.status_code == 201, kb.text
    kb_id = kb.json()["id"]

    from src.api.deps import get_structured_retriever
    from src.api.main import app

    app.dependency_overrides[get_structured_retriever] = lambda: FakeStructuredRetriever([_chunk()])

    from src.core.config import get_settings

    monkeypatch.setattr(get_settings(), "KNOWLEDGE_V2_ENABLED", True)

    graph = _graph(
        [
            _node("t", "trigger_webhook"),
            _node(
                "kb",
                "kb_query",
                {"knowledge_base_id": kb_id, "query": "política de descuentos", "limit": 3},
            ),
        ],
        [_edge("e1", "t", "kb")],
        ["t"],
    )
    created = await async_client.post(
        "/api/v1/workflows",
        headers={**h, "Idempotency-Key": f"ke-{uuid4().hex}"},
        json={"name": "Knowledge Evidence WF", "trigger_type": "webhook", "graph": graph},
    )
    assert created.status_code == 200, created.text
    wid = created.json()["workflow_id"]

    run = await async_client.post(
        f"/api/v1/workflows/{wid}/run",
        headers=h,
        json={"payload": {"message": "descuentos"}},
    )
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["status"] == "succeeded", body

    output = body["result"]["structured_output"]["nodes"]["kb"]["output"]
    assert output["method"] == "knowledge_v2"
    assert output["count"] == 1
    assert output["citations"][0]["document_name"] == "politica-descuentos.pdf"
    assert output["citations"][0]["page"] == 3
    evidence_id = output["evidence_ids"][0]

    context = body["result"]["context"]
    assert context["knowledge"]["kb"]["value"]["citations"], context
    assert context["evidence_refs"], context
    assert context["evidence_refs"][0]["value"]["evidence_id"] == evidence_id

    stored = await load_run_context(UUID(org["organization_id"]), UUID(body["run_id"]))
    assert stored is not None
    assert stored["evidence_refs"]
    assert stored["knowledge"]["kb"]["value"]["count"] == 1

    # La ref del ledger es válida en la org dueña y se rechaza para otra org.
    item = {"section": "evidence_refs", "payload": {"value": {"evidence_id": evidence_id}}}
    assert await filter_persistable_applied(uuid4(), [item]) == []
    assert await filter_persistable_applied(UUID(org["organization_id"]), [item]) == [item]
