# =============================================================================
# Phase 31C — Managed PostgreSQL, builder, reader-only SQL Expert
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from src.agents.tools.sql_expert_postgres import assert_reader_runtime_secrets
from src.catalog.physical_resolver import _usable
from src.core.domain.catalog import MappingType
from src.platform.billing.entitlements import BOOL_KEYS, INT_KEYS
from src.platform.managed_db.builder import to_ddl
from src.platform.managed_db.importer import infer_columns
from src.platform.managed_db.local_postgres import LocalPostgresProvider
from src.platform.managed_db.service import query_runtime_secrets


def test_entitlement_keys_include_managed_db() -> None:
    assert "managed_db" in BOOL_KEYS
    assert "managed_db_backups" in BOOL_KEYS
    assert "managed_db_max_mb" in INT_KEYS


def test_query_runtime_strips_schema_admin() -> None:
    cleaned = query_runtime_secrets(
        {
            "password": "reader",
            "schema_admin_password": "admin-secret",
            "schema_admin_user": "zent_schema_admin_x",
        }
    )
    assert "schema_admin_password" not in cleaned
    assert "schema_admin_user" not in cleaned
    out = assert_reader_runtime_secrets(
        {"password": "reader", "schema_admin_password": "admin-secret"}
    )
    assert "schema_admin_password" not in out


def test_builder_ddl_and_approved_mapping_type() -> None:
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
    assert MappingType.APPROVED_BY_SCHEMA_DESIGN.value == "APPROVED_BY_SCHEMA_DESIGN"
    assert _usable(
        {
            "mapping_type": "APPROVED_BY_SCHEMA_DESIGN",
            "name": "Price",
            "status": "approved",
        }
    )


def test_local_provider_implements_protocol() -> None:
    provider = LocalPostgresProvider()
    for method in (
        "create_database",
        "delete_database",
        "rotate_credentials",
        "create_readonly_user",
        "create_schema_admin_user",
        "get_connection_info",
        "health_check",
        "backup_status",
        "execute_admin_ddl",
    ):
        assert callable(getattr(provider, method))


@pytest.mark.asyncio
async def test_managed_db_provision_does_not_leak_passwords(
    async_client: AsyncClient,
) -> None:
    resp = await async_client.post(
        "/api/v1/billing/subscription/create-trial",
        json={
            "company_name": "Managed Org",
            "email": f"mdb-{uuid4().hex[:8]}@example.com",
            "country": "CL",
        },
    )
    assert resp.status_code == 200, resp.text
    org = resp.json()
    from src.infrastructure.postgres.relational_db import PostgresUserRepository
    from src.platform.auth.session import encrypt_session

    user = await PostgresUserRepository().get_by_external_id(
        UUID(org["organization_id"]), "default-admin"
    )
    assert user is not None
    token = encrypt_session(user.id, UUID(org["organization_id"]))
    listing = await async_client.get(
        "/api/v1/workspaces",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Organization-Id": org["organization_id"],
        },
    )
    assert listing.status_code == 200, listing.text
    wid = listing.json()["workspaces"][0]["id"]
    created = await async_client.post(
        "/api/v1/managed-db",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Organization-Id": org["organization_id"],
            "X-Workspace-Id": wid,
        },
    )
    assert created.status_code in (201, 403), created.text
    if created.status_code == 201:
        body = created.json()
        assert "schema_admin_password" not in body
        assert "query_reader_password" not in body
        assert body.get("db_name")


def test_csv_infer_precio() -> None:
    cols = infer_columns(
        ["codigo", "descripcion", "precio", "stock"],
        [["A1", "Ibuprofeno", "12.50", "10"]],
    )
    names = {c["name"]: c["type"] for c in cols}
    assert names["Price"] == "Money"
