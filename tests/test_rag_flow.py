# =============================================================================
# Ver flujo — construcción de la traza completa y store tenant-scoped.
# =============================================================================
from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from src.agents.runtime.orchestrator import _build_flow
from src.api.main import app
from src.core.domain.decision import RoutingDecision
from src.core.domain.entities import LLMResponse, RetrievalChunk, RetrievalContext
from src.core.ports.sql_expert import SqlQueryResult


def _chunk(score: float, filename: str = "doc.pdf") -> RetrievalChunk:
    return RetrievalChunk(
        document_id=uuid4(),
        content=f"fragmento con score {score}",
        score=score,
        metadata={"filename": filename},
    )


def _timings(**overrides) -> dict:
    base = {
        "decision_ms": 0.0,
        "plan_ms": 0.0,
        "embedding_ms": 0.0,
        "retrieval_ms": 0.0,
        "sql_ms": 0.0,
        "evidence_ms": 0.0,
        "grounding_ms": 0.0,
    }
    base.update(overrides)
    return base


def _adaptive(**overrides) -> dict:
    base = {
        "plan": None,
        "quality": None,
        "evidence": None,
        "attempts": [],
        "grounding": None,
        "llm_skipped": False,
        "fallbacks": [],
        "ctx_before": 0,
        "ctx_after": 0,
    }
    base.update(overrides)
    return base


def test_build_flow_jev_documents_with_timings() -> None:
    plan = SimpleNamespace(
        apply=True,
        source_route="knowledge.search",
        retrieval_strategy="hybrid",
        engine_strategy="hybrid",
        rewritten_query=None,
        skip_retrieval=False,
    )
    decision = RoutingDecision(
        capability="knowledge.answer",
        provider="jev",
        confidence=0.93,
        resolved=True,
        metadata={"acting": True, "mode": "jev"},
    )
    flow = _build_flow(
        query_id=uuid4(),
        organization_id=uuid4(),
        conversation_id=uuid4(),
        method="rag",
        status="completed",
        decision=decision,
        decision_evaluated=True,
        adaptive=_adaptive(plan=plan, attempts=[{"attempt": 1}]),
        retrieval_context=RetrievalContext(
            chunks=[_chunk(0.9, "gerente.pdf"), _chunk(0.5)],
            retrieval_latency_ms=120.0,
        ),
        sql_result=None,
        llm_response=LLMResponse(
            content="respuesta",
            model="deepseek-v3.2",
            prompt_tokens=100,
            completion_tokens=10,
            total_tokens=110,
            latency_ms=800.0,
        ),
        timings=_timings(
            decision_ms=90.0, plan_ms=40.0, embedding_ms=30.0, retrieval_ms=120.0
        ),
        total_ms=1500.0,
        fallbacks=[],
        generation_cost=0.0012,
        pricing={
            "input_cost_per_1k": 0.00015,
            "output_cost_per_1k": 0.0006,
            "currency": "USD",
        },
    )
    assert flow["verdict"] == {"decider": "JEV", "route": "Documentos"}
    assert flow["decision"]["jev_used"] is True
    assert flow["decision"]["acting"] is True
    assert flow["decision"]["ms"] == 90.0
    assert flow["retrieval"]["chunks"] == 2
    assert flow["retrieval"]["top_score"] == 0.9
    assert flow["retrieval"]["attempts"] == 1
    assert flow["generation"]["model"] == "deepseek-v3.2"
    assert flow["generation"]["cost"] == 0.0012
    assert flow["pricing"]["input_cost_per_1k"] == 0.00015
    assert flow["timings"]["generation_ms"] == 800.0
    assert flow["timings"]["total_ms"] == 1500.0
    assert flow["sources"][0]["title"] == "gerente.pdf"
    steps = [step["name"] for step in flow["steps"]]
    assert steps == ["Decisión", "Plan de búsqueda", "Búsqueda", "Respuesta"]


def test_build_flow_sql_route_legacy_decider() -> None:
    sql = SqlQueryResult(
        sql="SELECT COUNT(*) FROM ventas",
        row_count=3,
        metadata={"tables": ["ventas"]},
    )
    flow = _build_flow(
        query_id=uuid4(),
        organization_id=uuid4(),
        conversation_id=None,
        method="sql",
        status="completed",
        decision=None,
        decision_evaluated=False,
        adaptive=_adaptive(),
        retrieval_context=None,
        sql_result=sql,
        llm_response=LLMResponse(content="hay 3 ventas", model="gpt-4o-mini"),
        timings=_timings(sql_ms=250.0),
        total_ms=900.0,
        fallbacks=[],
    )
    assert flow["verdict"] == {"decider": "Legacy", "route": "SQL"}
    assert flow["decision"]["evaluated"] is False
    assert flow["sql"]["query"].startswith("SELECT")
    assert flow["sql"]["rows"] == 3
    assert flow["sql"]["tables"] == ["ventas"]
    assert flow["timings"]["sql_ms"] == 250.0
    assert [step["name"] for step in flow["steps"]] == ["SQL", "Respuesta"]


