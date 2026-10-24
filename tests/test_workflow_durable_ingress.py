# =============================================================================
# P02 — ingress durable: manual/schedule/webhook/event, inbox idempotente.
# =============================================================================
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from tests.test_workflow_durable_instances import _durable_graph
from tests.test_workflows import _create_org, _headers, _owner_session


async def _org(client: AsyncClient, name: str) -> dict:
    org = await _create_org(client, name)
    org["session"] = await _owner_session(client, org["organization_id"])
    return org


async def _create(
    client: AsyncClient,
    org: dict,
    *,
    name: str,
    trigger_type: str = "webhook",
    trigger_config: dict | None = None,
    graph: dict | None = None,
) -> str:
    body: dict = {
        "name": name,
        "trigger_type": trigger_type,
        "graph": graph or _durable_graph(),
        "workflow_version": 2,
    }
    if trigger_config is not None:
        body["trigger_config"] = trigger_config
    created = await client.post(
        "/api/v1/workflows",
        headers={**_headers(org), "Idempotency-Key": f"p02-{uuid4().hex}"},
        json=body,
    )
    assert created.status_code == 200, created.text
    return created.json()["workflow_id"]


async def _certify(client: AsyncClient, org: dict, wid: str) -> None:
    response = await client.post(
        f"/api/v1/workflows/{wid}/certifications",
        headers={**_headers(org), "Idempotency-Key": f"cert-{uuid4().hex}"},
        json={"level": "design"},
    )
    assert response.status_code == 200, response.text


async def _activate(client: AsyncClient, org: dict, wid: str) -> None:
    await _certify(client, org, wid)
    response = await client.post(
        f"/api/v1/workflows/{wid}/activate", headers=_headers(org)
    )
    assert response.status_code == 200, response.text


async def _publish(client: AsyncClient, org: dict, wid: str) -> None:
    await _certify(client, org, wid)
    response = await client.post(
        f"/api/v1/workflows/{wid}/publish",
        headers={**_headers(org), "Idempotency-Key": f"pub-{uuid4().hex}"},
        json={},
    )
    assert response.status_code == 200, response.text


async def _secret(client: AsyncClient, org: dict, wid: str) -> str:
    response = await client.post(
        f"/api/v1/workflows/{wid}/hook-secret/rotate",
        headers={**_headers(org), "Idempotency-Key": f"sec-{uuid4().hex}"},
    )
    assert response.status_code == 200, response.text
    return response.json()["hook_secret"]


async def _instance_count(org: dict, wid: str) -> int:
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT count(*) AS n FROM workflow_instances "
                    "WHERE organization_id = :oid AND workflow_id = :wid"
                ),
                {"oid": UUID(org["organization_id"]), "wid": UUID(wid)},
            )
        ).fetchone()
    finally:
        await session.close()
    return int(row.n or 0)


