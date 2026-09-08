# =============================================================================
# Phase 31C — Demo purge, transition, managed DB
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from src.agents.tools.sql_expert_postgres import assert_reader_runtime_secrets
from src.platform.managed_db.builder import to_ddl
from src.platform.managed_db.importer import infer_columns
from src.platform.managed_db.service import query_runtime_secrets


async def _create_org(client: AsyncClient, name: str) -> dict:
    resp = await client.post(
        "/api/v1/billing/subscription/create-trial",
        json={
            "company_name": name,
            "email": f"31c-{uuid4().hex[:8]}@example.com",
            "country": "CL",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _owner_session(organization_id: str) -> str:
    from src.infrastructure.postgres.relational_db import PostgresUserRepository
    from src.platform.auth.session import encrypt_session

    user = await PostgresUserRepository().get_by_external_id(
        UUID(organization_id), "default-admin"
    )
    assert user is not None
    return encrypt_session(user.id, UUID(organization_id))


def _headers(org: dict, workspace_id: str | None = None) -> dict:
    h = {
        "Authorization": f"Bearer {org['session']}",
        "X-Organization-Id": org["organization_id"],
    }
    if workspace_id:
        h["X-Workspace-Id"] = workspace_id
    return h


@pytest.mark.asyncio
async def test_start_with_my_data_creates_business_workspace(
    async_client: AsyncClient,
) -> None:
    org = await _create_org(async_client, "Trans A")
    org["session"] = await _owner_session(org["organization_id"])
    status = await async_client.get(
        "/api/v1/demo-transition/status", headers=_headers(org)
    )
    assert status.status_code == 200, status.text
    started = await async_client.post(
        "/api/v1/demo-transition/start-with-my-data",
        headers=_headers(org),
        json={"mode": "new_workspace", "name": "My Business"},
    )
    assert started.status_code == 200, started.text
    assert started.json()["workspace"]["kind"] == "business"
    listing = await async_client.get("/api/v1/workspaces", headers=_headers(org))
    kinds = {w["kind"] for w in listing.json()["workspaces"]}
    assert "business" in kinds


@pytest.mark.asyncio
async def test_demo_purge_idempotent(async_client: AsyncClient) -> None:
    from src.core.domain.entities import TenantContext
    from src.platform.demo_purge.service import DemoPurgeService

    org = await _create_org(async_client, "Purge Org")
    org["session"] = await _owner_session(org["organization_id"])
    listing = await async_client.get("/api/v1/workspaces", headers=_headers(org))
    wid = UUID(listing.json()["active_workspace_id"] or listing.json()["workspaces"][0]["id"])
    ctx = TenantContext(tenant_id=UUID(org["organization_id"]))
    svc = DemoPurgeService()
    first = await svc.purge(ctx, wid)
    second = await svc.purge(ctx, wid)
    assert second["idempotent"] is True
    assert first["after"] == second["after"]


@pytest.mark.asyncio
async def test_csv_infer_codigo_precio() -> None:
    cols = infer_columns(
        ["codigo", "descripcion", "precio", "stock"],
        [["A1", "Ibuprofeno", "12.50", "10"]],
    )
    names = {c["name"]: c["type"] for c in cols}
    assert names["Product Code"] == "Text"
    assert names["Description"] == "Text"
    assert names["Price"] == "Money"
    assert names["Stock"] == "Integer"


def test_sql_expert_strips_schema_admin() -> None:
    cleaned = query_runtime_secrets(
        {
            "password": "reader",
            "query_reader_password": "reader",
            "schema_admin_password": "admin-secret",
            "schema_admin_user": "zent_schema_admin_x",
        }
    )
    assert "schema_admin_password" not in cleaned
    assert cleaned["password"] == "reader"
    out = assert_reader_runtime_secrets(
        {"password": "reader", "schema_admin_password": "admin-secret"}
    )
    assert "schema_admin_password" not in out


def test_builder_ddl_contains_create_table() -> None:
    ddl = to_ddl(
        {
            "tables": [
                {
                    "name": "Products",
                    "fields": [
                        {"name": "Name", "type": "Text", "required": True},
                        {"name": "Price", "type": "Money"},
                    ],
                }
            ]
        }
    )
    assert "CREATE TABLE" in ddl
    assert "NUMERIC(19,4)" in ddl
