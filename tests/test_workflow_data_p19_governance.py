# =============================================================================
# P19.1-01 - Gobierno de publicacion: permisos, allowlist, PII y versionado.
# =============================================================================
from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from src.infrastructure.postgres.relational_db import (
    PostgresOrganizationRepository,
    PostgresWorkspaceRepository,
)
from src.infrastructure.postgres.session import get_async_session
from src.platform.workflows.bindings import upsert_binding
from src.platform.workflows.data_governance import (
    DataPolicyError,
    authorize_publication,
    get_publication_policy,
    save_publication_policy,
)
from src.platform.workflows.data_sources import (
    DataSourceError,
    preview_data_query,
    publish_data_query_plan,
)


async def _org_workspace(label: str):
    org = await PostgresOrganizationRepository().create_organization(
        uuid4(), f"{label} {uuid4().hex[:6]}"
    )
    workspace = await PostgresWorkspaceRepository().create_workspace(org.id, "Default", "default")
    return org, workspace


def _policy() -> dict:
    return {
        "schema": "zent.data.publication.policy/v1",
        "resources": [
            {
                "schema": "catalog",
                "table": "product_prices",
                "columns": ["sku", "product_name", "price", "currency", "customer_email"],
                "sensitive_columns": ["customer_email"],
                "operations": ["get_one", "list", "count"],
                "max_rows": 5,
            }
        ],
    }


def _connector(org_id, workspace_id, connector_id):
    return SimpleNamespace(
        id=connector_id,
        organization_id=org_id,
        workspace_id=workspace_id,
        name="P19.1 connector",
        type="postgres",
        status="active",
        config_json={"host": "127.0.0.1", "database": "demo", "user": "reader"},
    )


def _discovery():
    columns = [
        SimpleNamespace(name="sku", data_type="text", is_primary_key=True),
        SimpleNamespace(name="product_name", data_type="text", is_primary_key=False),
        SimpleNamespace(name="price", data_type="numeric", is_primary_key=False),
        SimpleNamespace(name="currency", data_type="text", is_primary_key=False),
        SimpleNamespace(name="customer_email", data_type="text", is_primary_key=False),
    ]
    table = SimpleNamespace(
        schema="catalog",
        name="product_prices",
        is_view=False,
        columns=columns,
    )
    return SimpleNamespace(tables=[table])


@pytest.mark.asyncio
async def test_publication_is_deny_by_default_and_separates_permissions() -> None:
    org, workspace = await _org_workspace("P19.1 Gov")
    connector_id = uuid4()

    with pytest.raises(DataPolicyError) as exc:
        await authorize_publication(
            org.id,
            workspace.id,
            connector_id,
            schema_name="catalog",
            table_name="product_prices",
            operation="get_one",
            fields={"sku", "price"},
            permissions={"workflows:update"},
            purpose="",
        )
    assert exc.value.code == "PERMISSION_DENIED"

    with pytest.raises(DataPolicyError) as exc:
        await authorize_publication(
            org.id,
            workspace.id,
            connector_id,
            schema_name="catalog",
            table_name="product_prices",
            operation="get_one",
            fields={"sku", "price"},
            permissions={"data_queries:publish"},
            purpose="",
        )
    assert exc.value.code == "POLICY_REQUIRED"

    saved = await save_publication_policy(
        org.id, workspace.id, connector_id, _policy(), actor_id=None
    )
    assert saved["version"] == 1
    assert len(saved["policy_hash"]) == 64

    stored = await get_publication_policy(org.id, workspace.id, connector_id)
    assert stored is not None
    assert stored["policy_hash"] == saved["policy_hash"]

    _, sensitive, max_rows = await authorize_publication(
        org.id,
        workspace.id,
        connector_id,
        schema_name="catalog",
        table_name="product_prices",
        operation="list",
        fields={"sku", "price"},
        permissions={"data_queries:publish"},
        purpose="",
    )
    assert sensitive == set()
    assert max_rows == 5

    with pytest.raises(DataPolicyError) as exc:
        await authorize_publication(
            org.id,
            workspace.id,
            connector_id,
            schema_name="catalog",
            table_name="product_prices",
            operation="get_one",
            fields={"customer_email"},
            permissions={"data_queries:publish"},
            purpose="soporte de pedido",
        )
    assert exc.value.code == "SENSITIVE_COLUMN_DENIED"

    with pytest.raises(DataPolicyError) as exc:
        await authorize_publication(
            org.id,
            workspace.id,
            connector_id,
            schema_name="catalog",
            table_name="product_prices",
            operation="get_one",
            fields={"customer_email"},
            permissions={"data_queries:publish", "data_queries:publish_sensitive"},
            purpose="short",
        )
    assert exc.value.code == "PURPOSE_REQUIRED"

    _, sensitive, _ = await authorize_publication(
        org.id,
        workspace.id,
        connector_id,
        schema_name="catalog",
        table_name="product_prices",
        operation="get_one",
        fields={"customer_email"},
        permissions={"data_queries:publish", "data_queries:publish_sensitive"},
        purpose="verificar correo del titular autenticado",
    )
    assert sensitive == {"customer_email"}

    with pytest.raises(DataPolicyError) as exc:
        await authorize_publication(
            org.id,
            workspace.id,
            connector_id,
            schema_name="pg_catalog",
            table_name="pg_user",
            operation="list",
            fields={"usename"},
            permissions={"data_queries:publish"},
            purpose="",
        )
    assert exc.value.code == "SYSTEM_SCHEMA_DENIED"


