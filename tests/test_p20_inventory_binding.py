# =============================================================================
# P20-16 — aislamiento de bindings de inventario por workspace.
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text

from src.infrastructure.postgres.relational_db import PostgresConnectorRepository
from src.infrastructure.postgres.session import get_async_session
from src.platform.workflows.bindings import BindingError
from src.platform.workflows.inventory_adapter import execute_inventory_action


async def _create_org_and_workspace(organization_id, workspace_id) -> None:
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO organizations (id, name, company_name) "
                "VALUES (:oid, :name, :name)"
            ),
            {"oid": str(organization_id), "name": "P20 inventory test"},
        )
        await session.execute(
            text(
                "INSERT INTO workspaces (id, organization_id, name, slug) "
                "VALUES (:wid, :oid, :name, :slug)"
            ),
            {
                "wid": str(workspace_id),
                "oid": str(organization_id),
                "name": "P20 workspace",
                "slug": f"p20-{str(workspace_id)[:8]}",
            },
        )
        await session.commit()
    finally:
        await session.close()


async def _cleanup(organization_id) -> None:
    session = await get_async_session()
    try:
        await session.execute(
            text("DELETE FROM connectors WHERE organization_id = :oid"),
            {"oid": str(organization_id)},
        )
        await session.execute(
            text("DELETE FROM organizations WHERE id = :oid"),
            {"oid": str(organization_id)},
        )
        await session.commit()
    finally:
        await session.close()


async def test_inventory_binding_rejects_other_workspace() -> None:
    organization_id = uuid4()
    owner_workspace = uuid4()
    other_workspace = uuid4()
    try:
        await _create_org_and_workspace(organization_id, owner_workspace)
        connector = await PostgresConnectorRepository().create_connector(
            organization_id,
            "ERP test",
            "postgres",
            workspace_id=owner_workspace,
            config_json={
                "host": "127.0.0.1",
                "port": 5432,
                "database": "none",
                "user": "none",
                "write": True,
            },
        )
        binding = {
            "config": {
                "connector_id": str(connector.id),
                "action": "commit_order_stock",
                "write": True,
            }
        }
        with pytest.raises(BindingError) as exc:
            await execute_inventory_action(
                organization_id,
                binding,
                {"order_number": "P20-TEST-1"},
                workspace_id=other_workspace,
            )
        assert exc.value.code == "PERMISSION_DENIED"
    finally:
        await _cleanup(organization_id)


async def test_inventory_binding_requires_write_flag() -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    try:
        await _create_org_and_workspace(organization_id, workspace_id)
        connector = await PostgresConnectorRepository().create_connector(
            organization_id,
            "ERP test",
            "postgres",
            workspace_id=workspace_id,
            config_json={
                "host": "127.0.0.1",
                "port": 5432,
                "database": "none",
                "user": "none",
                "write": False,
            },
        )
        binding = {
            "config": {
                "connector_id": str(connector.id),
                "action": "commit_order_stock",
                "write": False,
            }
        }
        with pytest.raises(BindingError) as exc:
            await execute_inventory_action(
                organization_id,
                binding,
                {"order_number": "P20-TEST-1"},
                workspace_id=workspace_id,
            )
        assert exc.value.code == "PERMISSION_DENIED"
    finally:
        await _cleanup(organization_id)
