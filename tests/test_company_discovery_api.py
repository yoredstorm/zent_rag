# =============================================================================
# Company Discovery API — smoke de endpoints tenant-scoped.
# Verifica permisos, paginación, el flujo encolar -> candidatos -> confirmar y
# la compilación de contexto, con dos organizaciones reales.
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
            "email": f"cd-{uuid4().hex[:8]}@example.com",
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


async def _drain_pending_runs() -> None:
    """Cierra los runs pendientes para que no contaminen otras corridas.

    `claim_pending_run` es global (lo usa el worker); un job encolado y no
    drenado haría fallar tests posteriores por orden de ejecución.
    """
    from dataclasses import replace

    from src.core.domain.company_discovery import DiscoveryRunStatus
    from src.infrastructure.postgres.company_discovery import (
        PostgresCompanyDiscoveryRepository,
    )

    store = PostgresCompanyDiscoveryRepository()
    for _ in range(20):
        claimed = await store.claim_pending_run()
        if claimed is None:
            return
        await store.save_run(replace(claimed, status=DiscoveryRunStatus.COMPLETED))


@pytest.fixture
async def api_client():
    from tests.conftest import attach_auto_idempotency

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield attach_auto_idempotency(client)


@pytest.fixture
async def org(api_client):
    created = await _create_org(api_client, "Company Discovery Org")
    created["session"] = await _owner_session(created["organization_id"])
    return created


@pytest.mark.asyncio
async def test_discovery_api_flow(api_client, org) -> None:
    """Encolar, listar candidatos, ver stats y compilar contexto."""
    # Sin datos aún: el listado responde paginado y vacío.
    listed = await api_client.get(
        "/api/v1/company-discovery/candidates",
        headers=_headers(org),
        params={"limit": 10, "offset": 0},
    )
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["items"] == []
    assert body["total"] == 0
    assert body["limit"] == 10

    stats = await api_client.get(
        "/api/v1/company-discovery/stats", headers=_headers(org)
    )
    assert stats.status_code == 200
    assert stats.json()["total"] == 0

    # Se puede poblar el grafo directamente (control admin) y luego compilar.
    created = await api_client.post(
        "/api/v1/company-graph/entities",
        headers=_headers(org),
        json={
            "entity_type": "concept",
            "canonical_name": "pending transaction",
            "aliases": ["pending"],
            "source": "manual",
        },
    )
    assert created.status_code == 201, created.text

    compiled = await api_client.post(
        "/api/v1/company-discovery/context/compile",
        headers=_headers(org),
        json={"request": "¿dónde se representa pending?", "max_concepts": 3},
    )
    assert compiled.status_code == 200, compiled.text
    payload = compiled.json()
    assert payload["tokens_estimate"] > 0
    assert payload["budget"]["max_concepts"] == 3

    preview = await api_client.post(
        "/api/v1/company-discovery/context/preview",
        headers=_headers(org),
        json={"request": "¿dónde se representa pending?"},
    )
    assert preview.status_code == 200, preview.text
    preview_body = preview.json()
    assert "agent_context" in preview_body
    assert "sql_hints" in preview_body
    assert "select " not in preview_body["sql_hints"].lower()

    # Encolar una corrida (no bloqueante) y ver el job durable.
    queued = await api_client.post(
        "/api/v1/company-discovery/runs",
        headers=_headers(org),
        json={"run_now": False},
    )
    assert queued.status_code == 202, queued.text
    run_id = queued.json()["run_id"]
    runs = await api_client.get(
        "/api/v1/company-discovery/runs", headers=_headers(org)
    )
    assert runs.status_code == 200
    assert run_id in {item["id"] for item in runs.json()["items"]}
    await _drain_pending_runs()

    gaps = await api_client.get(
        "/api/v1/company-discovery/gaps", headers=_headers(org)
    )
    assert gaps.status_code == 200 and gaps.json()["items"] == []
    conflicts = await api_client.get(
        "/api/v1/company-discovery/conflicts", headers=_headers(org)
    )
    assert conflicts.status_code == 200 and conflicts.json()["items"] == []


@pytest.mark.asyncio
async def test_discovery_api_is_tenant_scoped(api_client, org) -> None:
    other = await _create_org(api_client, "Company Discovery Other")
    other["session"] = await _owner_session(other["organization_id"])

    mine = await api_client.get(
        "/api/v1/company-discovery/candidates", headers=_headers(org)
    )
    theirs = await api_client.get(
        "/api/v1/company-discovery/candidates", headers=_headers(other)
    )
    assert mine.status_code == 200 and theirs.status_code == 200
    assert theirs.json()["items"] == []

    # Un candidato inexistente para el tenant responde 404, nunca 403 con datos.
    missing = await api_client.get(
        f"/api/v1/company-discovery/candidates/{uuid4()}", headers=_headers(other)
    )
    assert missing.status_code == 404

    invalid = await api_client.get(
        "/api/v1/company-discovery/candidates",
        headers=_headers(other),
        params={"kind": "not-a-kind"},
    )
    assert invalid.status_code == 400


@pytest.mark.asyncio
async def test_discovery_api_requires_auth(api_client) -> None:
    response = await api_client.get("/api/v1/company-discovery/candidates")
    assert response.status_code in (401, 403)
    bad_compile = await api_client.post(
        "/api/v1/company-discovery/context/compile", json={"request": "x"}
    )
    assert bad_compile.status_code in (401, 403)
