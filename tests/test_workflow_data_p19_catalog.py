# =============================================================================
# P19-02 — Catálogo de conexiones, recursos publicados y preview redactado.
#
# Los tests de catálogo usan metadatos locales (managed_databases y bindings).
# La introspección real se cubre en test_workflow_data_p19_query_integration.py.
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from src.infrastructure.postgres.relational_db import (
    PostgresOrganizationRepository,
    PostgresWorkspaceRepository,
)
from src.infrastructure.postgres.session import get_async_session
from src.platform.workflows.bindings import upsert_binding
from src.platform.workflows.data_sources import (
    DataSourceError,
    get_resource_schema,
    invalidate_data_catalog,
    list_data_query_plans,
    list_data_sources,
    list_published_resources,
    preview_data_query,
)


def _plan(*, resource: str = "p19_prices", projection: list[str] | None = None) -> dict:
    return {
        "schema": "zent.data.query.binding/v1",
        "scope": "workspace",
        "resource": {"schema": "public", "name": resource, "kind": "table"},
        "operation": "list",
        "projection": projection or ["sku", "price"],
        "allowed_columns": projection or ["sku", "price"],
        "policy": {"max_rows": 5},
        "resource_ref": f"public.{resource}",
    }


async def _org_workspace(label: str):
    org = await PostgresOrganizationRepository().create_organization(uuid4(), f"{label} {uuid4().hex[:6]}")
    workspace = await PostgresWorkspaceRepository().create_workspace(org.id, "Default", "default")
    return org, workspace


async def _managed_row(org_id, workspace_id, *, connector_id=None) -> str:
    db_id = uuid4()
    session = await get_async_session()
    try:
        if connector_id is not None:
            await session.execute(
                text(
                    "INSERT INTO connectors "
                    "(id, organization_id, name, type, status, workspace_id, config_json) "
                    "VALUES (:id, :oid, :name, 'postgres', 'active', :wid, '{}'::jsonb)"
                ),
                {
                    "id": str(connector_id),
                    "oid": str(org_id),
                    "name": f"p19-{connector_id.hex[:8]}",
                    "wid": str(workspace_id),
                },
            )
        await session.execute(
            text(
                "INSERT INTO managed_databases "
                "(id, organization_id, workspace_id, db_name, provider, status, connector_id) "
                "VALUES (:id, :oid, :wid, :db, 'local', 'ready', :cid)"
            ),
            {
                "id": str(db_id),
                "oid": str(org_id),
                "wid": str(workspace_id),
                "db": f"p19_{db_id.hex[:8]}",
                "cid": str(connector_id) if connector_id else None,
            },
        )
        await session.commit()
    finally:
        await session.close()
    return str(db_id)


@pytest.mark.asyncio
async def test_query_plans_expose_parameters_without_sql() -> None:
    org, workspace = await _org_workspace("P19 Plans")
    config = _plan(resource="plans_table")
    config["parameters"] = [
        {
            "name": "sku",
            "field": "sku",
            "operator": "eq",
            "type": "string",
            "required": True,
        }
    ]
    await upsert_binding(
        org.id,
        f"p19.plans.{uuid4().hex[:8]}",
        "managed_db",
        config=config,
        workspace_id=workspace.id,
    )
    invalidate_data_catalog(org.id, workspace.id)
    payload = await list_data_query_plans(
        org.id, workspace.id, permissions={"workflows:read"}
    )
    assert len(payload["plans"]) == 1
    plan = payload["plans"][0]
    assert plan["resource_ref"] == "public.plans_table"
    assert plan["parameters"][0]["name"] == "sku"
    assert "sql" not in plan


@pytest.mark.asyncio
async def test_sources_are_scoped_to_workspace_and_org() -> None:
    org, workspace = await _org_workspace("P19 Source")
    other_org, other_workspace = await _org_workspace("P19 Other")
    source_id = await _managed_row(org.id, workspace.id, connector_id=uuid4())
    await _managed_row(other_org.id, other_workspace.id, connector_id=uuid4())

    invalidate_data_catalog(org.id, workspace.id)
    payload = await list_data_sources(org.id, workspace.id, permissions={"workflows:read"})
    refs = [item["ref"] for item in payload["sources"]]
    assert f"managed_db:{source_id}" in refs
    assert all(item["ref"].startswith(("managed_db:", "connector:")) for item in payload["sources"])
    assert payload["sources"][0]["read_only"] is True


@pytest.mark.asyncio
async def test_resources_come_from_published_plans_only() -> None:
    org, workspace = await _org_workspace("P19 Resources")
    other_org, other_workspace = await _org_workspace("P19 Other Resources")
    await upsert_binding(
        org.id,
        f"p19.catalog.{uuid4().hex[:8]}",
        "managed_db",
        config=_plan(),
        workspace_id=workspace.id,
    )
    await upsert_binding(
        org.id,
        f"p19.legacy.{uuid4().hex[:8]}",
        "managed_db",
        config={"table": "legacy_table", "columns": ["id"]},
        workspace_id=workspace.id,
    )
    await upsert_binding(
        other_org.id,
        f"p19.other.{uuid4().hex[:8]}",
        "managed_db",
        config=_plan(resource="other_table"),
        workspace_id=other_workspace.id,
    )
    source_id = await _managed_row(org.id, workspace.id, connector_id=uuid4())

    invalidate_data_catalog(org.id, workspace.id)
    result = await list_published_resources(
        org.id,
        workspace.id,
        source_ref=f"managed_db:{source_id}",
        permissions={"workflows:read"},
    )
    refs = [item["resource_ref"] for item in result["resources"]]
    assert refs == ["public.p19_prices"]
    assert result["total"] == 1

    other = await list_published_resources(
        other_org.id,
        other_workspace.id,
        source_ref=None,
        permissions={"workflows:read"},
    )
    assert [item["resource_ref"] for item in other["resources"]] == ["public.other_table"]


