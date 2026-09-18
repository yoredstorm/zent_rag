# =============================================================================
# Knowledge Tabular V2 — API read contract (§35): /sources/{id}/tabular
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.main import app
from src.core.config import get_settings
from tests import tabular_fixtures as fx


async def _create_org(client: AsyncClient, name: str) -> dict:
    response = await client.post(
        "/api/v1/billing/subscription/create-trial",
        json={
            "company_name": name,
            "email": f"tab-api-{uuid4().hex[:8]}@example.com",
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
async def org_a(async_client: AsyncClient) -> dict:
    org = await _create_org(async_client, "Tabular API A")
    org["session"] = await _owner_session(org["organization_id"])
    return org


@pytest.fixture
async def org_b(async_client: AsyncClient) -> dict:
    org = await _create_org(async_client, "Tabular API B")
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


async def _upload_and_ingest(async_client: AsyncClient, org: dict) -> dict:
    """Sube ATPCO_TEST.xlsx a una KB y corre el engine (worker simulado)."""
    from src.core.domain.entities import IngestionJobStatus
    from src.infrastructure.postgres.knowledge_repos import (
        PostgresDocumentRegistryRepository,
        PostgresIngestionJobRepository,
        PostgresSourceRepository,
        PostgresSyncStateRepository,
    )
    from src.infrastructure.postgres.relational_db import PostgresKnowledgeBaseRepository
    from src.infrastructure.postgres.structured_documents import (
        PostgresStructuredDocumentRepository,
    )
    from src.infrastructure.postgres.tabular import PostgresTabularRepository
    from src.knowledge.engine.service import KnowledgeIngestionEngine
    from tests.test_knowledge_jobs import FakeEmbedding
    from tests.test_tabular_ingestion_engine import FakeVectorStore

    kb_response = await async_client.post(
        "/api/v1/knowledge-bases",
        headers=_headers(org),
        json={"name": "KB tabular API", "chunking_strategy": "fixed"},
    )
    assert kb_response.status_code == 201, kb_response.text
    kb_id = kb_response.json()["id"]

    upload = await async_client.post(
        "/api/v1/sources/files/upload",
        headers=_headers(org),
        params={"knowledge_base_id": kb_id},
        files={
            "file": (
                "ATPCO_TEST.xlsx",
                fx.atpco_workbook_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert upload.status_code == 201, upload.text
    source = upload.json()
    assert source["type"] == "excel"

    engine = KnowledgeIngestionEngine(
        job_repo=PostgresIngestionJobRepository(),
        sync_state_repo=PostgresSyncStateRepository(),
        doc_registry_repo=PostgresDocumentRegistryRepository(),
        kb_repo=PostgresKnowledgeBaseRepository(),
        source_repo=PostgresSourceRepository(),
        vector_store=FakeVectorStore(),
        embedding_provider=FakeEmbedding(),
        structured_doc_repo=PostgresStructuredDocumentRepository(),
        tabular_repo=PostgresTabularRepository(),
    )
    job = await engine.execute_job(UUID(source["job_id"]))
    assert job.status == IngestionJobStatus.COMPLETED, job.error_summary
    return {"source": source, "kb_id": kb_id}


@pytest.mark.asyncio
async def test_source_tabular_endpoint_exposes_structured_representation(
    async_client, org_a, org_b, isolated_settings
) -> None:
    context = await _upload_and_ingest(async_client, org_a)
    source = context["source"]

    response = await async_client.get(
        f"/api/v1/sources/{source['id']}/tabular", headers=_headers(org_a)
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["source_id"] == source["id"]
    assert len(payload["workbooks"]) == 1
    workbook = payload["workbooks"][0]
    assert workbook["filename"] == "ATPCO_TEST.xlsx"
    assert workbook["sheet_count"] == 1
    assert workbook["table_count"] == 1
    assert workbook["row_count"] == 4
    assert workbook["representations"] == {
        "structured": True,
        "semantic": True,
        "lexical": True,
    }
    assert workbook["quality_score"] > 0

    assert len(payload["tables"]) == 1
    table = payload["tables"][0]
    assert table["name"] == "ATPCO RECORD 2 RULES"
    assert table["workbook"] == "ATPCO_TEST.xlsx"
    assert table["row_count"] == 4
    assert table["header_rows"] == [4]
    assert table["detection_method"] == "heuristic"

    # Cross-tenant: la fuente de A no es visible para B.
    hidden = await async_client.get(
        f"/api/v1/sources/{source['id']}/tabular", headers=_headers(org_b)
    )
    assert hidden.status_code == 404


@pytest.mark.asyncio
async def test_kb_tabular_map_endpoint(
    async_client, org_a, org_b, isolated_settings
) -> None:
    context = await _upload_and_ingest(async_client, org_a)
    kb_id = context["kb_id"]

    response = await async_client.get(
        f"/api/v1/knowledge-bases/{kb_id}/tabular-map", headers=_headers(org_a)
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["knowledge_base_id"] == kb_id
    assert len(payload["workbooks"]) == 1
    workbook = payload["workbooks"][0]
    assert workbook["filename"] == "ATPCO_TEST.xlsx"
    assert workbook["representations"]["structured"] is True

    assert len(payload["tables"]) == 1
    table = payload["tables"][0]
    assert table["name"] == "ATPCO RECORD 2 RULES"
    assert table["sheet"] == "Record2"
    columns = {column["normalized_name"]: column for column in table["columns"]}
    assert "position" in columns["start_position"]["aliases"]
    assert columns["length"]["semantic_type"] == "length"

    rendered = payload["rendered"]
    assert "EXCEL MAP" in rendered
    assert "ATPCO RECORD 2 RULES" in rendered
    assert "Start Position" in rendered

    # Cross-tenant: KB de A no visible para B.
    hidden = await async_client.get(
        f"/api/v1/knowledge-bases/{kb_id}/tabular-map", headers=_headers(org_b)
    )
    assert hidden.status_code == 404
