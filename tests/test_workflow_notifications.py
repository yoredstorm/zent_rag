# =============================================================================
# Notification / Schedule Builder (commit 4) — canales y destinatarios reales,
# envío por correo a personas/equipos y errores humanos para canales no
# conectados.
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from tests.test_workflow_graph import _edge, _graph, _node
from tests.test_workflows import _create_org, _headers, _owner_session


async def _org(client: AsyncClient, name: str) -> dict:
    org = await _create_org(client, name)
    org["session"] = await _owner_session(client, org["organization_id"])
    from sqlalchemy import text

    from src.infrastructure.postgres.relational_db import PostgresUserRepository
    from src.infrastructure.postgres.session import get_async_session

    user = await PostgresUserRepository().get_by_external_id(
        UUID(org["organization_id"]), "default-admin"
    )
    assert user is not None
    # El admin de prueba no trae email; el builder solo ofrece personas con
    # correo real, así que el test se lo asigna (nada se simula en producción).
    email = f"owner-{uuid4().hex[:8]}@example.com"
    session = await get_async_session()
    try:
        await session.execute(
            text("UPDATE users SET email = :email WHERE id = :id"),
            {"email": email, "id": user.id},
        )
        await session.commit()
    finally:
        await session.close()
    org["user_id"] = str(user.id)
    org["user_email"] = email
    return org


@pytest.mark.asyncio
async def test_notification_targets_lists_real_people_and_channels(async_client: AsyncClient) -> None:
    org = await _org(async_client, "Notify Targets")
    h = _headers(org)

    resp = await async_client.get("/api/v1/workflows/notification-targets", headers=h)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    channels = {c["value"]: c for c in body["channels"]}
    assert channels["in_app"]["available"] is True
    assert "email" in channels and "webhook" in channels
    assert "slack" in channels and channels["slack"]["available"] is False
    assert "Conectar" in channels["slack"]["detail"] or "conectar" in channels["slack"]["detail"]

    owner_email = org["user_email"]
    assert any(p["email"] == owner_email for p in body["people"])
    assert isinstance(body["teams"], list)


@pytest.mark.asyncio
async def test_notify_email_recipients_in_simulation(async_client: AsyncClient) -> None:
    org = await _org(async_client, "Notify Email")
    h = _headers(org)

    graph = _graph(
        nodes=[
            _node("t", "trigger_webhook"),
            _node(
                "mail",
                "notify",
                {
                    "channel": "email",
                    "title": "Stock bajo",
                    "message": "Producto con stock bajo",
                    "recipients": [
                        {"kind": "email", "value": "compras@zent.pe", "label": "Compras"},
                        {"kind": "person", "value": org["user_id"], "label": "Owner"},
                    ],
                },
            ),
        ],
        edges=[_edge("e1", "t", "mail")],
        entrypoints=["t"],
    )
    created = await async_client.post(
        "/api/v1/workflows",
        headers=h,
        json={"name": "Notify Email WF", "trigger_type": "webhook", "graph": graph, "workflow_version": 2},
    )
    assert created.status_code == 200, created.text
    wid = created.json()["workflow_id"]

    run = await async_client.post(
        f"/api/v1/workflows/{wid}/run",
        headers=h,
        json={"payload": {}, "simulate": True},
    )
    assert run.status_code == 200, run.text
    run_body = run.json()
    assert run_body["status"] == "simulated", run_body

    detail = await async_client.get(f"/api/v1/workflows/runs/{run_body['run_id']}", headers=h)
    assert detail.status_code == 200, detail.text
    steps = detail.json()["steps"]
    mail = next(s for s in steps if s["node_id"] == "mail")
    recipients = mail["output"]["recipients"]
    assert "compras@zent.pe" in recipients
    assert org["user_email"] in recipients


@pytest.mark.asyncio
async def test_notify_unconnected_channel_returns_human_error(async_client: AsyncClient) -> None:
    org = await _org(async_client, "Notify Slack")
    h = _headers(org)

    graph = _graph(
        nodes=[
            _node("t", "trigger_webhook"),
            _node("slack", "notify", {"channel": "slack", "title": "Hola", "message": "m"}),
        ],
        edges=[_edge("e1", "t", "slack")],
        entrypoints=["t"],
    )
    created = await async_client.post(
        "/api/v1/workflows",
        headers=h,
        json={"name": "Notify Slack WF", "trigger_type": "webhook", "graph": graph, "workflow_version": 2},
    )
    assert created.status_code == 200, created.text
    wid = created.json()["workflow_id"]

    run = await async_client.post(
        f"/api/v1/workflows/{wid}/run",
        headers=h,
        json={"payload": {}, "simulate": True},
    )
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["status"] == "failed"
    assert "Slack" in (body.get("error") or "")


@pytest.mark.asyncio
async def test_notify_missing_recipient_emails_is_reported(async_client: AsyncClient) -> None:
    org = await _org(async_client, "Notify Empty Team")
    h = _headers(org)

    graph = _graph(
        nodes=[
            _node("t", "trigger_webhook"),
            _node(
                "mail",
                "notify",
                {
                    "channel": "email",
                    "title": "Aviso",
                    "message": "m",
                    "recipients": [{"kind": "team", "value": "equipo-inexistente"}],
                },
            ),
        ],
        edges=[_edge("e1", "t", "mail")],
        entrypoints=["t"],
    )
    created = await async_client.post(
        "/api/v1/workflows",
        headers=h,
        json={"name": "Notify Empty WF", "trigger_type": "webhook", "graph": graph, "workflow_version": 2},
    )
    assert created.status_code == 200, created.text
    wid = created.json()["workflow_id"]

    run = await async_client.post(
        f"/api/v1/workflows/{wid}/run",
        headers=h,
        json={"payload": {}, "simulate": False},
    )
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["status"] == "failed"
    assert "correos" in (body.get("error") or "").lower()
