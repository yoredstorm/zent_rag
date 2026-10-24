# =============================================================================
# P05 — workspace debe filtrar lectura y acción, no solo el tenant.
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.test_workflow_durable_instances import _durable_graph
from tests.test_workflows import _create_org, _headers, _owner_session


async def _org(client: AsyncClient, name: str) -> dict:
    org = await _create_org(client, name)
    org["session"] = await _owner_session(client, org["organization_id"])
    return org


def _ws_headers(org: dict, workspace_id: str) -> dict:
    return {**_headers(org), "X-Workspace-Id": workspace_id}


async def _default_workspace(client: AsyncClient, org: dict) -> dict:
    listing = await client.get("/api/v1/workspaces", headers=_headers(org))
    assert listing.status_code == 200, listing.text
    return next(w for w in listing.json()["workspaces"] if w["slug"] == "default")


async def _wait_instance(
    client: AsyncClient, org: dict, ws_a: dict, name: str
) -> tuple[str, str]:
    workflow = await client.post(
        "/api/v1/workflows",
        headers=_ws_headers(org, ws_a["id"]),
        json={
            "name": name,
            "trigger_type": "webhook",
            "workspace_id": ws_a["id"],
            "graph": _durable_graph(),
            "workflow_version": 2,
        },
    )
    assert workflow.status_code == 200, workflow.text
    wid = workflow.json()["workflow_id"]
    started = await client.post(
        f"/api/v1/workflows/{wid}/instances",
        headers={
            **_ws_headers(org, ws_a["id"]),
            "Idempotency-Key": f"p05-{uuid4().hex}",
        },
        json={"payload": {"message": "hola"}},
    )
    assert started.status_code == 200, started.text
    return wid, started.json()["instance_id"]


@pytest.mark.asyncio
async def test_instance_list_does_not_leak_across_workspaces(
    async_client: AsyncClient,
) -> None:
    org = await _org(async_client, "P05 WS List")
    ws_a = await _default_workspace(async_client, org)
    created = await async_client.post(
        "/api/v1/workspaces", headers=_headers(org), json={"name": "Workspace B"}
    )
    assert created.status_code == 201, created.text
    ws_b = created.json()
    _, instance_id = await _wait_instance(async_client, org, ws_a, "WAIT en A")

    listed = await async_client.get(
        "/api/v1/workflows/instances", headers=_ws_headers(org, ws_b["id"])
    )
    assert listed.status_code == 200, listed.text
    ids = {item["id"] for item in listed.json().get("instances", [])}
    assert instance_id not in ids

    detail = await async_client.get(
        f"/api/v1/workflows/instances/{instance_id}",
        headers=_ws_headers(org, ws_b["id"]),
    )
    assert detail.status_code == 404


@pytest.mark.asyncio
async def test_create_workflow_rejects_foreign_workspace(
    async_client: AsyncClient,
) -> None:
    org_a = await _org(async_client, "P05 WS Create A")
    org_b = await _org(async_client, "P05 WS Create B")
    ws_b = await _default_workspace(async_client, org_b)

    response = await async_client.post(
        "/api/v1/workflows",
        headers=_headers(org_a),
        json={
            "name": "Workspace ajeno",
            "trigger_type": "webhook",
            "workspace_id": ws_b["id"],
            "graph": _durable_graph(),
            "workflow_version": 2,
        },
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_signal_from_other_workspace_is_denied(
    async_client: AsyncClient,
) -> None:
    org = await _org(async_client, "P05 WS Signal")
    ws_a = await _default_workspace(async_client, org)
    created = await async_client.post(
        "/api/v1/workspaces", headers=_headers(org), json={"name": "Workspace B2"}
    )
    assert created.status_code == 201, created.text
    ws_b = created.json()
    _, instance_id = await _wait_instance(async_client, org, ws_a, "WAIT señal A")

    detail = await async_client.get(
        f"/api/v1/workflows/instances/{instance_id}",
        headers=_ws_headers(org, ws_a["id"]),
    )
    event_type = detail.json().get("waiting_event_type")
    assert event_type

    signaled = await async_client.post(
        f"/api/v1/workflows/instances/{instance_id}/signal",
        headers=_ws_headers(org, ws_b["id"]),
        json={"event_type": event_type, "payload": {"message": "desde B"}},
    )
    assert signaled.status_code == 404
