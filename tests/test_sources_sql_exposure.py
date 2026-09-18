# =============================================================================
# Exponer la tabla materializada (A+B): preview y SQL read-only por fuente
# =============================================================================
# Flujo real: org trial → Managed DB provisionada → upload + ingesta (engine
# inline) → materialización → endpoints del portal:
#   GET  /sources/{id}/table-preview  (Managed DB o fallback canónico)
#   POST /sources/{id}/sql            (SELECT-only, whitelist de la fuente)
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.main import app
from src.core.config import get_settings
from src.core.domain.entities import TenantContext
from src.infrastructure.postgres.relational_db import (
    PostgresUserRepository,
    PostgresWorkspaceRepository,
)
from src.platform.managed_db.service import provision_managed_database
from tests import tabular_fixtures as fx


async def _create_org(client: AsyncClient, name: str) -> dict:
    response = await client.post(
        "/api/v1/billing/subscription/create-trial",
        json={
            "company_name": name,
            "email": f"sql-exp-{uuid4().hex[:8]}@example.com",
            "country": "CL",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _owner_session(organization_id: str) -> str:
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
def isolated_settings(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(
        settings, "KNOWLEDGE_QUEUE_KEY", f"rag:knowledge:queue:test:{uuid4().hex}"
    )
    monkeypatch.setattr(settings, "KNOWLEDGE_TABULAR_MANAGED_DB_ENABLED", True)
    return settings


@pytest.fixture
async def org(async_client: AsyncClient) -> dict:
    organization = await _create_org(async_client, "SQL Exposure")
    organization["session"] = await _owner_session(organization["organization_id"])
    return organization


async def _provision_and_ingest(async_client: AsyncClient, org: dict) -> tuple[str, str]:
    """Provisiona Managed DB, sube el xlsx, corre el engine y materializa."""
    from src.core.domain.entities import IngestionJobStatus
    from src.infrastructure.postgres.knowledge_repos import (
        PostgresDocumentRegistryRepository,
        PostgresIngestionJobRepository,
        PostgresSourceRepository,
        PostgresSyncStateRepository,
    )
    from src.infrastructure.postgres.relational_db import (
        PostgresKnowledgeBaseRepository,
    )
    from src.infrastructure.postgres.structured_documents import (
        PostgresStructuredDocumentRepository,
    )
    from src.infrastructure.postgres.tabular import PostgresTabularRepository
    from src.knowledge.engine.service import KnowledgeIngestionEngine
    from src.platform.managed_db import service as managed_service
    from tests.test_knowledge_jobs import FakeEmbedding
    from tests.test_tabular_ingestion_engine import FakeVectorStore

    organization_id = UUID(org["organization_id"])

    async def _allow(*_args, **_kwargs):
        return None

    async def _entitlements(*_args, **_kwargs):
        return {"entitlements": {"managed_db": True, "managed_db_max_mb": 256}}

    original_check = managed_service.check_entitlement
    original_ents = managed_service.get_org_entitlements
    managed_service.check_entitlement = _allow
    managed_service.get_org_entitlements = _entitlements
    try:
        workspaces = await PostgresWorkspaceRepository().list_workspaces(organization_id)
        assert workspaces, "la org trial debe tener workspace"
        workspace = workspaces[0]
        ctx = TenantContext(
            tenant_id=organization_id,
            roles=frozenset({"owner"}),
            permissions=frozenset({"*"}),
            scopes=frozenset({"portal"}),
            auth_type="portal_session",
        )
        await provision_managed_database(ctx, workspace.id)

        kb_response = await async_client.post(
            "/api/v1/knowledge-bases",
            headers=_headers(org),
            json={"name": "KB sql exposure", "chunking_strategy": "fixed"},
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
        return source["id"], str(workspace.id)
    finally:
        managed_service.check_entitlement = original_check
        managed_service.get_org_entitlements = original_ents


async def test_table_preview_and_sql_endpoints(
    async_client: AsyncClient, org: dict
) -> None:
    source_id, workspace_id = await _provision_and_ingest(async_client, org)
    try:
        preview = await async_client.get(
            f"/api/v1/sources/{source_id}/table-preview?limit=5",
            headers=_headers(org),
        )
        assert preview.status_code == 200, preview.text
        body = preview.json()
        assert body["origin"] == "managed_db"
        assert body["table"].startswith("zent_")
        assert body["count"] == 4  # el fixture tiene 4 filas de datos
        assert "field_name" in body["columns"]
        assert any("Carrier Code" in str(cell) for row in body["rows"] for cell in row)

        sql = await async_client.post(
            f"/api/v1/sources/{source_id}/sql",
            headers=_headers(org),
            json={
                "query": (
                    f'SELECT field_name, start_position FROM "{body["table"]}" '
                    "WHERE field_name = 'Carrier Code' ORDER BY start_position"
                )
            },
        )
        assert sql.status_code == 200, sql.text
        payload = sql.json()
        assert payload["columns"] == ["field_name", "start_position"]
        assert payload["rows"] == [["Carrier Code", 28]]
        assert payload["truncated"] is False

        # Whitelist: otra tabla (de la plataforma) debe rechazarse.
        forbidden = await async_client.post(
            f"/api/v1/sources/{source_id}/sql",
            headers=_headers(org),
            json={"query": "SELECT * FROM organizations"},
        )
        assert forbidden.status_code == 403, forbidden.text

        # Solo SELECT: DELETE debe rechazarse.
        delete = await async_client.post(
            f"/api/v1/sources/{source_id}/sql",
            headers=_headers(org),
            json={"query": f'DELETE FROM "{body["table"]}"'},
        )
        assert delete.status_code == 400, delete.text
    finally:
        from src.platform.managed_db.service import get_managed_database
        from tests.test_managed_db_provisioning import _cleanup

        try:
            managed = await get_managed_database(
                UUID(org["organization_id"]), UUID(workspace_id)
            )
        except Exception:  # noqa: BLE001
            managed = None
        if managed:
            roles = [
                f"zent_schema_admin_{org['organization_id'].replace('-', '')[:8]}_{workspace_id.replace('-', '')[:8]}",
                f"zent_query_reader_{org['organization_id'].replace('-', '')[:8]}_{workspace_id.replace('-', '')[:8]}",
            ]
            await _cleanup(managed["db_name"], roles)