@pytest.mark.asyncio
async def test_unknown_source_and_resource_do_not_leak() -> None:
    org, workspace = await _org_workspace("P19 Unknown")
    with pytest.raises(DataSourceError) as exc:
        await list_published_resources(
            org.id,
            workspace.id,
            source_ref=f"managed_db:{uuid4()}",
            permissions={"workflows:read"},
        )
    assert exc.value.code == "RESOURCE_NOT_EXPOSED"

    with pytest.raises(DataSourceError) as exc:
        await get_resource_schema(
            org.id,
            workspace.id,
            "public.not_published",
            permissions={"workflows:read"},
        )
    assert exc.value.code == "RESOURCE_NOT_EXPOSED"


@pytest.mark.asyncio
async def test_preview_redacts_sensitive_fields_and_rejects_other_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.platform.workflows.data_sources as data_sources

    org, workspace = await _org_workspace("P19 Preview")
    other_org, other_workspace = await _org_workspace("P19 Preview Other")
    binding = await upsert_binding(
        org.id,
        f"p19.preview.{uuid4().hex[:8]}",
        "managed_db",
        config=_plan(projection=["customer_email", "points"]),
        workspace_id=workspace.id,
    )

    async def _fake_select(*_args, **_kwargs):
        return {
            "status": "FOUND",
            "found": True,
            "record": None,
            "rows": [{"customer_email": "a@example.com", "points": 10}],
            "columns": [],
            "row_count": 1,
            "truncated": False,
            "data_as_of": None,
            "source_ref": "public.p19_prices",
            "binding_ref": binding["id"],
            "binding_hash": "hash",
            "duration_ms": 1,
            "reason_code": None,
            "provenance": {},
        }

    monkeypatch.setattr(data_sources, "_execute_managed_select", _fake_select)
    result = await preview_data_query(
        org.id,
        workspace.id,
        UUID(binding["id"]),
        {},
        permissions={"data_queries:preview"},
    )
    assert result["preview"] is True
    assert result["result"]["rows"][0]["customer_email"] == "***"
    assert result["result"]["rows"][0]["points"] == 10
    assert "customer_email" in result["redacted_fields"]

    with pytest.raises(DataSourceError) as exc:
        await preview_data_query(
            other_org.id,
            other_workspace.id,
            UUID(binding["id"]),
            {},
            permissions={"data_queries:preview"},
        )
    assert exc.value.code == "RESOURCE_NOT_EXPOSED"


@pytest.mark.asyncio
async def test_catalog_api_lists_only_workspace_sources(
    async_client,
) -> None:
    from src.infrastructure.postgres.session import get_async_session
    from tests.test_workflows import _create_org, _headers, _owner_session

    org = await _create_org(async_client, f"P19 API {uuid4().hex[:6]}")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    org_id = org["organization_id"]
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text("SELECT id FROM workspaces WHERE organization_id = :oid LIMIT 1"),
                {"oid": org_id},
            )
        ).fetchone()
    finally:
        await session.close()
    assert row is not None
    workspace_id = str(row.id)
    source_id = await _managed_row(org_id, workspace_id, connector_id=uuid4())
    headers = {**_headers(org), "X-Workspace-Id": workspace_id}

    response = await async_client.get("/api/v1/workflows/data-sources", headers=headers)
    assert response.status_code == 200, response.text
    refs = [item["ref"] for item in response.json()["sources"]]
    assert f"managed_db:{source_id}" in refs

    resources = await async_client.get(
        f"/api/v1/workflows/data-sources/managed_db:{source_id}/resources",
        headers=headers,
    )
    assert resources.status_code == 200, resources.text
    assert resources.json()["resources"] == []

    missing = await async_client.post(
        "/api/v1/workflows/data-query/preview",
        headers=headers,
        json={"binding_id": str(uuid4()), "params": {}},
    )
    assert missing.status_code == 404
    assert "RESOURCE_NOT_EXPOSED" in missing.text


@pytest.mark.asyncio
async def test_revoked_connector_is_degraded() -> None:
    org, workspace = await _org_workspace("P19 Revoked")
    connector_id = uuid4()
    await _managed_row(org.id, workspace.id, connector_id=connector_id)
    session = await get_async_session()
    try:
        await session.execute(
            text("UPDATE connectors SET status = 'disabled' WHERE id = :cid"),
            {"cid": str(connector_id)},
        )
        await session.commit()
    finally:
        await session.close()
    invalidate_data_catalog(org.id, workspace.id)
    payload = await list_data_sources(org.id, workspace.id, permissions={"workflows:read"})
    assert payload["sources"][0]["status"] == "DEGRADED"


@pytest.mark.asyncio
async def test_binding_save_invalidates_catalog_cache() -> None:
    org, workspace = await _org_workspace("P19 Cache")
    invalidate_data_catalog(org.id, workspace.id)
    before = await list_published_resources(org.id, workspace.id, permissions={"workflows:read"})
    assert before["resources"] == []
    await upsert_binding(
        org.id,
        f"p19.cache.{uuid4().hex[:8]}",
        "managed_db",
        config=_plan(resource="cache_table"),
        workspace_id=workspace.id,
    )
    after = await list_published_resources(org.id, workspace.id, permissions={"workflows:read"})
    assert [item["resource_ref"] for item in after["resources"]] == ["public.cache_table"]
