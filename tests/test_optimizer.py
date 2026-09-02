# =============================================================================
# Optimizer (PROMPT 14) — perfiles, recomendaciones, apply/ignore
# =============================================================================
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient


async def _create_org(client: AsyncClient, name: str) -> dict:
    resp = await client.post(
        "/api/v1/billing/subscription/create-trial",
        json={
            "company_name": name,
            "email": f"opt-{uuid4().hex[:8]}@example.com",
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


async def _seed_slow_agent_usage(client: AsyncClient, org: dict) -> dict:
    """Agente con 10 requests: p95 alto, cost/req alto, tokens altos."""
    from uuid import uuid4 as _u4

    agent_resp = await client.post(
        "/api/v1/agents",
        headers={
            "Authorization": f"Bearer {org['session']}",
            "X-Organization-Id": org["organization_id"],
            "Idempotency-Key": f"opt-{_u4().hex}",
        },
        json={"name": "Slow Agent", "system_prompt": "t", "model": "gpt-4o-mini", "tools": []},
    )
    assert agent_resp.status_code in (200, 201), agent_resp.text
    agent = agent_resp.json()

    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    oid = UUID(org["organization_id"])
    now = datetime.now(timezone.utc)
    session = await get_async_session()
    try:
        for i in range(10):
            await session.execute(
                text(
                    "INSERT INTO usage_events (request_id, event_type, organization_id, "
                    "agent_id, deployment_id, model, provider, total_tokens, "
                    "embedding_tokens, retrieval_count, latency_ms, status, "
                    "estimated_cost, created_at) "
                    "VALUES (gen_random_uuid(), 'agent_run', :oid, :aid, NULL, "
                    "'gpt-4o-mini', 'openai', 2500, 1000, 8, 20000.0, 'completed', "
                    "0.004, :created)"
                ),
                {
                    "oid": oid,
                    "aid": UUID(agent["id"]),
                    "created": now - timedelta(hours=i),
                },
            )
        await session.commit()
    finally:
        await session.close()
    return agent


@pytest.mark.asyncio
async def test_optimizer_profiles(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Opt Profiles Org")
    org["session"] = await _owner_session(org["organization_id"])
    plat = await _platform_admin(async_client, f"padmin-opt-{uuid4().hex[:8]}@zent.example")
    agent = await _seed_slow_agent_usage(async_client, org)

    resp = await async_client.get(
        f"/api/v1/platform/optimizer/profiles?organization_id={org['organization_id']}",
        headers=plat,
    )
    assert resp.status_code == 200, resp.text
    profiles = resp.json()["profiles"]
    mine = next(p for p in profiles if p["agent_id"] == agent["id"])
    assert mine["requests"] == 10
    assert mine["p95_ms"] == pytest.approx(20000.0, abs=1.0)
    assert mine["cost_per_request"] == pytest.approx(0.004, abs=1e-6)
    assert mine["tokens_per_request"] == pytest.approx(2500.0, abs=1.0)
    assert mine["sources_per_request"] == pytest.approx(8.0, abs=0.1)
    assert mine["embedding_share_pct"] == pytest.approx(40.0, abs=0.1)


@pytest.mark.asyncio
async def test_optimizer_scan_and_apply(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Opt Apply Org")
    org["session"] = await _owner_session(org["organization_id"])
    plat = await _platform_admin(async_client, f"padmin-apply-{uuid4().hex[:8]}@zent.example")
    agent = await _seed_slow_agent_usage(async_client, org)
    oid = org["organization_id"]

    # Scan → recomendaciones (p95 20s > 10.5s, tokens 2500, cost 0.004, 8 fuentes, 40% embed).
    scan = await async_client.post(
        f"/api/v1/platform/optimizer/scan?organization_id={oid}", headers=plat, json={}
    )
    assert scan.status_code == 200, scan.text
    created = {c["type"] for c in scan.json()["recommendations_created"]}
    assert "cheaper_model" in created
    assert "reduce_top_k" in created
    assert "prune_sources" in created
    assert "embedding_cache" in created

    # Dedupe: re-scan no duplica.
    scan2 = await async_client.post(
        f"/api/v1/platform/optimizer/scan?organization_id={oid}", headers=plat, json={}
    )
    assert scan2.json()["count"] == 0

    listed = await async_client.get(
        f"/api/v1/platform/optimizer/recommendations?organization_id={oid}", headers=plat
    )
    assert listed.status_code == 200, listed.text
    recs = listed.json()["recommendations"]
    assert len(recs) >= 4
    model_rec = next(r for r in recs if r["recommendation_key"] == "cheaper_model")
    assert model_rec["expected_savings_pct"] == 30.0
    assert model_rec["status"] == "suggested"

    # Apply model → agent.model = zent-cheap; top_k rec aplicada → config retrieval.top_k 3.
    applied = await async_client.post(
        f"/api/v1/platform/optimizer/recommendations/{model_rec['id']}/apply",
        headers=plat,
        json={},
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["status"] == "applied"
    assert applied.json()["model"] == "zent-cheap"

    # Agente actualizado.
    agents = await async_client.get(
        f"/api/v1/platform/organizations/{oid}/agents", headers=plat
    )
    mine = next(a for a in agents.json()["agents"] if a["id"] == agent["id"])
    assert mine["model"] == "zent-cheap"

    # Apply top_k.
    topk_rec = next(
        r for r in recs if r["recommendation_key"] == "reduce_top_k"
    )
    applied2 = await async_client.post(
        f"/api/v1/platform/optimizer/recommendations/{topk_rec['id']}/apply",
        headers=plat,
        json={},
    )
    assert applied2.json()["status"] == "applied"

    # Ignorar una.
    prune_rec = next(r for r in recs if r["recommendation_key"] == "prune_sources")
    ignored = await async_client.post(
        f"/api/v1/platform/optimizer/recommendations/{prune_rec['id']}/ignore",
        headers=plat,
        json={},
    )
    assert ignored.status_code == 200, ignored.text

    # Estado final.
    final = await async_client.get(
        f"/api/v1/platform/optimizer/recommendations?organization_id={oid}", headers=plat
    )
    statuses = {r["id"]: r["status"] for r in final.json()["recommendations"]}
    assert statuses[model_rec["id"]] == "applied"
    assert statuses[prune_rec["id"]] == "ignored"


@pytest.mark.asyncio
async def test_optimizer_deployment_profile(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Opt Deploy Org")
    org["session"] = await _owner_session(org["organization_id"])
    plat = await _platform_admin(async_client, f"padmin-dep-{uuid4().hex[:8]}@zent.example")
    _agent = await _seed_slow_agent_usage(async_client, org)

    dep_resp = await async_client.get(
        "/api/v1/deployments",
        headers={
            "Authorization": f"Bearer {org['session']}",
            "X-Organization-Id": org["organization_id"],
        },
    )
    # Si el agente no está desplegado, el endpoint de profile responde 404 limpio.
    missing = await async_client.get(
        f"/api/v1/platform/optimizer/profiles?organization_id={org['organization_id']}"
        f"&deployment_id={uuid4()}",
        headers=plat,
    )
    assert missing.status_code == 404
