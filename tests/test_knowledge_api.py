# =============================================================================
# Knowledge Platform API — integración end-to-end + aislamiento cross-org
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.main import app
from src.core.config import get_settings


async def _create_org(client: AsyncClient, name: str) -> dict:
    response = await client.post(
        "/api/v1/billing/subscription/create-trial",
        json={
            "company_name": name,
            "email": f"kp-{uuid4().hex[:8]}@example.com",
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
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
async def org_a(async_client: AsyncClient) -> dict:
    org = await _create_org(async_client, "KP Org A")
    org["session"] = await _owner_session(org["organization_id"])
    return org


@pytest.fixture
async def org_b(async_client: AsyncClient) -> dict:
    org = await _create_org(async_client, "KP Org B")
    org["session"] = await _owner_session(org["organization_id"])
    return org


@pytest.fixture
def isolated_settings(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(
        settings, "KNOWLEDGE_QUEUE_KEY", f"rag:knowledge:queue:test:{uuid4().hex}"
    )
    return settings


# ---------------------------------------------------------------------------
# KB config
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kb_create_with_chunking_config(
    async_client, org_a, isolated_settings
) -> None:
    response = await async_client.post(
        "/api/v1/knowledge-bases",
        json={
            "name": "Docs KB",
            "chunking_strategy": "recursive",
            "chunk_size": 800,
            "chunk_overlap": 80,
            "retrieval_strategy": "vector",
            "reranker": None,
            "metadata_schema": {"fields": {"category": {"type": "str", "required": False}}},
        },
        headers=_headers(org_a),
    )
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["chunking_strategy"] == "recursive"
    assert data["chunk_size"] == 800
    assert data["chunk_overlap"] == 80
    assert data["metadata_schema"]["fields"]["category"]["type"] == "str"


@pytest.mark.asyncio
async def test_kb_rejects_invalid_chunking_strategy(
    async_client, org_a, isolated_settings
) -> None:
    response = await async_client.post(
        "/api/v1/knowledge-bases",
        json={"name": "Bad KB", "chunking_strategy": "quantum"},
        headers=_headers(org_a),
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Upload y sources
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_creates_file_source(async_client, org_a, isolated_settings) -> None:
    response = await async_client.post(
        "/api/v1/sources/files/upload",
        headers=_headers(org_a),
        files={"file": ("manual.txt", b"# Manual\n\nContenido del manual de prueba.", "text/plain")},
    )
    assert response.status_code == 201, response.text
    source = response.json()
    assert source["type"] == "file"
    assert source["config"]["object_key"]

    from src.knowledge.storage import resolve_path

    path = resolve_path(UUID(org_a["organization_id"]), source["config"]["object_key"])
    assert path.exists()


@pytest.mark.asyncio
async def test_upload_csv_autodetected(async_client, org_a, isolated_settings) -> None:
    csv_bytes = b"nombre,precio\nParacetamol,2.5\nIbuprofeno,3.0\n"
    response = await async_client.post(
        "/api/v1/sources/files/upload",
        headers=_headers(org_a),
        files={"file": ("catalogo.csv", csv_bytes, "text/csv")},
    )
    assert response.status_code == 201, response.text
    assert response.json()["type"] == "csv"


@pytest.mark.asyncio
async def test_source_discover(async_client, org_a, isolated_settings) -> None:
    upload = await async_client.post(
        "/api/v1/sources/files/upload",
        headers=_headers(org_a),
        files={"file": ("manual.txt", b"# Manual\n\nContenido.", "text/plain")},
    )
    source_id = upload.json()["id"]

    response = await async_client.post(
        f"/api/v1/sources/{source_id}/discover",
        headers=_headers(org_a),
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["type"] == "file"
    assert data["items"][0]["external_id"]


@pytest.mark.asyncio
async def test_sync_creates_job_and_engine_completes(
    async_client, org_a, isolated_settings
) -> None:
    # KB con chunking recursive
    kb = await async_client.post(
        "/api/v1/knowledge-bases",
        json={"name": "KP KB", "chunking_strategy": "recursive", "chunk_size": 500},
        headers=_headers(org_a),
    )
    kb_id = kb.json()["id"]

    upload = await async_client.post(
        "/api/v1/sources/files/upload?knowledge_base_id=" + kb_id,
        headers=_headers(org_a),
        files={"file": ("manual.txt", b"# Manual\n\nContenido del manual de prueba.", "text/plain")},
    )
    source_id = upload.json()["id"]

    sync = await async_client.post(
        f"/api/v1/sources/{source_id}/sync", headers=_headers(org_a)
    )
    assert sync.status_code == 200, sync.text
    job_id = sync.json()["job_id"]

    # Simular el worker: engine con vector store/embedder falsos
    from src.infrastructure.postgres.knowledge_repos import (
        PostgresDocumentRegistryRepository,
        PostgresIngestionJobRepository,
        PostgresSourceRepository,
        PostgresSyncStateRepository,
    )
    from src.infrastructure.postgres.relational_db import (
        PostgresKnowledgeBaseRepository,
    )
    from src.knowledge.engine.service import KnowledgeIngestionEngine
    from tests.test_knowledge_jobs import FakeEmbedding, FakeVectorStore

    engine = KnowledgeIngestionEngine(
        job_repo=PostgresIngestionJobRepository(),
        sync_state_repo=PostgresSyncStateRepository(),
        doc_registry_repo=PostgresDocumentRegistryRepository(),
        kb_repo=PostgresKnowledgeBaseRepository(),
        source_repo=PostgresSourceRepository(),
        vector_store=FakeVectorStore(),
        embedding_provider=FakeEmbedding(),
    )
    job = await engine.execute_job(UUID(job_id))
    assert job.status.value == "completed"
    assert job.records_processed == 1

    status = await async_client.get(f"/api/v1/jobs/{job_id}", headers=_headers(org_a))
    assert status.status_code == 200
    assert status.json()["status"] == "completed"
    assert status.json()["records_processed"] == 1


@pytest.mark.asyncio
async def test_api_token_cannot_manage_sources(async_client, org_a, isolated_settings) -> None:
    # El token de trial solo trae scopes rag:* — sin permiso sources:write
    response = await async_client.post(
        "/api/v1/sources",
        json={"name": "x", "type": "web", "config": {"url": "https://example.com"}},
        headers={
            "Authorization": f"Bearer {org_a['api_token']}",
            "X-Organization-Id": org_a["organization_id"],
        },
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Aislamiento cross-org
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cross_org_source_isolation(
    async_client, org_a, org_b, isolated_settings
) -> None:
    created = await async_client.post(
        "/api/v1/sources",
        json={"name": "A-only", "type": "web", "config": {"url": "https://example.com"}},
        headers=_headers(org_a),
    )
    assert created.status_code == 201, created.text
    source_id = created.json()["id"]

    # B no puede leer la fuente de A por ID -> 404 (no revela existencia)
    response = await async_client.get(
        f"/api/v1/sources/{source_id}", headers=_headers(org_b)
    )
    assert response.status_code == 404

    # B no la ve en sus listas
    listing = await async_client.get("/api/v1/sources", headers=_headers(org_b))
    names = [s["name"] for s in listing.json()["sources"]]
    assert "A-only" not in names

    # B no puede modificarla ni eliminarla
    response = await async_client.put(
        f"/api/v1/sources/{source_id}",
        json={"name": "hacked"},
        headers=_headers(org_b),
    )
    assert response.status_code == 404
    response = await async_client.delete(
        f"/api/v1/sources/{source_id}", headers=_headers(org_b)
    )
    assert response.status_code == 404

    # B no puede sincronizarla
    response = await async_client.post(
        f"/api/v1/sources/{source_id}/sync", headers=_headers(org_b)
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_cross_org_job_isolation(
    async_client, org_a, org_b, isolated_settings
) -> None:
    created = await async_client.post(
        "/api/v1/sources",
        json={"name": "job-src", "type": "web", "config": {"url": "https://example.com"}},
        headers=_headers(org_a),
    )
    source_id = created.json()["id"]
    sync = await async_client.post(
        f"/api/v1/sources/{source_id}/sync", headers=_headers(org_a)
    )
    job_id = sync.json()["job_id"]

    # B no puede ver el job de A
    response = await async_client.get(f"/api/v1/jobs/{job_id}", headers=_headers(org_b))
    assert response.status_code == 404

    # B no puede retry/cancel el job de A
    response = await async_client.post(
        f"/api/v1/jobs/{job_id}/retry", headers=_headers(org_b)
    )
    assert response.status_code == 404
    response = await async_client.post(
        f"/api/v1/jobs/{job_id}/cancel", headers=_headers(org_b)
    )
    assert response.status_code == 404

    # Y B no ve el job en su listado
    listing = await async_client.get("/api/v1/jobs", headers=_headers(org_b))
    assert job_id not in [j["id"] for j in listing.json()["jobs"]]


@pytest.mark.asyncio
async def test_upload_isolated_per_organization(async_client, org_a, org_b, isolated_settings) -> None:
    # Uploads de A quedan bajo el directorio de A; si B intenta usar el
    # object_key de A, resuelve DENTRO del directorio de B (donde no existe
    # el archivo) — jamás accede al contenido de A.
    from src.knowledge.storage import resolve_path

    upload = await async_client.post(
        "/api/v1/sources/files/upload",
        headers=_headers(org_a),
        files={"file": ("secreto.txt", b"secreto de A", "text/plain")},
    )
    object_key = upload.json()["config"]["object_key"]

    path_a = resolve_path(UUID(org_a["organization_id"]), object_key)
    assert path_a.exists()

    # B con el object_key de A: su ruta no existe (no hay leak)
    path_b = resolve_path(UUID(org_b["organization_id"]), object_key)
    assert not path_b.exists()

    # B no puede registrar una fuente 'file' apuntando al object_key de A
    response = await async_client.post(
        "/api/v1/sources",
        json={"name": "stolen", "type": "file", "config": {"object_key": object_key}},
        headers=_headers(org_b),
    )
    assert response.status_code == 201
    stolen_id = response.json()["id"]
    discover = await async_client.post(
        f"/api/v1/sources/{stolen_id}/discover", headers=_headers(org_b)
    )
    assert discover.status_code == 422  # archivo no encontrado en el dir de B


@pytest.mark.asyncio
async def test_spoofed_header_on_sources_rejected(
    async_client, org_a, org_b, isolated_settings
) -> None:
    response = await async_client.get(
        "/api/v1/sources",
        headers=_headers(org_a)
        | {"X-Organization-Id": org_b["organization_id"]},
    )
    assert response.status_code == 403
