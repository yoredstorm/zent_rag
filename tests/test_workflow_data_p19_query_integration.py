# =============================================================================
# P19-01 — Integración real con PostgreSQL Managed DB.
#
# Crea una base gestionada efímera, una tabla de precios y un plan canónico.
# Comprueba filas reales, parámetros ligados y que la sesión de lectura rechaza
# escrituras. No usa datos de clientes ni proveedores externos.
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text

from src.core.domain.entities import TenantContext
from src.infrastructure.postgres.relational_db import (
    PostgresOrganizationRepository,
    PostgresWorkspaceRepository,
)
from src.platform.managed_db.service import (
    open_managed_query_session,
    provision_managed_database,
    run_schema_admin_sql,
)
from src.platform.workflows.bindings import _execute_managed_select, upsert_binding


async def _cleanup(db_name: str, roles: list[str]) -> None:
    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        await session.execute(text("COMMIT"))
        await session.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
        for role in roles:
            await session.execute(text(f'DROP ROLE IF EXISTS "{role}"'))
        await session.commit()
    except Exception:  # noqa: BLE001 - limpieza best-effort
        await session.rollback()
    finally:
        await session.close()


async def test_p19_01_real_managed_query_is_parameterized_and_read_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.platform.managed_db import service as managed_service

    async def _allow(*_args, **_kwargs):
        return None

    async def _entitlements(*_args, **_kwargs):
        return {"entitlements": {"managed_db": True, "managed_db_max_mb": 256}}

    monkeypatch.setattr(managed_service, "check_entitlement", _allow)
    monkeypatch.setattr(managed_service, "get_org_entitlements", _entitlements)

    organization = await PostgresOrganizationRepository().create_organization(uuid4(), f"P19 Query {uuid4().hex[:6]}")
    workspace = await PostgresWorkspaceRepository().create_workspace(organization.id, "Default", "default")
    ctx = TenantContext(
        tenant_id=organization.id,
        roles=frozenset({"owner"}),
        permissions=frozenset({"*"}),
        scopes=frozenset({"portal"}),
        auth_type="portal_session",
    )
    managed = await provision_managed_database(ctx, workspace.id)
    roles = [
        f"zent_schema_admin_{str(organization.id).replace('-', '')[:8]}_{str(workspace.id).replace('-', '')[:8]}",
        f"zent_query_reader_{str(organization.id).replace('-', '')[:8]}_{str(workspace.id).replace('-', '')[:8]}",
    ]
    try:
        await run_schema_admin_sql(
            organization.id,
            workspace.id,
            'CREATE TABLE IF NOT EXISTS "p19_prices" ('
            '"sku" TEXT NOT NULL, "channel" TEXT NOT NULL, '
            '"price" NUMERIC(12,2) NOT NULL, "currency" TEXT NOT NULL);',
        )
        await run_schema_admin_sql(
            organization.id,
            workspace.id,
            'INSERT INTO "p19_prices" ("sku", "channel", "price", "currency") VALUES '
            "('ARR-001', 'retail', 5.00, 'PEN'), "
            "('ARR-002', 'retail', 6.50, 'PEN'), "
            "('ARR-001', 'wholesale', 4.50, 'PEN');",
        )
        plan = {
            "schema": "zent.data.query.binding/v1",
            "scope": "workspace",
            "resource": {"schema": "public", "name": "p19_prices", "kind": "table"},
            "operation": "get_one",
            "projection": ["sku", "price", "currency"],
            "allowed_columns": ["sku", "price", "currency", "channel"],
            "required_predicates": [{"field": "channel", "op": "eq", "source": "binding", "value": "retail"}],
            "parameters": [
                {
                    "name": "sku",
                    "field": "sku",
                    "operator": "eq",
                    "type": "string",
                    "required": True,
                }
            ],
            "policy": {"max_rows": 1, "timeout_ms": 3000, "read_only": True},
            "column_types": {"sku": "string", "price": "number", "currency": "string"},
        }
        binding = await upsert_binding(
            organization.id,
            f"p19.price.{uuid4().hex[:8]}",
            "managed_db",
            config=plan,
            workspace_id=workspace.id,
        )

        result = await _execute_managed_select(
            organization.id,
            binding,
            {"params": {"sku": "ARR-001"}},
            workspace_id=workspace.id,
        )
        assert result["status"] == "FOUND"
        assert result["found"] is True
        assert result["record"]["sku"] == "ARR-001"
        assert result["record"]["currency"] == "PEN"
        assert float(result["record"]["price"]) == 5.0
        assert result["binding_hash"]
        assert "sql" not in result

        from src.platform.workflows.data_sources import get_resource_schema

        schema = await get_resource_schema(
            organization.id,
            workspace.id,
            "public.p19_prices",
            permissions={"workflows:read"},
        )
        names = [column["name"] for column in schema["columns"]]
        assert names == ["sku", "channel", "price", "currency"]
        assert all(column["sensitive"] is False for column in schema["columns"])

        injected = await _execute_managed_select(
            organization.id,
            binding,
            {"params": {"sku": "ARR-001' OR 1=1 --"}},
            workspace_id=workspace.id,
        )
        assert injected["status"] == "NOT_FOUND"

        session = await open_managed_query_session(organization.id, workspace.id)
        assert session is not None
        try:
            with pytest.raises(Exception) as exc:
                await session.execute(
                    text(
                        'INSERT INTO "p19_prices" ("sku", "channel", "price", "currency") '
                        "VALUES ('X', 'retail', 1, 'PEN')"
                    )
                )
            assert "read-only" in str(exc.value).lower() or "read only" in str(exc.value).lower()
        finally:
            await session.close()
    finally:
        await _cleanup(managed["db_name"], roles)
