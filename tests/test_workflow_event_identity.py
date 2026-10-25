from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from src.infrastructure.postgres.session import get_async_session
from tests.test_workflow_graph import _edge, _graph, _node
from tests.test_workflows import _create_org, _headers, _owner_session


def _wait_node(nid: str) -> dict:
    node = _node(nid, "wait_event", {"preset": "message"})
    node["output_ports"] = [
        {"name": "out", "type": "json"},
        {"name": "timeout", "type": "json"},
    ]
    return node


def _durable_graph() -> dict:
    return _graph(
        nodes=[
            _node("t", "trigger_webhook"),
            _wait_node("w1"),
            _node("end", "end"),
        ],
        edges=[_edge("e1", "t", "w1"), _edge("e2", "w1", "end")],
        entrypoints=["t"],
    )


async def _org(client: AsyncClient, name: str) -> dict:
    org = await _create_org(client, name)
    org["session"] = await _owner_session(client, org["organization_id"])
    return org


async def _published_workflow(client: AsyncClient, org: dict) -> tuple[str, str]:
    created = await client.post(
        "/api/v1/workflows",
        headers={**_headers(org), "Idempotency-Key": f"p13-{uuid4().hex}"},
        json={
            "name": "P13 ingress",
            "trigger_type": "webhook",
            "graph": _durable_graph(),
            "workflow_version": 2,
        },
    )
    assert created.status_code == 200, created.text
    body = created.json()
    workflow_id = body["workflow_id"]
    certified = await client.post(
        f"/api/v1/workflows/{workflow_id}/certifications",
        headers={**_headers(org), "Idempotency-Key": f"cert-{uuid4().hex}"},
        json={"level": "design"},
    )
    assert certified.status_code == 200, certified.text
    published = await client.post(
        f"/api/v1/workflows/{workflow_id}/publish",
        headers={**_headers(org), "Idempotency-Key": f"pub-{uuid4().hex}"},
        json={},
    )
    assert published.status_code == 200, published.text
    return workflow_id, body["hook_secret"]


async def _instance_count(workflow_id: str) -> int:
    session = await get_async_session()
    try:
        value = (
            await session.execute(
                text("SELECT COUNT(*) FROM workflow_instances WHERE workflow_id = :wid"),
                {"wid": UUID(workflow_id)},
            )
        ).scalar()
    finally:
        await session.close()
    return int(value or 0)


@pytest.mark.asyncio
async def test_two_legit_identical_payloads_create_two_operations(
    async_client: AsyncClient,
) -> None:
    org = await _org(async_client, "P13 Identity Identical")
    workflow_id, secret = await _published_workflow(async_client, org)

    for _ in range(2):
        response = await async_client.post(
            f"/api/v1/public/workflows/{workflow_id}/hook",
            headers={"X-Zent-Workflow-Secret": secret},
            json={"message": "same"},
        )
        assert response.status_code == 200, response.text

    assert await _instance_count(workflow_id) == 2


@pytest.mark.asyncio
async def test_same_provider_event_id_creates_one(async_client: AsyncClient) -> None:
    org = await _org(async_client, "P13 Identity Provider")
    workflow_id, secret = await _published_workflow(async_client, org)

    first = await async_client.post(
        f"/api/v1/public/workflows/{workflow_id}/hook",
        headers={
            "X-Zent-Workflow-Secret": secret,
            "X-Zent-Event-Id": "provider-evt-1",
        },
        json={"message": "same"},
    )
    assert first.status_code == 200, first.text

    second = await async_client.post(
        f"/api/v1/public/workflows/{workflow_id}/hook",
        headers={
            "X-Zent-Workflow-Secret": secret,
            "X-Zent-Event-Id": "provider-evt-1",
        },
        json={"message": "same"},
    )
    assert second.status_code == 200, second.text
    assert second.json()["duplicate"] is True
    assert second.json()["instance_id"] == first.json()["instance_id"]
    assert await _instance_count(workflow_id) == 1


