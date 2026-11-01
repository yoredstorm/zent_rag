# =============================================================================
# P18.5-02 — Un UUID no concede acceso: run, approvals y samples por workspace.
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.test_workflow_published_snapshot import _marker_graph
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


async def _workflow_and_run(
    client: AsyncClient, org: dict, workspace: dict
) -> tuple[str, str]:
    created = await client.post(
        "/api/v1/workflows",
        headers={
            **_ws_headers(org, workspace["id"]),
            "Idempotency-Key": f"p185-{uuid4().hex}",
        },
        json={
            "name": "P18.5 workspace",
            "trigger_type": "webhook",
            "workspace_id": workspace["id"],
            "graph": _marker_graph("A"),
            "workflow_version": 2,
        },
    )
    assert created.status_code == 200, created.text
    workflow_id = created.json()["workflow_id"]
    run = await client.post(
        f"/api/v1/workflows/{workflow_id}/run",
        headers={
            **_ws_headers(org, workspace["id"]),
            "Idempotency-Key": f"p185-run-{uuid4().hex}",
        },
        json={"payload": {"message": "hola"}, "simulate": False},
    )
    assert run.status_code == 200, run.text
    body = run.json()
    run_id = body.get("run_id") or (body.get("run") or {}).get("run_id")
    assert run_id, body
    return workflow_id, run_id


@pytest.mark.asyncio
async def test_run_detail_is_scoped_to_workspace(async_client: AsyncClient) -> None:
    org = await _org(async_client, "P18.5 WS Run")
    ws_a = await _default_workspace(async_client, org)
    created = await async_client.post(
        "/api/v1/workspaces", headers=_headers(org), json={"name": "Workspace B"}
    )
    assert created.status_code == 201, created.text
    ws_b = created.json()
    workflow_id, run_id = await _workflow_and_run(async_client, org, ws_a)

    own = await async_client.get(
        f"/api/v1/workflows/runs/{run_id}", headers=_ws_headers(org, ws_a["id"])
    )
    assert own.status_code == 200, own.text
    assert own.json()["workflow_id"] == workflow_id
    assert own.json()["has_provenance"] is True

    foreign = await async_client.get(
        f"/api/v1/workflows/runs/{run_id}", headers=_ws_headers(org, ws_b["id"])
    )
    assert foreign.status_code == 404, foreign.text
    assert run_id not in foreign.text

    no_workspace = await async_client.get(
        f"/api/v1/workflows/runs/{run_id}", headers=_headers(org)
    )
    # Sin header, el servidor usa el workspace activo de la membresía (no eleva).
    assert no_workspace.status_code == 200, no_workspace.text
    assert no_workspace.json()["workspace_id"] == ws_a["id"]

    from uuid import UUID

    from src.platform.workflows.access import WorkflowAccessDenied, assert_run_access

    with pytest.raises(WorkflowAccessDenied) as denied:
        await assert_run_access(UUID(org["organization_id"]), UUID(run_id), None)
    assert denied.value.status_code == 400

    approvals_b = await async_client.get(
        f"/api/v1/workflows/runs/{run_id}/approvals",
        headers=_ws_headers(org, ws_b["id"]),
    )
    assert approvals_b.status_code == 404, approvals_b.text

    samples_a = await async_client.get(
        f"/api/v1/workflows/{workflow_id}/sample-outputs",
        headers=_ws_headers(org, ws_a["id"]),
    )
    assert samples_a.status_code == 200, samples_a.text
    assert samples_a.json()["run_id"] == run_id

    samples_b = await async_client.get(
        f"/api/v1/workflows/{workflow_id}/sample-outputs",
        headers=_ws_headers(org, ws_b["id"]),
    )
    assert samples_b.status_code == 404, samples_b.text


@pytest.mark.asyncio
async def test_workspace_header_must_belong_to_organization(
    async_client: AsyncClient,
) -> None:
    org_a = await _org(async_client, "P18.5 WS Header A")
    ws_a = await _default_workspace(async_client, org_a)
    _, run_id = await _workflow_and_run(async_client, org_a, ws_a)

    org_b = await _org(async_client, "P18.5 WS Header B")
    ws_b = await _default_workspace(async_client, org_b)
    forged = await async_client.get(
        f"/api/v1/workflows/runs/{run_id}", headers=_ws_headers(org_a, ws_b["id"])
    )
    # El header pertenece a otra organización: 404 sin revelar el run.
    assert forged.status_code == 404, forged.text


@pytest.mark.asyncio
async def test_org_global_run_remains_readable_without_workspace(
    async_client: AsyncClient,
) -> None:
    org = await _org(async_client, "P18.5 WS Global")
    created = await async_client.post(
        "/api/v1/workflows",
        headers={**_headers(org), "Idempotency-Key": f"p185-{uuid4().hex}"},
        json={
            "name": "P18.5 global",
            "trigger_type": "webhook",
            "graph": _marker_graph("G"),
            "workflow_version": 2,
        },
    )
    assert created.status_code == 200, created.text
    workflow_id = created.json()["workflow_id"]
    detail = await async_client.get(
        f"/api/v1/workflows/{workflow_id}", headers=_headers(org)
    )
    if detail.json().get("workspace_id"):
        pytest.skip("el owner tiene workspace activo; el caso global ya está cubierto")
    run = await async_client.post(
        f"/api/v1/workflows/{workflow_id}/run",
        headers={**_headers(org), "Idempotency-Key": f"p185-{uuid4().hex}"},
        json={"payload": {"message": "hola"}, "simulate": False},
    )
    assert run.status_code == 200, run.text
    run_id = run.json().get("run_id") or (run.json().get("run") or {}).get("run_id")
    read = await async_client.get(
        f"/api/v1/workflows/runs/{run_id}", headers=_headers(org)
    )
    assert read.status_code == 200, read.text
