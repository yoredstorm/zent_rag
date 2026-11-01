# =============================================================================
# P19-06 — Integración con PostgreSQL externo fuera de Managed DB.
#
# Requiere la base externa de ops/p19-external y las variables:
#   P19_EXTERNAL_HOST=127.0.0.1
#   P19_EXTERNAL_PORT=55432
#   P19_EXTERNAL_DB=zent_external_mvp
#   P19_EXTERNAL_USER=p19_reader
#   P19_EXTERNAL_PASSWORD=p19_reader_dev_2026
# Sin ellas se declara SKIPPED, nunca PASS.
# =============================================================================
from __future__ import annotations

import os
from uuid import uuid4

import pytest

from src.infrastructure.postgres.relational_db import (
    PostgresConnectorRepository,
    PostgresOrganizationRepository,
    PostgresWorkspaceRepository,
)
from src.infrastructure.secrets.secret_store_resolver import get_secret_store
from src.platform.workflows.bindings import BindingError, _dispatch_binding

pytestmark = pytest.mark.skipif(
    not os.environ.get("P19_EXTERNAL_HOST"),
    reason="P19 external PostgreSQL not configured",
)


def _plan(connector_id) -> dict:
    return {
        "schema": "zent.data.query.binding/v1",
        "scope": "workspace",
        "connection_ref": str(connector_id),
        "resource": {"schema": "catalog", "name": "product_prices", "kind": "table"},
        "operation": "get_one",
        "projection": ["sku", "product_name", "price", "currency", "valid_from", "valid_to"],
        "allowed_columns": [
            "sku",
            "product_name",
            "price",
            "currency",
            "valid_from",
            "valid_to",
            "channel",
        ],
        "required_predicates": [
            {"field": "channel", "op": "eq", "source": "binding", "value": "retail"}
        ],
        "parameters": [
            {"name": "sku", "field": "sku", "operator": "eq", "type": "string", "required": True}
        ],
        "policy": {"max_rows": 1, "timeout_ms": 3000, "read_only": True},
        "column_types": {
            "sku": "string",
            "product_name": "string",
            "price": "number",
            "currency": "string",
            "valid_from": "date",
            "valid_to": "date",
        },
    }


async def test_connected_db_reads_external_postgres_without_managed_db() -> None:
    org = await PostgresOrganizationRepository().create_organization(
        uuid4(), f"P19 External {uuid4().hex[:6]}"
    )
    workspace = await PostgresWorkspaceRepository().create_workspace(
        org.id, "Default", "default"
    )
    connector = await PostgresConnectorRepository().create_connector(
        org.id,
        f"P19 External {uuid4().hex[:6]}",
        "postgres",
        workspace_id=workspace.id,
        config_json={
            "host": os.environ["P19_EXTERNAL_HOST"],
            "port": int(os.environ.get("P19_EXTERNAL_PORT", "55432")),
            "database": os.environ.get("P19_EXTERNAL_DB", "zent_external_mvp"),
            "user": os.environ.get("P19_EXTERNAL_USER", "p19_reader"),
            "ssl": False,
        },
    )
    await get_secret_store().put(
        org.id,
        connector.id,
        {"password": os.environ.get("P19_EXTERNAL_PASSWORD", "p19_reader_dev_2026")},
    )
    binding = {
        "id": str(uuid4()),
        "organization_id": str(org.id),
        "workspace_id": str(workspace.id),
        "capability_ref": "p19.external.price",
        "provider_kind": "connected_db",
        "config": _plan(connector.id),
        "credential_ref": None,
        "contract_input_schema": {},
        "contract_output_schema": {},
        "status": "active",
    }
    result = await _dispatch_binding(
        org.id,
        "p19.external.price",
        binding,
        {"params": {"sku": "ARR-001"}},
        kind="connected_db",
        workspace_id=workspace.id,
        source="test",
        actor_id=None,
        workflow_id=None,
        run_id=None,
        instance_id=None,
        node_id=None,
    )
    assert result["status"] == "FOUND"
    assert result["record"]["sku"] == "ARR-001"
    assert result["record"]["currency"] == "PEN"
    assert float(result["record"]["price"]) == 5.0
    assert result["source_ref"] == "table:catalog.product_prices"
    assert "sql_query" not in result

    injected = await _dispatch_binding(
        org.id,
        "p19.external.price",
        binding,
        {"params": {"sku": "ARR-001' OR 1=1 --"}},
        kind="connected_db",
        workspace_id=workspace.id,
        source="test",
        actor_id=None,
        workflow_id=None,
        run_id=None,
        instance_id=None,
        node_id=None,
    )
    assert injected["status"] == "NOT_FOUND"


async def test_connected_db_rejects_unexposed_connector() -> None:
    org = await PostgresOrganizationRepository().create_organization(
        uuid4(), f"P19 External Missing {uuid4().hex[:6]}"
    )
    workspace = await PostgresWorkspaceRepository().create_workspace(
        org.id, "Default", "default"
    )
    binding = {
        "id": str(uuid4()),
        "organization_id": str(org.id),
        "workspace_id": str(workspace.id),
        "capability_ref": "p19.external.price",
        "provider_kind": "connected_db",
        "config": _plan(uuid4()),
        "credential_ref": None,
        "contract_input_schema": {},
        "contract_output_schema": {},
        "status": "active",
    }
    with pytest.raises(BindingError) as exc:
        await _dispatch_binding(
            org.id,
            "p19.external.price",
            binding,
            {"params": {"sku": "ARR-001"}},
            kind="connected_db",
            workspace_id=workspace.id,
            source="test",
            actor_id=None,
            workflow_id=None,
            run_id=None,
            instance_id=None,
            node_id=None,
        )
    assert exc.value.code == "RESOURCE_NOT_EXPOSED"
