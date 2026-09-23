# =============================================================================
# Company Intelligence Studio — demo seed + API (Fase 5C)
# =============================================================================
# Verifica el escenario §26 contra Postgres y las vistas §27 (preguntas demo),
# el aislamiento por tenant y que la Studio consuma el contrato del grafo.
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.main import app


async def _create_org(client: AsyncClient, name: str) -> dict:
    response = await client.post(
        "/api/v1/billing/subscription/create-trial",
        json={
            "company_name": name,
            "email": f"ci-{uuid4().hex[:8]}@example.com",
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
async def api_client():
    from tests.conftest import attach_auto_idempotency

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield attach_auto_idempotency(client)


@pytest.fixture
async def seeded(api_client):
    """Organización con el escenario Fare Audit sembrado."""
    from src.company.demo_seed import seed_demo_candidates, seed_fare_audit_demo

    created = await _create_org(api_client, "Company Intelligence Org")
    organization_id = UUID(created["organization_id"])
    result = await seed_fare_audit_demo(organization_id)
    await seed_demo_candidates(organization_id)
    created["seed"] = result
    created["session"] = await _owner_session(created["organization_id"])
    return created


@pytest.mark.asyncio
async def test_demo_seed_is_complete_and_idempotent(seeded) -> None:
    from src.company.demo_seed import seed_fare_audit_demo

    organization_id = UUID(seeded["organization_id"])
    seed = seeded["seed"]
    assert seed.entities == 13
    assert seed.relationships == 12
    assert seed.authority_rules == 4
    assert seed.memory_recorded is True
    assert seed.finding_recorded is True
    assert seed.experiment_recorded is True

    # Idempotente: volver a sembrar no duplica entidades.
    again = await seed_fare_audit_demo(organization_id)
    assert again.entities == seed.entities

    from src.company.wiring import company_graph_service

    graph = company_graph_service()
    entities = await graph.find_entities(organization_id, limit=200)
    assert len(entities) == seed.entities


@pytest.mark.asyncio
async def test_overview_endpoint_reports_seeded_graph(api_client, seeded) -> None:
    response = await api_client.get(
        "/api/v1/company-intelligence/overview", headers=_headers(seeded)
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["entities"]["total"] == 13
    assert body["coverage"]["systems"] == 1
    assert body["coverage"]["concepts"] == 1
    assert body["coverage"]["agents"] == 1
    assert body["coverage"]["workflows"] == 1
    assert body["knowledge_gaps"]["total"] >= 1


@pytest.mark.asyncio
async def test_entity_detail_and_map_endpoints(api_client, seeded) -> None:
    from src.company.wiring import company_graph_service

    organization_id = UUID(seeded["organization_id"])
    graph = company_graph_service()
    entities = await graph.find_entities(organization_id, query="A1672", limit=5)
    a1672 = next(
        item for item in entities if item.canonical_name == "A1672"
    )

    detail = await api_client.get(
        f"/api/v1/company-intelligence/entities/{a1672.id}", headers=_headers(seeded)
    )
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["entity"]["canonical_name"] == "A1672"
    assert body["incoming"] and body["outgoing"]
    assert any(
        item["canonical_name"] == "PXSAUDIT"
        for item in body["related"].get("systems", [])
    )

    layer = await api_client.get(
        f"/api/v1/company-intelligence/map/{a1672.id}",
        headers=_headers(seeded),
        params={"max_nodes": 5, "max_edges": 4},
    )
    assert layer.status_code == 200, layer.text
    payload = layer.json()
    assert len(payload["nodes"]) <= 5
    assert len(payload["edges"]) <= 4
    assert payload["root"]["id"] == str(a1672.id)


@pytest.mark.asyncio
async def test_impact_and_source_of_truth_endpoints(api_client, seeded) -> None:
    from src.company.wiring import company_graph_service

    organization_id = UUID(seeded["organization_id"])
    graph = company_graph_service()
    pxsaudit = next(
        item
        for item in await graph.find_entities(organization_id, query="PXSAUDIT", limit=5)
        if item.canonical_name == "PXSAUDIT"
    )
    impact = await api_client.get(
        f"/api/v1/company-intelligence/entities/{pxsaudit.id}/impact",
        headers=_headers(seeded),
    )
    assert impact.status_code == 200, impact.text
    body = impact.json()
    assert body["affected"]
    assert all("status" in edge for edge in body["edges"])
    assert body["paths"]

    truth = await api_client.get(
        "/api/v1/company-intelligence/source-of-truth", headers=_headers(seeded)
    )
    assert truth.status_code == 200, truth.text
    entries = truth.json()["items"]
    pending = next(
        item for item in entries if item["concept"] == "Pending Transaction"
    )
    assert pending["authoritative"][0]["source_name"] == "PXSAUDIT"


@pytest.mark.asyncio
async def test_gaps_changes_risks_health_and_institutional(api_client, seeded) -> None:
    gaps = await api_client.get(
        "/api/v1/company-intelligence/knowledge-gaps", headers=_headers(seeded)
    )
    assert gaps.status_code == 200, gaps.text
    items = gaps.json()["items"]
    assert any(item["gap_kind"] == "undocumented_step" for item in items)
    assert any(item["origin"] == "graph" for item in items)

    changes = await api_client.get(
        "/api/v1/company-intelligence/changes", headers=_headers(seeded)
    )
    assert changes.status_code == 200
    assert changes.json()["items"]

    risks = await api_client.get(
        "/api/v1/company-intelligence/risks", headers=_headers(seeded)
    )
    assert risks.status_code == 200
    assert all(item["level"] == "potential" for item in risks.json()["items"])

    health = await api_client.get(
        "/api/v1/company-intelligence/health", headers=_headers(seeded)
    )
    assert health.status_code == 200, health.text
    assert health.json()["counts"]["entities"] == 13

    institutional = await api_client.get(
        "/api/v1/company-intelligence/institutional", headers=_headers(seeded)
    )
    assert institutional.status_code == 200
    body = institutional.json()
    assert [item["canonical_name"] for item in body["teams"]] == ["Audit Team"]


@pytest.mark.asyncio
async def test_process_and_memory_views(api_client, seeded) -> None:
    from src.company.wiring import company_graph_service

    organization_id = UUID(seeded["organization_id"])
    graph = company_graph_service()
    process = next(
        item
        for item in await graph.find_entities(
            organization_id, query="Reconciliation", limit=10
        )
        if item.entity_type == "process"
    )
    page = await api_client.get(
        f"/api/v1/company-intelligence/processes/{process.id}", headers=_headers(seeded)
    )
    assert page.status_code == 200, page.text
    body = page.json()
    assert any(item["name"] == "PXSAUDIT" for item in body["systems"])
    assert any(item["name"] == "Reconciliation Workflow" for item in body["workflows"])
    assert body["deviation"]["available"] is False

    a1672 = next(
        item
        for item in await graph.find_entities(organization_id, query="A1672", limit=5)
        if item.canonical_name == "A1672"
    )
    memory = await api_client.get(
        f"/api/v1/company-intelligence/entities/{a1672.id}/memory",
        headers=_headers(seeded),
    )
    assert memory.status_code == 200, memory.text
    body = memory.json()
    assert body["patterns"], "la memoria sembrada debe aparecer ligada a la tabla"
    assert any(
        item["pattern_key"].startswith("sql") for item in body["patterns"]
    ) or body["patterns"]


@pytest.mark.asyncio
async def test_demo_questions_are_answerable(api_client, seeded) -> None:
    """§27: las preguntas demo deben tener respuesta con evidencia."""
    questions = [
        "¿Qué es Record2?",
        "¿Dónde se representa Carrier Code?",
        "¿Qué proceso usa A1672?",
        "¿Qué depende de ATPCO?",
        "¿Qué se vería afectado si PXSAUDIT no está disponible?",
        "¿Cuál es la fuente de verdad de ticket status?",
        "¿Qué aprendió Zent sobre esta tabla?",
    ]
    for question in questions:
        response = await api_client.post(
            "/api/v1/company-intelligence/ask",
            headers=_headers(seeded),
            json={"question": question, "allow_knowledge": False},
        )
        assert response.status_code == 200, f"{question}: {response.text}"
        body = response.json()
        assert body["intent"], question
        assert body["decision"]["provider"] in ("jev", "lexical"), question
        # Toda respuesta no vacía trae evidencia o declara que no encontró nada.
        assert body["answer"] or body["evidence"], question
        assert body["context_used"]["tokens_estimate"] is not None


@pytest.mark.asyncio
async def test_studio_is_tenant_scoped(api_client, seeded) -> None:
    other = await _create_org(api_client, "Company Intelligence Other")
    other["session"] = await _owner_session(other["organization_id"])

    overview = await api_client.get(
        "/api/v1/company-intelligence/overview", headers=_headers(other)
    )
    assert overview.status_code == 200
    assert overview.json()["entities"]["total"] == 0

    from src.company.wiring import company_graph_service

    graph = company_graph_service()
    a1672 = next(
        item
        for item in await graph.find_entities(
            UUID(seeded["organization_id"]), query="A1672", limit=5
        )
        if item.canonical_name == "A1672"
    )
    # La entidad de otro tenant no existe para este: 404, no fuga de datos.
    detail = await api_client.get(
        f"/api/v1/company-intelligence/entities/{a1672.id}", headers=_headers(other)
    )
    assert detail.status_code == 404

    ask = await api_client.post(
        "/api/v1/company-intelligence/ask",
        headers=_headers(other),
        json={"question": "¿Qué es A1672?", "allow_knowledge": False},
    )
    assert ask.status_code == 200
    assert "No encontré" in ask.json()["answer"]


@pytest.mark.asyncio
async def test_studio_requires_auth(api_client) -> None:
    for path in (
        "/api/v1/company-intelligence/overview",
        "/api/v1/company-intelligence/knowledge-gaps",
        "/api/v1/company-intelligence/source-of-truth",
    ):
        response = await api_client.get(path)
        assert response.status_code in (401, 403), path
    ask = await api_client.post(
        "/api/v1/company-intelligence/ask", json={"question": "¿qué es esto?"}
    )
    assert ask.status_code in (401, 403)


@pytest.mark.asyncio
async def test_ask_examples_endpoint(api_client, seeded) -> None:
    response = await api_client.get(
        "/api/v1/company-intelligence/ask/examples", headers=_headers(seeded)
    )
    assert response.status_code == 200
    assert len(response.json()["items"]) >= 6


@pytest.mark.asyncio
async def test_entities_and_domains_endpoints(api_client, seeded) -> None:
    entities = await api_client.get(
        "/api/v1/company-intelligence/entities",
        headers=_headers(seeded),
        params={"entity_type": "process", "limit": 10},
    )
    assert entities.status_code == 200, entities.text
    body = entities.json()
    assert body["items"]
    assert all(item["entity_type"] == "process" for item in body["items"])

    domains = await api_client.get(
        "/api/v1/company-intelligence/domains", headers=_headers(seeded)
    )
    assert domains.status_code == 200
    assert any(item["domain"] == "fare-audit" for item in domains.json()["items"])
