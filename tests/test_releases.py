# =============================================================================
# AI Agent Versioning & Rollout v2 (PROMPT 42)
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
            "email": f"rl-{uuid4().hex[:8]}@example.com",
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
        "Idempotency-Key": f"rl-{uuid4().hex}",
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


async def _agent_with_versions(client: AsyncClient, org: dict, name: str, prompts: list[str]) -> tuple[str, list[str]]:
    import json

    agent = (
        await client.post(
            "/api/v1/agents",
            headers={**_headers(org), "Idempotency-Key": f"rl-a-{uuid4().hex}"},
            json={"name": name, "system_prompt": prompts[0], "model": "gpt-4o-mini"},
        )
    ).json()
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    version_ids = []
    try:
        for i, prompt in enumerate(prompts):
            vid = (
                await session.execute(
                    text(
                        "INSERT INTO agent_versions (id, agent_id, organization_id, "
                        "version_number, status, config_snapshot, notes) "
                        "VALUES (gen_random_uuid(), :a, :o, :num, 'ready', "
                        "CAST(:snap AS jsonb), :notes) RETURNING id"
                    ),
                    {
                        "a": UUID(agent["id"]),
                        "o": UUID(org["organization_id"]),
                        "num": i + 1,
                        "snap": json.dumps({"system_prompt": prompt, "model": "gpt-4o-mini", "max_tokens": 1000 + i * 500}),
                        "notes": f"v{i + 1}",
                    },
                )
            ).scalar()
            version_ids.append(str(vid))
        await session.commit()
    finally:
        await session.close()
    return agent["id"], version_ids


@pytest.mark.asyncio
async def test_versions_history_and_diff(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "RL Diff Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    agent_id, [va, vb] = await _agent_with_versions(
        async_client, org, "Diff Agent", ["prompt version uno", "prompt version dos"
    ])

    versions = await async_client.get(f"/api/v1/releases/versions/{agent_id}", headers=h)
    assert versions.status_code == 200, versions.text
    assert len(versions.json()["versions"]) == 2

    diff = await async_client.get(
        f"/api/v1/releases/diff/{agent_id}?a={va}&b={vb}", headers=h
    )
    assert diff.status_code == 200, diff.text
    body = diff.json()
    assert body["version_a"]["number"] == 1
    assert body["version_b"]["number"] == 2
    assert body["prompt_diff"]["changed"] is True
    assert body["prompt_diff"]["a"] == "prompt version uno"
    assert body["prompt_diff"]["b"] == "prompt version dos"
    assert any(c["key"] == "max_tokens" and c["kind"] == "changed" for c in body["config_diff"])
    assert body["model_changed"] is False


