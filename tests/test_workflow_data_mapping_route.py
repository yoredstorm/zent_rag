from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.test_workflows import _create_org, _headers, _owner_session


def _graph() -> dict:
    return {
        "workflow_version": 2,
        "nodes": [
            {"id": "t", "type": "trigger_webhook", "label": "Inicio", "config": {}},
            {"id": "end", "type": "end", "label": "Fin", "config": {}},
        ],
        "edges": [
            {
                "id": "e1",
                "from_node": "t",
                "from_port": "out",
                "to_node": "end",
                "to_port": "in",
            }
        ],
        "variables": {},
        "entrypoints": ["t"],
        "metadata": {
            "data_mapping": {
                "schema": "zent.data.mapping/v1",
                "sources": [
                    {
                        "id": "products",
                        "kind": "managed_db",
                        "fields": ["sku"],
                        "capability_ref": "catalog.products.search",
                    }
                ],
                "mappings": [
                    {"source_id": "products", "field": "sku", "target": "product"}
                ],
            }
        },
    }


async def _org(client: AsyncClient, name: str) -> dict:
    org = await _create_org(client, name)
    org["session"] = await _owner_session(client, org["organization_id"])
    return org


async def _workspace(client: AsyncClient, org: dict) -> dict:
    listing = await client.get("/api/v1/workspaces", headers=_headers(org))
    assert listing.status_code == 200, listing.text
    return next(w for w in listing.json()["workspaces"] if w["slug"] == "default")


@pytest.mark.asyncio
async def test_workflow_data_mapping_is_exposed_and_workspace_scoped(
    async_client: AsyncClient,
) -> None:
    org = await _org(async_client, "P06 Data Mapping")
    ws_a = await _workspace(async_client, org)
    created_b = await async_client.post(
        "/api/v1/workspaces", headers=_headers(org), json={"name": "Mapping B"}
    )
    assert created_b.status_code == 201, created_b.text
    ws_b = created_b.json()

    created = await async_client.post(
        "/api/v1/workflows",
        headers={
            **_headers(org),
            "X-Workspace-Id": ws_a["id"],
            "Idempotency-Key": f"p06-map-{uuid4().hex}",
        },
        json={
            "name": "Mapping real",
            "trigger_type": "webhook",
            "workspace_id": ws_a["id"],
            "graph": _graph(),
        },
    )
    assert created.status_code == 200, created.text
    workflow_id = created.json()["workflow_id"]

    response = await async_client.get(
        f"/api/v1/workflows/{workflow_id}/data-mapping",
        headers={**_headers(org), "X-Workspace-Id": ws_a["id"]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["errors"] == []
    assert body["mapping"]["schema"] == "zent.data.mapping/v1"
    assert body["inventory"]["duplicate_vector_store"] is False

    foreign = await async_client.get(
        f"/api/v1/workflows/{workflow_id}/data-mapping",
        headers={**_headers(org), "X-Workspace-Id": ws_b["id"]},
    )
    assert foreign.status_code == 404
