from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from src.infrastructure.postgres.session import get_async_session
from tests.test_workflow_graph import _edge, _graph, _node
from tests.test_workflows import _create_org, _headers, _owner_session


def _marker_graph(value: str, metadata: dict | None = None) -> dict:
    graph = _graph(
        nodes=[
            _node("t", "trigger_webhook"),
            _node("m", "set_variable", {"name": "marker", "value": value}),
            _node("end", "end"),
        ],
        edges=[_edge("e1", "t", "m"), _edge("e2", "m", "end")],
        entrypoints=["t"],
    )
    if metadata is not None:
        graph["metadata"] = metadata
    return graph


async def _org(client: AsyncClient, name: str) -> dict:
    org = await _create_org(client, name)
    org["session"] = await _owner_session(client, org["organization_id"])
    return org


async def _create(
    client: AsyncClient,
    org: dict,
    graph: dict | None = None,
    *,
    trigger_type: str = "webhook",
    trigger_config: dict | None = None,
) -> tuple[str, str | None]:
    response = await client.post(
        "/api/v1/workflows",
        headers={**_headers(org), "Idempotency-Key": f"p13-{uuid4().hex}"},
        json={
            "name": "P13 published",
            "trigger_type": trigger_type,
            "trigger_config": trigger_config or {},
            "graph": graph or _marker_graph("A"),
            "workflow_version": 2,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    return body["workflow_id"], body.get("hook_secret")


async def _certify(client: AsyncClient, org: dict, workflow_id: str) -> dict:
    response = await client.post(
        f"/api/v1/workflows/{workflow_id}/certifications",
        headers={**_headers(org), "Idempotency-Key": f"cert-{uuid4().hex}"},
        json={"level": "design"},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _publish(client: AsyncClient, org: dict, workflow_id: str) -> dict:
    response = await client.post(
        f"/api/v1/workflows/{workflow_id}/publish",
        headers={**_headers(org), "Idempotency-Key": f"pub-{uuid4().hex}"},
        json={},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _marker_value(client: AsyncClient, org: dict, run_id: str) -> str | None:
    response = await client.get(
        f"/api/v1/workflows/runs/{run_id}", headers=_headers(org)
    )
    assert response.status_code == 200, response.text
    steps = response.json()["steps"]
    marker = next((s for s in steps if s.get("node_id") == "m"), None)
    assert marker is not None, steps
    return (marker.get("output") or {}).get("value")


async def _hook(client: AsyncClient, workflow_id: str, secret: str | None) -> str:
    assert secret
    response = await client.post(
        f"/api/v1/public/workflows/{workflow_id}/hook",
        headers={"X-Zent-Workflow-Secret": secret},
        json={"message": "same"},
    )
    assert response.status_code == 200, response.text
    run_id = response.json().get("run_id")
    assert run_id, response.text
    return str(run_id)


@pytest.mark.asyncio
async def test_edit_active_workflow_keeps_published_execution(
    async_client: AsyncClient,
) -> None:
    org = await _org(async_client, "P13 Published Edit")
    workflow_id, secret = await _create(async_client, org)
    await _certify(async_client, org, workflow_id)
    await _publish(async_client, org, workflow_id)

    patched = await async_client.patch(
        f"/api/v1/workflows/{workflow_id}",
        headers={**_headers(org), "Idempotency-Key": f"patch-{uuid4().hex}"},
        json={"graph": _marker_graph("B"), "workflow_version": 2},
    )
    assert patched.status_code == 200, patched.text

    run_id = await _hook(async_client, workflow_id, secret)
    assert await _marker_value(async_client, org, run_id) == "A"


@pytest.mark.asyncio
async def test_schedule_uses_published_snapshot(async_client: AsyncClient) -> None:
    from src.platform.workflows.engine import run_due_scheduled_workflows

    org = await _org(async_client, "P13 Published Schedule")
    workflow_id, _ = await _create(
        async_client,
        org,
        trigger_type="schedule",
        trigger_config={"every_minutes": 5},
    )
    await _certify(async_client, org, workflow_id)
    await _publish(async_client, org, workflow_id)

    patched = await async_client.patch(
        f"/api/v1/workflows/{workflow_id}",
        headers={**_headers(org), "Idempotency-Key": f"patch-{uuid4().hex}"},
        json={"graph": _marker_graph("B"), "workflow_version": 2},
    )
    assert patched.status_code == 200, patched.text

    fired = await run_due_scheduled_workflows(
        now=datetime.now(timezone.utc),
        organization_id=UUID(org["organization_id"]),
    )
    assert fired >= 1

    session = await get_async_session()
    try:
        run = (
            await session.execute(
                text(
                    "SELECT id FROM workflow_runs WHERE workflow_id = :wid "
                    "ORDER BY started_at DESC LIMIT 1"
                ),
                {"wid": UUID(workflow_id)},
            )
        ).fetchone()
    finally:
        await session.close()
    assert run is not None
    assert await _marker_value(async_client, org, str(run.id)) == "A"


@pytest.mark.asyncio
async def test_patch_rejects_stale_revision(async_client: AsyncClient) -> None:
    org = await _org(async_client, "P13 Revision")
    workflow_id, _ = await _create(async_client, org)
    detail = await async_client.get(
        f"/api/v1/workflows/{workflow_id}", headers=_headers(org)
    )
    revision = int(detail.json()["draft_revision"])

    first = await async_client.patch(
        f"/api/v1/workflows/{workflow_id}",
        headers={**_headers(org), "Idempotency-Key": f"patch-{uuid4().hex}"},
        json={"name": "P13 v2", "expected_revision": revision},
    )
    assert first.status_code == 200, first.text
    assert int(first.json()["draft_revision"]) == revision + 1

    stale = await async_client.patch(
        f"/api/v1/workflows/{workflow_id}",
        headers={
            **_headers(org),
            "Idempotency-Key": f"patch-{uuid4().hex}",
            "If-Match": f'"rev-{revision}"',
        },
        json={"name": "P13 stale"},
    )
    assert stale.status_code == 409, stale.text
    assert "workflow_revision_conflict" in stale.text


@pytest.mark.asyncio
async def test_concurrent_patches_are_monotonic(async_client: AsyncClient) -> None:
    org = await _org(async_client, "P13 Concurrent Patch")
    workflow_id, _ = await _create(async_client, org)
    detail = await async_client.get(
        f"/api/v1/workflows/{workflow_id}", headers=_headers(org)
    )
    published_hash = detail.json()["published_graph_hash"]

    async def patch_once(index: int):
        return await async_client.patch(
            f"/api/v1/workflows/{workflow_id}",
            headers={
                **_headers(org),
                "Idempotency-Key": f"patch-{uuid4().hex}",
            },
            json={"name": f"P13 patch {index}"},
        )

    responses = await asyncio.gather(*(patch_once(i) for i in range(50)))
    assert all(response.status_code == 200 for response in responses)

    after = await async_client.get(
        f"/api/v1/workflows/{workflow_id}", headers=_headers(org)
    )
    assert int(after.json()["draft_revision"]) == 50
    assert after.json()["published_graph_hash"] == published_hash


@pytest.mark.asyncio
async def test_concurrent_publishes_keep_single_production(
    async_client: AsyncClient,
) -> None:
    org = await _org(async_client, "P13 Concurrent Publish")
    workflow_id, _ = await _create(async_client, org)
    await _certify(async_client, org, workflow_id)

    async def publish_once():
        return await async_client.post(
            f"/api/v1/workflows/{workflow_id}/publish",
            headers={**_headers(org), "Idempotency-Key": f"pub-{uuid4().hex}"},
            json={},
        )

    responses = await asyncio.gather(*(publish_once() for _ in range(10)))
    assert all(response.status_code == 200 for response in responses), [
        response.text for response in responses if response.status_code != 200
    ]

    versions = await async_client.get(
        f"/api/v1/workflows/{workflow_id}/versions", headers=_headers(org)
    )
    production = [
        item for item in versions.json()["versions"] if item["status"] == "production"
    ]
    assert len(production) == 1
    detail = await async_client.get(
        f"/api/v1/workflows/{workflow_id}", headers=_headers(org)
    )
    assert detail.json()["published_version_id"] == production[0]["id"]


@pytest.mark.asyncio
async def test_restore_active_version_is_atomic_and_certified(
    async_client: AsyncClient,
) -> None:
    org = await _org(async_client, "P13 Restore")
    workflow_id, secret = await _create(async_client, org)
    await _certify(async_client, org, workflow_id)
    first = await _publish(async_client, org, workflow_id)
    first_version_id = first["published_version_id"]

    patched = await async_client.patch(
        f"/api/v1/workflows/{workflow_id}",
        headers={**_headers(org), "Idempotency-Key": f"patch-{uuid4().hex}"},
        json={"graph": _marker_graph("B"), "workflow_version": 2},
    )
    assert patched.status_code == 200, patched.text
    await _certify(async_client, org, workflow_id)
    await _publish(async_client, org, workflow_id)

    restored = await async_client.post(
        f"/api/v1/workflows/{workflow_id}/versions/{first_version_id}/restore",
        headers={**_headers(org), "Idempotency-Key": f"restore-{uuid4().hex}"},
    )
    assert restored.status_code == 200, restored.text

    detail = await async_client.get(
        f"/api/v1/workflows/{workflow_id}", headers=_headers(org)
    )
    assert detail.json()["published_version_id"] == first_version_id
    assert detail.json()["draft_changed"] is False
    versions = await async_client.get(
        f"/api/v1/workflows/{workflow_id}/versions", headers=_headers(org)
    )
    production = [
        item for item in versions.json()["versions"] if item["status"] == "production"
    ]
    assert len(production) == 1
    assert production[0]["id"] == first_version_id

    run_id = await _hook(async_client, workflow_id, secret)
    assert await _marker_value(async_client, org, run_id) == "A"


@pytest.mark.asyncio
async def test_trigger_change_invalidates_certificate_for_publish(
    async_client: AsyncClient,
) -> None:
    org = await _org(async_client, "P13 Trigger Stale")
    workflow_id, _ = await _create(
        async_client, org, trigger_config={"source": "crm"}
    )
    await _certify(async_client, org, workflow_id)
    patched = await async_client.patch(
        f"/api/v1/workflows/{workflow_id}",
        headers={**_headers(org), "Idempotency-Key": f"patch-{uuid4().hex}"},
        json={"trigger_config": {"source": "erp"}},
    )
    assert patched.status_code == 200, patched.text

    denied = await async_client.post(
        f"/api/v1/workflows/{workflow_id}/publish",
        headers={**_headers(org), "Idempotency-Key": f"pub-{uuid4().hex}"},
        json={},
    )
    assert denied.status_code == 409, denied.text
    assert "trigger_stale" in denied.text


@pytest.mark.asyncio
async def test_binding_change_invalidates_certificate_for_publish(
    async_client: AsyncClient,
) -> None:
    org = await _org(async_client, "P13 Binding Stale")
    workflow_id, _ = await _create(async_client, org)
    certificate = await _certify(async_client, org, workflow_id)
    detail = await async_client.get(
        f"/api/v1/workflows/{workflow_id}", headers=_headers(org)
    )
    workspace_id = detail.json()["workspace_id"]

    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO workflow_capability_bindings "
                "(organization_id, workspace_id, capability_ref, provider_kind, "
                "config, status) VALUES (:oid, :ws, :ref, 'rest_api', '{}'::jsonb, 'active')"
            ),
            {
                "oid": UUID(org["organization_id"]),
                "ws": UUID(workspace_id) if workspace_id else None,
                "ref": f"p13.binding.{uuid4().hex[:8]}",
            },
        )
        await session.commit()
    finally:
        await session.close()

    denied = await async_client.post(
        f"/api/v1/workflows/{workflow_id}/publish",
        headers={**_headers(org), "Idempotency-Key": f"pub-{uuid4().hex}"},
        json={},
    )
    assert denied.status_code == 409, denied.text
    assert "bindings_stale" in denied.text
    assert certificate["binding_fingerprint"]


@pytest.mark.asyncio
async def test_org_level_certificate_is_visible_from_workspace_context(
    async_client: AsyncClient,
) -> None:
    from src.platform.workflows.release_policy import (
        evaluate_release,
        issue_certificate,
        list_certificates,
    )

    org = await _org(async_client, "P13 Org Certificate")
    workflow_id, _ = await _create(async_client, org)
    session = await get_async_session()
    try:
        await session.execute(
            text("UPDATE workflows SET workspace_id = NULL WHERE id = :wid"),
            {"wid": UUID(workflow_id)},
        )
        await session.commit()
    finally:
        await session.close()
    listing = await async_client.get("/api/v1/workspaces", headers=_headers(org))
    workspace_id = listing.json()["workspaces"][0]["id"]
    certificate = await issue_certificate(
        UUID(org["organization_id"]),
        UUID(workflow_id),
        level="design",
        workspace_id=None,
    )
    assert certificate["workspace_id"] is None
    decision = await evaluate_release(
        UUID(org["organization_id"]),
        UUID(workflow_id),
        action="publish",
        workspace_id=UUID(workspace_id),
    )
    assert decision.allowed is True, decision.to_dict()
    listed = await list_certificates(
        UUID(org["organization_id"]),
        UUID(workflow_id),
        workspace_id=UUID(workspace_id),
    )
    assert any(item["id"] == certificate["id"] for item in listed["certificates"])


@pytest.mark.asyncio
async def test_legacy_metadata_cannot_self_assign(async_client: AsyncClient) -> None:
    org = await _org(async_client, "P13 Legacy Metadata")
    workflow_id, _ = await _create(
        async_client,
        org,
        _marker_graph(
            "A",
            {"release_policy": "legacy", "legacy": True, "require_certification": False},
        ),
    )
    denied = await async_client.post(
        f"/api/v1/workflows/{workflow_id}/publish",
        headers={**_headers(org), "Idempotency-Key": f"pub-{uuid4().hex}"},
        json={},
    )
    assert denied.status_code == 409, denied.text

    session = await get_async_session()
    try:
        policy = (
            await session.execute(
                text(
                    "SELECT release_policy, published_version_id FROM workflows "
                    "WHERE id = :wid"
                ),
                {"wid": UUID(workflow_id)},
            )
        ).fetchone()
    finally:
        await session.close()
    assert policy.release_policy == "standard"
    assert policy.published_version_id is None