@pytest.mark.asyncio
async def test_manual_run_of_wait_graph_starts_durable_instance(
    async_client: AsyncClient,
) -> None:
    org = await _org(async_client, "P02 Manual Durable")
    wid = await _create(async_client, org, name="Manual WAIT")

    response = await async_client.post(
        f"/api/v1/workflows/{wid}/run",
        headers=_headers(org),
        json={"payload": {"message": "hola"}},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body.get("instance_id"), body
    assert body.get("durable") is True
    assert await _instance_count(org, wid) == 1
    detail = await async_client.get(
        f"/api/v1/workflows/instances/{body['instance_id']}", headers=_headers(org)
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["status"] == "WAITING"


@pytest.mark.asyncio
async def test_schedule_due_starts_durable_instance_and_is_idempotent(
    async_client: AsyncClient,
) -> None:
    org = await _org(async_client, "P02 Schedule Durable")
    wid = await _create(
        async_client,
        org,
        name="Schedule WAIT",
        trigger_type="schedule",
        trigger_config={"every_minutes": 1},
    )
    await _activate(async_client, org, wid)

    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session
    from src.platform.workflows.engine import run_due_scheduled_workflows

    now = datetime.now(timezone.utc)
    session = await get_async_session()
    try:
        await session.execute(
            text("UPDATE workflows SET last_run_at = :ts WHERE id = :wid"),
            {"ts": now - timedelta(hours=2), "wid": UUID(wid)},
        )
        await session.commit()
    finally:
        await session.close()

    await run_due_scheduled_workflows(organization_id=UUID(org["organization_id"]), now=now)
    assert await _instance_count(org, wid) == 1

    # Mismo epoch: el ingress key evita una segunda instancia.
    session = await get_async_session()
    try:
        await session.execute(
            text("UPDATE workflows SET last_run_at = :ts WHERE id = :wid"),
            {"ts": now - timedelta(hours=2), "wid": UUID(wid)},
        )
        await session.commit()
    finally:
        await session.close()
    await run_due_scheduled_workflows(organization_id=UUID(org["organization_id"]), now=now)
    assert await _instance_count(org, wid) == 1


@pytest.mark.asyncio
async def test_public_hook_duplicate_creates_one_instance(
    async_client: AsyncClient,
) -> None:
    org = await _org(async_client, "P02 Hook Duplicate")
    wid = await _create(async_client, org, name="Hook WAIT")
    await _publish(async_client, org, wid)
    secret = await _secret(async_client, org, wid)

    first = await async_client.post(
        f"/api/v1/public/workflows/{wid}/hook",
        headers={"X-Zent-Workflow-Secret": secret, "X-Zent-Event-Id": "evt-1"},
        json={"message": "hola"},
    )
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert first_body.get("instance_id"), first_body

    second = await async_client.post(
        f"/api/v1/public/workflows/{wid}/hook",
        headers={"X-Zent-Workflow-Secret": secret, "X-Zent-Event-Id": "evt-1"},
        json={"message": "hola"},
    )
    assert second.status_code == 200, second.text
    second_body = second.json()
    assert second_body.get("duplicate") is True
    assert second_body.get("instance_id") == first_body["instance_id"]
    assert await _instance_count(org, wid) == 1


@pytest.mark.asyncio
async def test_event_trigger_duplicate_starts_one_durable_instance(
    async_client: AsyncClient,
) -> None:
    org = await _org(async_client, "P02 Event Duplicate")
    wid = await _create(
        async_client, org, name="Event WAIT", trigger_type="event"
    )
    await _activate(async_client, org, wid)
    trigger = await async_client.post(
        "/api/v1/workflows/triggers",
        headers={**_headers(org), "Idempotency-Key": f"trg-{uuid4().hex}"},
        json={"workflow_id": wid, "event_type": "invoice.detected"},
    )
    assert trigger.status_code == 200, trigger.text

    from src.platform.workflows.events import dispatch_event_to_workflows

    base = {
        "organization_id": org["organization_id"],
        "event_id": "evt-42",
        "amount": 10,
    }
    fired = await dispatch_event_to_workflows(
        "invoice.detected", {**base, "ts": "2026-10-23T10:00:00Z"}
    )
    assert fired == 1
    assert await _instance_count(org, wid) == 1

    fired_2 = await dispatch_event_to_workflows(
        "invoice.detected", {**base, "ts": "2026-10-23T10:00:01Z"}
    )
    assert fired_2 in (0, 1)
    assert await _instance_count(org, wid) == 1


@pytest.mark.asyncio
async def test_event_trigger_on_draft_does_not_execute(
    async_client: AsyncClient,
) -> None:
    org = await _org(async_client, "P02 Event Draft")
    created = await async_client.post(
        "/api/v1/workflows",
        headers={**_headers(org), "Idempotency-Key": f"p02-{uuid4().hex}"},
        json={
            "name": "Borrador en evento",
            "trigger_type": "event",
            "steps": [
                {
                    "type": "notify",
                    "config": {"channel": "in_app", "title": "x", "message": "x"},
                }
            ],
        },
    )
    assert created.status_code == 200, created.text
    wid = created.json()["workflow_id"]
    trigger = await async_client.post(
        "/api/v1/workflows/triggers",
        headers={**_headers(org), "Idempotency-Key": f"trg-{uuid4().hex}"},
        json={"workflow_id": wid, "event_type": "invoice.detected"},
    )
    assert trigger.status_code == 200, trigger.text

    from src.platform.workflows.events import dispatch_event_to_workflows

    fired = await dispatch_event_to_workflows(
        "invoice.detected",
        {"organization_id": org["organization_id"], "event_id": "draft-1"},
    )
    assert fired == 0


@pytest.mark.asyncio
async def test_pending_ingress_event_is_claimed_on_retry(
    async_client: AsyncClient,
) -> None:
    """Crash entre registrar y claim: el reintento debe reclamar y ejecutar."""
    org = await _org(async_client, "P02 Ingress Retry")
    wid = await _create(async_client, org, name="Retry WAIT")

    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session
    from src.platform.workflows.ingress import route_ingress

    key = f"retry-{uuid4().hex}"
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO workflow_ingress_events "
                "(organization_id, workspace_id, workflow_id, trigger_type, ingress_key, "
                "payload, status) VALUES (:oid, NULL, :wid, 'webhook', :key, '{}'::jsonb, 'pending')"
            ),
            {
                "oid": UUID(org["organization_id"]),
                "wid": UUID(wid),
                "key": key,
            },
        )
        await session.commit()
    finally:
        await session.close()

    detail = await async_client.get(f"/api/v1/workflows/{wid}", headers=_headers(org))
    workspace_id = detail.json().get("workspace_id")
    result = await route_ingress(
        workflow_id=UUID(wid),
        organization_id=UUID(org["organization_id"]),
        trigger="webhook",
        payload={"message": "retry"},
        workspace_id=UUID(workspace_id) if workspace_id else None,
        idempotency_key=key,
        require_active=False,
    )
    assert result.get("instance_id"), result
    assert await _instance_count(org, wid) == 1


@pytest.mark.asyncio
async def test_stale_ingress_claim_is_requeued(async_client: AsyncClient) -> None:
    org = await _org(async_client, "P02 Ingress Sweep")
    wid = await _create(async_client, org, name="Sweep WAIT")

    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session
    from src.platform.workflows.ingress import sweep_ingress_events

    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO workflow_ingress_events "
                "(organization_id, workflow_id, trigger_type, ingress_key, payload, "
                "status, claimed_at) VALUES (:oid, :wid, 'webhook', :key, '{}'::jsonb, "
                "'processing', NOW() - INTERVAL '10 minutes')"
            ),
            {
                "oid": UUID(org["organization_id"]),
                "wid": UUID(wid),
                "key": f"orphan-{uuid4().hex}",
            },
        )
        await session.commit()
    finally:
        await session.close()

    stats = await sweep_ingress_events(stale_minutes=1)
    assert stats["requeued"] >= 1