@pytest.mark.asyncio
async def test_publish_never_overwrites_capability_and_audits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.connectors import plugin as plugin_module
    from src.infrastructure.postgres import relational_db
    from src.infrastructure.secrets import secret_store_resolver

    org, workspace = await _org_workspace("P19.1 Publish")
    connector_id = uuid4()
    connector = _connector(org.id, workspace.id, connector_id)

    class _FakePlugin:
        async def discover(self):
            return _discovery()

        async def close(self):
            return None

    class _FakeSecrets:
        async def get(self, organization_id, ref):
            return {"password": "not-a-real-secret"}

    async def _get_connector(self, organization_id, ref):
        return connector if UUID(str(ref)) == connector_id else None

    monkeypatch.setattr(plugin_module, "get_plugin", lambda *args, **kwargs: _FakePlugin())
    monkeypatch.setattr(secret_store_resolver, "get_secret_store", lambda: _FakeSecrets())
    monkeypatch.setattr(
        relational_db.PostgresConnectorRepository, "get_connector", _get_connector
    )

    await save_publication_policy(
        org.id, workspace.id, connector_id, _policy(), actor_id=None
    )

    body = {
        "connector_ref": f"connector:{connector_id}",
        "resource_ref": "catalog.product_prices",
        "operation": "get_one",
        "projection": ["sku", "product_name", "price", "currency"],
        "parameter": {
            "name": "sku",
            "field": "sku",
            "operator": "eq",
            "type": "string",
            "required": True,
        },
        "max_rows": 1,
        "capability_ref": "data.fixed.ref.that.must.be.ignored",
        "label": "Precio",
    }
    first = await publish_data_query_plan(
        org.id,
        workspace.id,
        body,
        permissions={"data_queries:publish"},
        actor_id=None,
    )
    second = await publish_data_query_plan(
        org.id,
        workspace.id,
        {**body, "label": "Precio v2"},
        permissions={"data_queries:publish"},
        actor_id=None,
    )
    assert first["binding_ref"] != second["binding_ref"]
    assert first["capability_ref"] != second["capability_ref"]
    assert first["capability_ref"] != body["capability_ref"]
    assert first["policy_hash"]
    assert first["sensitive_columns"] == []

    session = await get_async_session()
    try:
        count = (
            await session.execute(
                text_count(),
                {"oid": str(org.id), "wid": str(workspace.id)},
            )
        ).scalar_one()
    finally:
        await session.close()
    assert count == 2


def text_count():
    from sqlalchemy import text

    return text(
        "SELECT COUNT(*) FROM data_query_publication_events "
        "WHERE organization_id = :oid AND workspace_id = :wid AND action = 'plan.published'"
    )


@pytest.mark.asyncio
async def test_publish_rejects_sensitive_without_explicit_grant() -> None:
    org, workspace = await _org_workspace("P19.1 PII")
    connector_id = uuid4()
    await save_publication_policy(
        org.id, workspace.id, connector_id, _policy(), actor_id=None
    )
    with pytest.raises(DataPolicyError) as exc:
        await authorize_publication(
            org.id,
            workspace.id,
            connector_id,
            schema_name="catalog",
            table_name="product_prices",
            operation="list",
            fields={"sku", "customer_email"},
            permissions={"data_queries:publish"},
            purpose="",
        )
    assert exc.value.code == "SENSITIVE_COLUMN_DENIED"


@pytest.mark.asyncio
async def test_preview_rejects_stale_policy_without_querying(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org, workspace = await _org_workspace("P19.1 Stale")
    connector_id = uuid4()
    plan = {
        "schema": "zent.data.query.binding/v1",
        "scope": "workspace",
        "connection_ref": str(connector_id),
        "resource": {"schema": "catalog", "name": "product_prices", "kind": "table"},
        "operation": "get_one",
        "projection": ["sku", "price"],
        "allowed_columns": ["sku", "price"],
        "policy": {"max_rows": 1},
        "policy_hash": "0" * 64,
    }
    binding = await upsert_binding(
        org.id,
        f"p19.stale.{uuid4().hex[:8]}",
        "connected_db",
        config=plan,
        workspace_id=workspace.id,
    )
    await save_publication_policy(
        org.id, workspace.id, connector_id, _policy(), actor_id=None
    )

    async def _must_not_run(*args, **kwargs):
        raise AssertionError("no debe ejecutar SQL con policy stale")

    monkeypatch.setattr(
        "src.platform.workflows.bindings._execute_connected_select", _must_not_run
    )
    with pytest.raises(DataSourceError) as exc:
        await preview_data_query(
            org.id,
            workspace.id,
            UUID(binding["id"]),
            {},
            permissions={"data_queries:preview"},
        )
    assert exc.value.code == "POLICY_STALE"