@pytest.mark.asyncio
async def test_same_key_different_payload_conflicts(async_client: AsyncClient) -> None:
    org = await _org(async_client, "P13 Identity Conflict")
    workflow_id, secret = await _published_workflow(async_client, org)

    first = await async_client.post(
        f"/api/v1/public/workflows/{workflow_id}/hook",
        headers={
            "X-Zent-Workflow-Secret": secret,
            "X-Zent-Event-Id": "evt-conflict-1",
        },
        json={"message": "one"},
    )
    assert first.status_code == 200, first.text

    second = await async_client.post(
        f"/api/v1/public/workflows/{workflow_id}/hook",
        headers={
            "X-Zent-Workflow-Secret": secret,
            "X-Zent-Event-Id": "evt-conflict-1",
        },
        json={"message": "two"},
    )
    assert second.status_code == 409, second.text
    assert "idempotency_conflict" in second.text
    assert await _instance_count(workflow_id) == 1


@pytest.mark.asyncio
async def test_hundred_concurrent_same_key_one_instance(
    async_client: AsyncClient,
) -> None:
    from src.platform.workflows.ingress import route_ingress

    org = await _org(async_client, "P13 Identity Concurrent")
    workflow_id, _ = await _published_workflow(async_client, org)
    detail = await async_client.get(
        f"/api/v1/workflows/{workflow_id}", headers=_headers(org)
    )
    workspace_id = detail.json()["workspace_id"]
    semaphore = asyncio.Semaphore(20)

    async def send():
        async with semaphore:
            return await route_ingress(
                workflow_id=UUID(workflow_id),
                organization_id=UUID(org["organization_id"]),
                workspace_id=UUID(workspace_id) if workspace_id else None,
                trigger="webhook",
                payload={"message": "same"},
                idempotency_key="concurrent-key",
                provider_event_id="concurrent-evt",
                source="webhook",
                system_context=True,
                require_active=True,
            )

    results = await asyncio.gather(*(send() for _ in range(100)))
    assert all(result.get("error") is None for result in results), results[:3]
    assert await _instance_count(workflow_id) == 1


@pytest.mark.asyncio
async def test_schedule_occurrence_identity(async_client: AsyncClient) -> None:
    from src.platform.workflows.ingress import route_ingress

    org = await _org(async_client, "P13 Schedule Identity")
    workflow_id, _ = await _published_workflow(async_client, org)
    detail = await async_client.get(
        f"/api/v1/workflows/{workflow_id}", headers=_headers(org)
    )
    workspace_id = detail.json()["workspace_id"]

    async def send(occurrence: str):
        return await route_ingress(
            workflow_id=UUID(workflow_id),
            organization_id=UUID(org["organization_id"]),
            workspace_id=UUID(workspace_id) if workspace_id else None,
            trigger="schedule",
            payload={"occurrence_at": occurrence},
            idempotency_key=f"sched:{workflow_id}:{occurrence}",
            actor_type="scheduler",
            system_context=True,
            require_active=True,
        )

    first = await send("2026-10-25T10:00:00+00:00")
    same = await send("2026-10-25T10:00:00+00:00")
    different = await send("2026-10-25T10:05:00+00:00")
    assert first.get("instance_id")
    assert same.get("duplicate") is True
    assert different.get("instance_id")
    assert await _instance_count(workflow_id) == 2


@pytest.mark.asyncio
async def test_outbox_persists_and_drains(monkeypatch) -> None:
    from src.platform.workflows import outbox

    delivered: list[tuple[str, dict]] = []

    async def fake_publish(event_type: str, payload: dict) -> None:
        delivered.append((event_type, payload))

    monkeypatch.setattr(
        "src.platform.realtime.stream.publish_event", fake_publish
    )

    org_id = uuid4()
    session = await get_async_session()
    try:
        eid = await outbox.enqueue(
            session,
            organization_id=org_id,
            workspace_id=None,
            aggregate_type="test",
            aggregate_key="p13",
            event_type="p13.outbox.test",
            payload={"hello": "world"},
        )
        await session.commit()
    finally:
        await session.close()

    result = await outbox.dispatch_pending(limit=10)
    assert result["delivered"] >= 1
    assert any(payload.get("event_id") == str(eid) for _, payload in delivered)

    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT delivered_at FROM workflow_outbox WHERE event_id = :eid"
                ),
                {"eid": eid},
            )
        ).fetchone()
    finally:
        await session.close()
    assert row is not None and row.delivered_at is not None
