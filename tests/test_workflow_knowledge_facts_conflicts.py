# =============================================================================
# Cognitive Workflows — Fase 2: extract_facts, compare, check_conflicts.
#
# Reuso: document_facts (reglas offline), TemporalResolver, Claim Ledger
# (upsert PROPOSED + attach_evidence + find_conflicting + classify_conflict).
# =============================================================================
from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from src.core.domain.entities import RetrievalChunk
from src.rag.retrieval.structured import AssembledContext, V2RetrievalOptions
from tests.test_workflows import _create_org, _headers, _owner_session

FACT_TEXT = (
    "Contrato marco con ACME SAC. Monto: S/ 45,000.00. "
    "Fecha de inicio: 2026-01-15. Vigencia anual."
)
OLD_POLICY = "La política antigua permitía un descuento máximo del 10% para clientes recurrentes."
NEW_POLICY = "La política nueva permite un descuento máximo del 20% para clientes recurrentes."


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
            prompt_tokens=50,
            completion_tokens=20,
            total_tokens=70,
            latency_ms=3.0,
            finish_reason="stop",
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
            "section_path": ["Sección 1"],
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


async def _setup(async_client: AsyncClient, name: str) -> tuple[dict, str]:
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
    async_client: AsyncClient,
    org: dict,
    kb_id: str,
    config: dict,
    *,
    retriever: _FakeRetriever,
    llm: _FakeLLM | None = None,
    v2: bool = True,
) -> dict:
    from src.api.deps import get_llm_provider, get_structured_retriever
    from src.api.main import app
    from src.core.config import get_settings

    app.dependency_overrides[get_structured_retriever] = lambda: retriever
    if llm is not None:
        app.dependency_overrides[get_llm_provider] = lambda: llm
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
            headers={**_headers(org), "Idempotency-Key": f"kf-{uuid4().hex}"},
            json={"name": f"KF {config.get('operation')}", "trigger_type": "webhook", "graph": graph},
        )
        assert created.status_code == 200, created.text
        run = await async_client.post(
            f"/api/v1/workflows/{created.json()['workflow_id']}/run",
            headers={**_headers(org), "Idempotency-Key": f"kfr-{uuid4().hex}"},
            json={"payload": {}, "simulate": True},
        )
        assert run.status_code == 200, run.text
        body = run.json()
        assert body["status"] in ("simulated", "succeeded"), body
        return body["result"]["structured_output"]["nodes"]["kb"]["output"]
    finally:
        get_settings().KNOWLEDGE_V2_ENABLED = previous


@pytest.mark.asyncio
async def test_extract_facts_persists_proposed_claims(async_client: AsyncClient) -> None:
    org, kb_id = await _setup(async_client, "KF Facts")
    retriever = _FakeRetriever({"contrato": _chunk(FACT_TEXT)})
    output = await _run_kb(
        async_client,
        org,
        kb_id,
        {"operation": "extract_facts", "query": "contrato"},
        retriever=retriever,
    )
    assert output["status"] == "ok", output
    assert output["claims"], output
    assert output["claims"][0]["status"] == "proposed"
    assert output["entities"]
    assert output["evidence_ids"]
    assert output["facts"]

    from src.api.deps import get_claim_ledger_repo

    repo = get_claim_ledger_repo()
    saved = await repo.get(UUID(org["organization_id"]), UUID(output["claims"][0]["claim_id"]))
    assert saved is not None
    assert saved.status.value == "proposed"
    assert saved.task_id is not None
    assert saved.evidence_ids


@pytest.mark.asyncio
async def test_extract_facts_without_v2_is_not_supported(async_client: AsyncClient) -> None:
    org, kb_id = await _setup(async_client, "KF Facts NoV2")
    retriever = _FakeRetriever({"contrato": _chunk(FACT_TEXT)})
    output = await _run_kb(
        async_client,
        org,
        kb_id,
        {"operation": "extract_facts", "query": "contrato"},
        retriever=retriever,
        v2=False,
    )
    assert output["status"] == "not_supported"
    assert output["reason_codes"] == ["requires_knowledge_v2"]


@pytest.mark.asyncio
async def test_compare_returns_differences(async_client: AsyncClient) -> None:
    org, kb_id = await _setup(async_client, "KF Compare")
    retriever = _FakeRetriever(
        {
            "política antigua": _chunk(OLD_POLICY, "politica-old.pdf"),
            "política nueva": _chunk(NEW_POLICY, "politica-new.pdf"),
        }
    )
    llm = _FakeLLM(
        '{"differences": [{"topic": "descuento", "left": "10%", "right": "20%", '
        '"impact": "alto"}]}'
    )
    output = await _run_kb(
        async_client,
        org,
        kb_id,
        {
            "operation": "compare",
            "compare_left": "política antigua",
            "compare_right": "política nueva",
        },
        retriever=retriever,
        llm=llm,
    )
    assert output["status"] == "ok", output
    assert output["differences"][0]["topic"] == "descuento"
    assert output["sides"] == {"left": 1, "right": 1}
    assert len(output["evidence_ids"]) >= 2
    assert output["temporal_context"]["note"] == "no_effective_dates"


@pytest.mark.asyncio
async def test_compare_requires_both_sides(async_client: AsyncClient) -> None:
    org, kb_id = await _setup(async_client, "KF Compare Missing")
    retriever = _FakeRetriever({"política": _chunk(OLD_POLICY)})
    output = await _run_kb(
        async_client,
        org,
        kb_id,
        {"operation": "compare", "compare_left": "política"},
        retriever=retriever,
    )
    assert output["status"] == "not_supported"
    assert output["reason_codes"] == ["requires_left_and_right"]


@pytest.mark.asyncio
async def test_check_conflicts_detects_ledger_conflict(async_client: AsyncClient) -> None:
    org, kb_id = await _setup(async_client, "KF Conflicts")
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

    retriever = _FakeRetriever({"descuento": _chunk("…")})
    output = await _run_kb(
        async_client,
        org,
        kb_id,
        {"operation": "check_conflicts", "subject": "descuento maximo"},
        retriever=retriever,
    )
    assert output["status"] == "ok", output
    assert output["has_conflicts"] is True
    assert output["count"] >= 1
    conflict = output["conflicts"][0]
    assert conflict["conflict_type"] == "direct_conflict"
    assert conflict["severity"] == "high"
    assert conflict["resolution_status"] == "unresolved"
    assert len(conflict["claim_ids"]) == 2
    assert len(output["claim_ids"]) == 2


@pytest.mark.asyncio
async def test_check_conflicts_without_claims_is_not_found(async_client: AsyncClient) -> None:
    org, kb_id = await _setup(async_client, "KF Conflicts Empty")
    retriever = _FakeRetriever({"x": _chunk("…")})
    output = await _run_kb(
        async_client,
        org,
        kb_id,
        {"operation": "check_conflicts", "subject": f"tema-{uuid4().hex[:8]}"},
        retriever=retriever,
    )
    assert output["status"] == "knowledge_not_found"
    assert output["has_conflicts"] is False
