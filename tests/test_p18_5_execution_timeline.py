# =============================================================================
# P18.5-08 — execution_timeline/v1: cursor, causalidad y redacción.
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from src.infrastructure.postgres.session import get_async_session
from tests.test_workflow_durable_instances import _durable_graph
from tests.test_workflows import _create_org, _headers, _owner_session


async def _org(client: AsyncClient, name: str) -> dict:
    org = await _create_org(client, name)
    org["session"] = await _owner_session(client, org["organization_id"])
    return org


async def _instance(client: AsyncClient, org: dict) -> tuple[str, str]:
    created = await client.post(
        "/api/v1/workflows",
        headers={**_headers(org), "Idempotency-Key": f"p185-{uuid4().hex}"},
        json={
            "name": "P18.5 timeline",
            "trigger_type": "webhook",
            "graph": _durable_graph(),
            "workflow_version": 2,
        },
    )
    assert created.status_code == 200, created.text
    workflow_id = created.json()["workflow_id"]
    started = await client.post(
        f"/api/v1/workflows/{workflow_id}/instances",
        headers={**_headers(org), "Idempotency-Key": f"p185-{uuid4().hex}"},
        json={"payload": {"message": "hola"}},
    )
    assert started.status_code == 200, started.text
    return workflow_id, started.json()["instance_id"]


@pytest.mark.asyncio
async def test_timeline_projection_is_paginated_and_redacted(
    async_client: AsyncClient,
) -> None:
    org = await _org(async_client, "P18.5 timeline cursor")
    workflow_id, instance_id = await _instance(async_client, org)

    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO workflow_run_events "
                "(run_id, organization_id, instance_id, seq, kind, node_id, payload) "
                "SELECT r.id, r.organization_id, r.instance_id, "
                "       (SELECT COALESCE(MAX(seq), 0) FROM workflow_run_events) + n, "
                "       'synthetic_event', 'n1', "
                "       jsonb_build_object('status','ok','token','secreto',"
                "                          'summary', repeat('x', 2500)) "
                "FROM workflow_runs r CROSS JOIN generate_series(1, 5) AS n "
                "WHERE r.id = (SELECT id FROM workflow_runs WHERE instance_id = :iid "
                "              ORDER BY started_at LIMIT 1)"
            ),
            {"iid": instance_id},
        )
        await session.commit()
    finally:
        await session.close()

    first = await async_client.get(
        f"/api/v1/workflows/instances/{instance_id}/timeline?limit=2",
        headers=_headers(org),
    )
    assert first.status_code == 200, first.text
    body = first.json()
    projection = body["execution_timeline"]
    assert projection["schema"] == "execution_timeline/v1"
    assert projection["has_more"] is True
    assert projection["next_cursor"]
    assert len(projection["items"]) >= 1
    assert any(item["kind"] == "run" for item in projection["items"])

    full = await async_client.get(
        f"/api/v1/workflows/instances/{instance_id}/timeline?limit=500",
        headers=_headers(org),
    )
    assert full.status_code == 200, full.text
    synthetic = next(
        item for item in full.json()["events"] if item["kind"] == "synthetic_event"
    )
    assert synthetic["payload"]["token"] == "[redacted]"
    assert len(synthetic["payload"]["summary"]) <= 2001
    assert full.json()["execution_timeline"]["has_more"] is False

    cursor = projection["next_cursor"]
    second = await async_client.get(
        f"/api/v1/workflows/instances/{instance_id}/timeline?limit=2&cursor={cursor}",
        headers=_headers(org),
    )
    assert second.status_code == 200, second.text
    second_body = second.json()
    first_ids = {item["id"] for item in body["events"]}
    second_ids = {item["id"] for item in second_body["events"]}
    assert not (first_ids & second_ids)
    assert second_body["execution_timeline"]["has_more"] in (True, False)

    invalid = await async_client.get(
        f"/api/v1/workflows/instances/{instance_id}/timeline?cursor=no-es-cursor",
        headers=_headers(org),
    )
    assert invalid.status_code == 400, invalid.text
    error_body = invalid.json()
    error_detail = error_body.get("detail", error_body)
    assert error_detail["error_code"] == "timeline_cursor_invalid"


@pytest.mark.asyncio
async def test_timeline_from_other_workspace_is_hidden(async_client: AsyncClient) -> None:
    org = await _org(async_client, "P18.5 timeline ws")
    _, instance_id = await _instance(async_client, org)
    created = await async_client.post(
        "/api/v1/workspaces", headers=_headers(org), json={"name": "Timeline B"}
    )
    assert created.status_code == 201, created.text
    ws_b = created.json()
    denied = await async_client.get(
        f"/api/v1/workflows/instances/{instance_id}/timeline",
        headers={**_headers(org), "X-Workspace-Id": ws_b["id"]},
    )
    assert denied.status_code == 404, denied.text
