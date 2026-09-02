# =============================================================================
# Workflows & Automation (PROMPT 17)
# =============================================================================
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient


async def _create_org(client: AsyncClient, name: str) -> dict:
    resp = await client.post(
        "/api/v1/billing/subscription/create-trial",
        json={
            "company_name": name,
            "email": f"wf-{uuid4().hex[:8]}@example.com",
            "country": "CL",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _owner_session(organization_id: str) -> str:
    from src.infrastructure.postgres.relational_db import PostgresUserRepository
    from src.platform.auth.session import encrypt_session

    user = await PostgresUserRepository().get_by_external_id(
        UUID(organization_id), "default-admin"
    )
    assert user is not None
    return encrypt_session(user.id, UUID(organization_id))


def _headers(org: dict) -> dict:
    return {
        "Authorization": f"Bearer {org['session']}",
        "X-Organization-Id": org["organization_id"],
        "Idempotency-Key": f"wf-{uuid4().hex}",
    }


async def _platform_admin(client: AsyncClient, email: str) -> dict:
    import hashlib as hl

    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session
    from src.platform.auth.passwords import hash_password

    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO users (id, organization_id, external_id, email_hash, "
                "role, email, password_hash, is_platform_admin) "
                "VALUES (gen_random_uuid(), NULL, :ext, :eh, 'platform', :email, :ph, true)"
            ),
            {
                "ext": f"plat-{uuid4().hex[:12]}",
                "eh": hl.sha256(email.encode()).hexdigest(),
                "email": email,
                "ph": hash_password("secret-123"),
            },
        )
        await session.execute(
            text(
                "INSERT INTO user_platform_roles (user_id, role_id) "
                "SELECT u.id, pr.id FROM users u CROSS JOIN platform_roles pr "
                "WHERE lower(u.email) = lower(:email) AND pr.name = 'super_admin' "
                "ON CONFLICT DO NOTHING"
            ),
            {"email": email},
        )
        await session.commit()
    finally:
        await session.close()
    login = await client.post(
        "/api/v1/auth/platform/login", json={"email": email, "password": "secret-123"}
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.mark.asyncio
async def test_workflow_notify_and_approval_flow(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Wf Org")
    org["session"] = await _owner_session(org["organization_id"])
    h = _headers(org)
    plat = await _platform_admin(async_client, f"padmin-wf-{uuid4().hex[:8]}@zent.example")

    # Workflow tenant: notify + approval + notify.
    created = await async_client.post(
        "/api/v1/workflows",
        headers=h,
        json={
            "name": "Release Pipeline",
            "description": "Notifica, espera aprobación, notifica",
            "trigger_type": "manual",
            "steps": [
                {"type": "notify", "params": {"email": "ops@example.com", "message": "Inicio"}},
                {"type": "approval", "params": {"message": "¿Desplegar?"}},
                {"type": "notify", "params": {"email": "ops@example.com", "message": "Fin"}},
            ],
        },
    )
    assert created.status_code == 201, created.text
    workflow_id = created.json()["id"]

    listed = await async_client.get("/api/v1/workflows", headers=h)
    assert listed.status_code == 200, listed.text
    assert listed.json()["workflows"][0]["id"] == workflow_id

    # Trigger → corre en background: notify + queda waiting_approval.
    triggered = await async_client.post(f"/api/v1/workflows/{workflow_id}/trigger", headers=h, json={})
    assert triggered.status_code == 200, triggered.text
    assert triggered.json()["status"] == "started"
    run_id = triggered.json()["run_id"]

    import asyncio

    for _ in range(20):
        await asyncio.sleep(0.5)
        runs = (await async_client.get("/api/v1/workflows/runs", headers=h)).json()["runs"]
        run = next(r for r in runs if r["id"] == run_id)
        if run["status"] == "waiting_approval":
            break

    assert run["status"] == "waiting_approval", run
    steps = (await async_client.get(f"/api/v1/workflows/runs/{run_id}", headers=h)).json()["steps"]
    assert steps[0]["status"] == "completed"
    assert steps[1]["status"] == "waiting_approval"

    # Aprobar → sigue y completa.
    approved = await async_client.post(f"/api/v1/workflows/runs/{run_id}/approve", headers=h, json={})
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"

    for _ in range(20):
        await asyncio.sleep(0.5)
        runs = (await async_client.get("/api/v1/workflows/runs", headers=h)).json()["runs"]
        run = next(r for r in runs if r["id"] == run_id)
        if run["status"] == "completed":
            break
    assert run["status"] == "completed"
    steps2 = (await async_client.get(f"/api/v1/workflows/runs/{run_id}", headers=h)).json()["steps"]
    assert steps2[2]["status"] == "completed"


@pytest.mark.asyncio
async def test_workflow_deploy_and_platform_overview(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Wf Deploy Org")
    org["session"] = await _owner_session(org["organization_id"])
    h = _headers(org)
    plat = await _platform_admin(async_client, f"padmin-wfd-{uuid4().hex[:8]}@zent.example")

    # Agente con versión ready.
    agent = (
        await async_client.post(
            "/api/v1/agents",
            headers={**_headers(org), "Idempotency-Key": f"wf-a-{uuid4().hex}"},
            json={"name": "Wf Agent", "system_prompt": "t", "model": "gpt-4o-mini", "tools": []},
        )
    ).json()
    version = (
        await async_client.post(
            f"/api/v1/agents/{agent['id']}/versions", headers=h, json={}
        )
    ).json()
    await async_client.post(
        f"/api/v1/agents/{agent['id']}/versions/{version['id']}/promote",
        headers=h,
        json={"status": "ready"},
    )

    # Workflow: deploy + notify.
    created = await async_client.post(
        "/api/v1/workflows",
        headers=h,
        json={
            "name": "Deploy Agent",
            "trigger_type": "manual",
            "steps": [
                {"type": "deploy", "params": {"agent_id": agent["id"], "environment": "production"}},
            ],
        },
    )
    assert created.status_code == 201, created.text
    workflow_id = created.json()["id"]

    triggered = await async_client.post(f"/api/v1/workflows/{workflow_id}/trigger", headers=h, json={})
    run_id = triggered.json()["run_id"]

    import asyncio

    for _ in range(20):
        await asyncio.sleep(0.5)
        runs = (await async_client.get("/api/v1/workflows/runs", headers=h)).json()["runs"]
        run = next(r for r in runs if r["id"] == run_id)
        if run["status"] in ("completed", "failed"):
            break
    assert run["status"] == "completed", run
    steps = (await async_client.get(f"/api/v1/workflows/runs/{run_id}", headers=h)).json()["steps"]
    assert steps[0]["status"] == "completed"
    assert steps[0]["details"].get("slug")
    assert steps[0]["details"]["status"] == "healthy"

    # Overview de plataforma ve el workflow y el run.
    all_wf = await async_client.get("/api/v1/platform/workflows", headers=plat)
    assert all_wf.status_code == 200, all_wf.text
    assert any(w["id"] == workflow_id for w in all_wf.json()["workflows"])
    all_runs = await async_client.get("/api/v1/platform/workflows/runs", headers=plat)
    assert any(r["id"] == run_id for r in all_runs.json()["runs"])


@pytest.mark.asyncio
async def test_workflow_schedule_cron_and_reject(async_client: AsyncClient) -> None:
    from src.platform.workflows.workflows import cron_matches

    # Cron matcher unit.
    now = datetime(2026, 8, 31, 10, 30, tzinfo=timezone.utc)
    assert cron_matches("30 * * * *", now)
    assert cron_matches("*/15 * * * *", now)
    assert cron_matches("* 10 * * *", now)
    assert not cron_matches("0 * * * *", now)
    assert cron_matches("30 10 31 8 *", now)

    org = await _create_org(async_client, "Wf Cron Org")
    org["session"] = await _owner_session(org["organization_id"])
    h = _headers(org)

    created = await async_client.post(
        "/api/v1/workflows",
        headers=h,
        json={
            "name": "Hourly Report",
            "trigger_type": "schedule",
            "cron_expr": "0 * * * *",
            "steps": [{"type": "notify", "params": {"email": "fin@example.com"}}],
        },
    )
    assert created.status_code == 201, created.text
    wf_id = created.json()["id"]

    # Sin cron → 400.
    bad = await async_client.post(
        "/api/v1/workflows",
        headers=_headers(org),
        json={"name": "Bad", "trigger_type": "schedule", "steps": [{"type": "notify", "params": {"email": "x@x.com"}}]},
    )
    assert bad.status_code == 400

    # Reject flow: approval + reject → canceled.
    wf2 = await async_client.post(
        "/api/v1/workflows",
        headers=_headers(org),
        json={
            "name": "Approve Gate",
            "trigger_type": "manual",
            "steps": [{"type": "approval", "params": {"message": "ok?"}}],
        },
    )
    assert wf2.status_code == 201, wf2.text
    t2 = await async_client.post(f"/api/v1/workflows/{wf2.json()['id']}/trigger", headers=h, json={})
    run_id2 = t2.json()["run_id"]

    import asyncio

    for _ in range(20):
        await asyncio.sleep(0.5)
        runs = (await async_client.get("/api/v1/workflows/runs", headers=h)).json()["runs"]
        run = next(r for r in runs if r["id"] == run_id2)
        if run["status"] == "waiting_approval":
            break
    rejected = await async_client.post(f"/api/v1/workflows/runs/{run_id2}/reject", headers=h, json={})
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected"

    for _ in range(10):
        await asyncio.sleep(0.5)
        runs = (await async_client.get("/api/v1/workflows/runs", headers=h)).json()["runs"]
        run = next(r for r in runs if r["id"] == run_id2)
        if run["status"] == "canceled":
            break
    assert run["status"] == "canceled"

    # El workflow con cron aparece en la plataforma.
    plat = await _platform_admin(async_client, f"padmin-wfc-{uuid4().hex[:8]}@zent.example")
    all_wf = await async_client.get("/api/v1/platform/workflows", headers=plat)
    assert any(w["id"] == wf_id and w["cron_expr"] == "0 * * * *" for w in all_wf.json()["workflows"])