def test_answerability_evidence_accepts_snippet() -> None:
    """El gate agrega `snippet`; el schema no debe romper la respuesta."""
    from src.api.schemas import AnswerabilityEvidenceResponse

    item = AnswerabilityEvidenceResponse(
        evidence_id="e-1",
        type="document",
        source_name="manual.pdf",
        authority_level="official",
        freshness=None,
        snippet="texto de evidencia",
    )
    assert item.snippet == "texto de evidencia"


def test_build_flow_extractive_fast_path_marks_skipped() -> None:
    plan = SimpleNamespace(
        apply=True,
        source_route="knowledge.search",
        retrieval_strategy="lexical",
        engine_strategy="hybrid",
        rewritten_query=None,
        skip_retrieval=False,
    )
    flow = _build_flow(
        query_id=uuid4(),
        organization_id=uuid4(),
        conversation_id=None,
        method="rag",
        status="completed",
        decision=None,
        decision_evaluated=False,
        adaptive=_adaptive(plan=plan, llm_skipped=True),
        retrieval_context=RetrievalContext(chunks=[_chunk(0.8)], retrieval_latency_ms=10.0),
        sql_result=None,
        llm_response=LLMResponse(content="extraído", model="extractive"),
        timings=_timings(retrieval_ms=10.0),
        total_ms=50.0,
        fallbacks=[],
    )
    assert flow["generation"]["skipped"] is True
    assert "Respuesta" not in [step["name"] for step in flow["steps"]]


# ---------------------------------------------------------------------------
# Store + endpoint tenant-scoped
# ---------------------------------------------------------------------------


async def _create_org(client: AsyncClient, name: str) -> dict:
    response = await client.post(
        "/api/v1/billing/subscription/create-trial",
        json={
            "company_name": name,
            "email": f"flow-{uuid4().hex[:8]}@example.com",
            "country": "CL",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _owner_session(organization_id: str) -> str:
    from src.infrastructure.postgres.relational_db import PostgresUserRepository
    from src.platform.auth.session import encrypt_session

    user = await PostgresUserRepository().get_by_external_id(
        UUID(organization_id), "default-admin"
    )
    assert user is not None
    return encrypt_session(user.id, UUID(organization_id))


def _headers(org: dict) -> dict:
    return {
        "Authorization": f"Bearer {org['session']}",
        "X-Organization-Id": org["organization_id"],
    }


@pytest.fixture
async def async_client():
    from tests.conftest import attach_auto_idempotency

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield attach_auto_idempotency(client)


@pytest.fixture
async def org(async_client: AsyncClient) -> dict:
    organization = await _create_org(async_client, "Flow Store")
    organization["session"] = await _owner_session(organization["organization_id"])
    return organization


async def test_flow_store_roundtrip_and_tenant_isolation(
    async_client: AsyncClient, org: dict
) -> None:
    from src.rag.flow_store import get_flow, record_flow

    query_id = uuid4()
    organization_id = UUID(org["organization_id"])
    await record_flow(
        query_id=query_id,
        organization_id=organization_id,
        flow={"verdict": {"decider": "JEV", "route": "Documentos"}},
        method="rag",
        status="completed",
    )
    stored = await get_flow(organization_id, query_id)
    assert stored is not None
    assert stored["verdict"]["decider"] == "JEV"
    assert stored["method"] == "rag"

    assert await get_flow(uuid4(), query_id) is None


async def test_flow_endpoint_returns_stored_flow_and_404_cross_tenant(
    async_client: AsyncClient, org: dict
) -> None:
    from src.rag.flow_store import record_flow

    query_id = uuid4()
    await record_flow(
        query_id=query_id,
        organization_id=UUID(org["organization_id"]),
        flow={"verdict": {"decider": "Reglas", "route": "SQL"}, "timings": {"total_ms": 12}},
        method="sql",
        status="completed",
    )

    response = await async_client.get(
        f"/api/v1/rag/queries/{query_id}/flow", headers=_headers(org)
    )
    assert response.status_code == 200, response.text
    assert response.json()["flow"]["verdict"]["route"] == "SQL"

    other = await _create_org(async_client, "Flow Other")
    other["session"] = await _owner_session(other["organization_id"])
    cross = await async_client.get(
        f"/api/v1/rag/queries/{query_id}/flow", headers=_headers(other)
    )
    assert cross.status_code == 404

    missing = await async_client.get(
        f"/api/v1/rag/queries/{uuid4()}/flow", headers=_headers(org)
    )
    assert missing.status_code == 404
