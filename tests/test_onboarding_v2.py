# =============================================================================
# Tenant Onboarding Experience v2 (PROMPT 39)
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient


async def _create_org(client: AsyncClient, name: str) -> dict:
    resp = await client.post(
        "/api/v1/billing/subscription/create-trial",
        json={
            "company_name": name,
            "email": f"ob-{uuid4().hex[:8]}@example.com",
            "country": "CL",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _owner_session(client: AsyncClient, organization_id: str) -> str:
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
        "Idempotency-Key": f"ob-{uuid4().hex}",
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
async def test_initial_state_and_manual_complete(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "OB Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    state = await async_client.get("/api/v1/onboarding", headers=h)
    assert state.status_code == 200, state.text
    body = state.json()
    assert body["progress_pct"] == 0
    assert body["next_step"] == "create_kb"
    assert body["guide"]["title"] == "Empieza con tu conocimiento"
    assert body["pending_steps"] == ["create_kb", "add_documents", "create_agent", "deploy_agent", "first_query"]

    bad = await async_client.post("/api/v1/onboarding/steps/nope/complete", headers=h)
    assert bad.status_code == 400

    done = await async_client.post("/api/v1/onboarding/steps/create_kb/complete", headers=h)
    assert done.status_code == 200, done.text
    assert done.json()["completed"] is False

    state2 = await async_client.get("/api/v1/onboarding", headers=h)
    assert state2.json()["progress_pct"] == 20
    assert state2.json()["next_step"] == "add_documents"
    assert "create_kb" in state2.json()["done_steps"]


@pytest.mark.asyncio
async def test_full_completion_computes_ttfv(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "OB Full Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    for step in ["create_kb", "add_documents", "create_agent", "deploy_agent", "first_query"]:
        resp = await async_client.post(f"/api/v1/onboarding/steps/{step}/complete", headers=h)
        assert resp.status_code == 200, resp.text

    state = await async_client.get("/api/v1/onboarding", headers=h)
    assert state.json()["completed"] is True
    assert state.json()["progress_pct"] == 100
    assert state.json()["time_to_first_value_seconds"] is not None
    assert state.json()["guide"]["title"] == "¡Todo listo!"

    progress = await async_client.get("/api/v1/onboarding/progress", headers=h)
    assert progress.json()["completed_at"] is not None


@pytest.mark.asyncio
async def test_sync_from_real_actions(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "OB Sync Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    # Crear KB real → paso 1 marcado automáticamente.
    kb = await async_client.post(
        "/api/v1/knowledge-bases",
        headers={**_headers(org), "Idempotency-Key": f"ob-kb-{uuid4().hex}"},
        json={"name": "KB Onboarding"},
    )
    assert kb.status_code in (200, 201), kb.text

    # Crear agente real → paso 3 marcado.
    agent = (
        await async_client.post(
            "/api/v1/agents",
            headers={**_headers(org), "Idempotency-Key": f"ob-a-{uuid4().hex}"},
            json={"name": "OB Agent", "system_prompt": "t", "model": "gpt-4o-mini"},
        )
    ).json()

    # Deployment en production → paso 4.
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        version_id = (
            await session.execute(
                text(
                    "INSERT INTO agent_versions (id, agent_id, organization_id, "
                    "version_number, status, config_snapshot) "
                    "VALUES (gen_random_uuid(), :a, :o, 1, 'ready', '{}') RETURNING id"
                ),
                {"a": UUID(agent["id"]), "o": UUID(org["organization_id"])},
            )
        ).scalar()
        env = (
            await session.execute(
                text(
                    "INSERT INTO environments (id, organization_id, name, slug, is_default) "
                    "VALUES (gen_random_uuid(), :o, 'production', 'production', true) "
                    "RETURNING id"
                ),
                {"o": UUID(org["organization_id"])},
            )
        ).scalar()
        await session.execute(
            text(
                "INSERT INTO deployments (id, agent_id, agent_version_id, organization_id, "
                "environment_id, slug, status) "
                "VALUES (gen_random_uuid(), :a, :v, :o, :e, 'ob-prod', 'healthy')"
            ),
            {
                "a": UUID(agent["id"]),
                "v": version_id,
                "o": UUID(org["organization_id"]),
                "e": env,
            },
        )
        await session.commit()
    finally:
        await session.close()

    state = await async_client.get("/api/v1/onboarding", headers=h)
    done = set(state.json()["done_steps"])
    assert "create_kb" in done
    assert "create_agent" in done
    assert "deploy_agent" in done
    assert state.json()["next_step"] in ("add_documents", "first_query")


@pytest.mark.asyncio
async def test_activation_metrics(async_client: AsyncClient) -> None:
    org_a = await _create_org(async_client, "OB Met A")
    org_b = await _create_org(async_client, "OB Met B")
    plat = await _platform_admin(async_client, f"padmin-ob-{uuid4().hex[:8]}@zent.example")

    from src.platform.onboardingv2.onboarding import complete_step

    # A completa todo; B solo el primero.
    for step in ["create_kb", "add_documents", "create_agent", "deploy_agent", "first_query"]:
        await complete_step(UUID(org_a["organization_id"]), step)
    await complete_step(UUID(org_b["organization_id"]), "create_kb")

    metrics = await async_client.get("/api/v1/platform/onboarding/metrics", headers=plat)
    assert metrics.status_code == 200, metrics.text
    body = metrics.json()
    assert body["total_orgs"] >= 2
    assert body["completed"] >= 1
    assert body["activation_rate"] > 0
    assert body["avg_time_to_first_value_seconds"] is not None
    funnel = {f["step"]: f["orgs"] for f in body["funnel"]}
    assert funnel["create_kb"] >= 2
    assert funnel["first_query"] >= 1

    status = await async_client.get("/api/v1/platform/onboarding/status", headers=plat)
    assert status.status_code == 200, status.text
    rows = {o["organization_id"]: o for o in status.json()["organizations"]}
    assert rows[str(org_a["organization_id"])]["completed_at"] is not None