@pytest.mark.asyncio
async def test_release_lifecycle_promote_rollback(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "RL Life Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    agent_id, [va, vb] = await _agent_with_versions(async_client, org, "Life Agent", ["v1", "v2"])

    started = await async_client.post(
        "/api/v1/releases/start",
        headers={**_headers(org), "Idempotency-Key": f"rl-s-{uuid4().hex}"},
        json={"agent_id": agent_id, "version_id": vb, "channel": "canary", "traffic_pct": 50, "notes": "canary v2"},
    )
    assert started.status_code == 200, started.text
    release_id = started.json()["release_id"]
    assert started.json()["traffic_pct"] == 50

    health = await async_client.post(f"/api/v1/releases/{release_id}/health", headers={**_headers(org)})
    assert health.status_code == 200, health.text
    assert health.json()["passed_gate"] is True  # sin tráfico → 100

    # Deployment healthy para verificar el switch de versión.
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        env_id = (
            await session.execute(
                text(
                    "INSERT INTO environments (id, organization_id, name, slug, is_default) "
                    "VALUES (gen_random_uuid(), :o, 'production', 'production', true) RETURNING id"
                ),
                {"o": UUID(org["organization_id"])},
            )
        ).scalar()
        await session.execute(
            text(
                "INSERT INTO deployments (id, agent_id, agent_version_id, organization_id, "
                "environment_id, slug, status) "
                "VALUES (gen_random_uuid(), :a, :v, :o, :e, 'life-prod', 'healthy')"
            ),
            {"a": UUID(agent_id), "v": UUID(va), "o": UUID(org["organization_id"]), "e": env_id},
        )
        await session.commit()
    finally:
        await session.close()

    promoted = await async_client.post(f"/api/v1/releases/{release_id}/promote", headers={**_headers(org)})
    assert promoted.status_code == 200, promoted.text
    assert promoted.json()["status"] == "promoted"
    assert promoted.json()["deployments_updated"] == 1

    session = await get_async_session()
    try:
        deployed_v = (
            await session.execute(
                text(
                    "SELECT agent_version_id FROM deployments WHERE slug = 'life-prod' "
                    "AND organization_id = :oid"
                ),
                {"oid": UUID(org["organization_id"])},
            )
        ).scalar()
    finally:
        await session.close()
    assert str(deployed_v) == vb  # el deployment ahora apunta a v2

    rolled = await async_client.post(
        f"/api/v1/releases/{release_id}/rollback?detail=inestable", headers={**_headers(org)}
    )
    assert rolled.status_code == 200, rolled.text
    assert rolled.json()["status"] == "rolled_back"
    assert rolled.json()["deployments_updated"] == 1

    session = await get_async_session()
    try:
        deployed_v2 = (
            await session.execute(
                text(
                    "SELECT agent_version_id FROM deployments WHERE slug = 'life-prod' "
                    "AND organization_id = :oid"
                ),
                {"oid": UUID(org["organization_id"])},
            )
        ).scalar()
    finally:
        await session.close()
    assert str(deployed_v2) == va  # rollback a v1

    detail = await async_client.get(f"/api/v1/releases/{release_id}", headers={**_headers(org)})
    events = [e["event_type"] for e in detail.json()["events"]]
    assert "started" in events
    assert "health_ok" in events
    assert "promoted" in events
    assert "rolled_back" in events


@pytest.mark.asyncio
async def test_health_gate_with_traffic_and_pause(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "RL Health Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    agent_id, [va, vb] = await _agent_with_versions(async_client, org, "Health Agent", ["v1", "v2"])

    from src.platform.releases.releases import start_release

    started = await start_release(UUID(agent_id), UUID(vb), "canary", 100)
    release_id = UUID(started["release_id"])

    # Tráfico con errores altos → health fail.
    from src.platform.proxy.inference_proxy import log_inference

    for i in range(10):
        await log_inference(
            organization_id=UUID(org["organization_id"]),
            deployment_id=None,
            agent_id=UUID(agent_id),
            model="gpt-4o-mini",
            backend="openai",
            status="error" if i < 6 else "completed",
            prompt_tokens=50,
            completion_tokens=25,
            latency_ms=3000.0,
            cost=0.001,
        )

    from src.platform.releases.releases import health_check

    result = await health_check(release_id)
    assert result["health_score"] < 100
    assert result["passed_gate"] is False  # 60% error rate + p95 3s → fail

    detail = await async_client.get(f"/api/v1/releases/{release_id}", headers=h)
    events = [e["event_type"] for e in detail.json()["events"]]
    assert "health_fail" in events

    paused = await async_client.post(f"/api/v1/releases/{release_id}/pause", headers={**_headers(org)})
    assert paused.json()["status"] == "paused"
    resumed = await async_client.post(f"/api/v1/releases/{release_id}/resume", headers={**_headers(org)})
    assert resumed.json()["status"] == "running"


@pytest.mark.asyncio
async def test_platform_dashboard(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "RL Dash Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    plat = await _platform_admin(async_client, f"padmin-rld-{uuid4().hex[:8]}@zent.example")

    agent_id, [va, vb] = await _agent_with_versions(async_client, org, "Dash Agent", ["v1", "v2"])
    from src.platform.releases.releases import promote, start_release

    rel = await start_release(UUID(agent_id), UUID(vb), "stable", 100)
    await promote(UUID(rel["release_id"]))

    dash = await async_client.get("/api/v1/platform/releases/dashboard", headers=plat)
    assert dash.status_code == 200, dash.text
    assert dash.json()["total_releases"] >= 1
    entry = next(a for a in dash.json()["agents"] if a["agent_id"] == str(agent_id))
    assert entry["stable"]["version"] == 2
    assert entry["stable"]["status"] == "promoted"
