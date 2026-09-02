# =============================================================================
# AI Governance (PROMPT 13) — PII masking, anomalías, audit intelligence,
# prompt revisions, políticas AI.
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
            "email": f"ai-{uuid4().hex[:8]}@example.com",
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
async def test_pii_mask_and_scan(async_client: AsyncClient) -> None:
    plat = await _platform_admin(async_client, f"padmin-pii-{uuid4().hex[:8]}@zent.example")

    text = "Contacta a maria@corp.example o al +51 999 888 777. DNI 12345678, RUC 20123456789."
    mask = await async_client.post(
        "/api/v1/platform/ai-governance/pii/mask", headers=plat, json={"text": text}
    )
    assert mask.status_code == 200, mask.text
    body = mask.json()
    assert body["detected"]["email"] == 1
    assert body["detected"]["phone"] >= 1
    assert body["detected"]["dni"] == 1
    assert body["detected"]["ruc"] == 1
    assert "maria@corp.example" not in body["masked"]
    assert "999 888 777" not in body["masked"]

    scan = await async_client.post(
        "/api/v1/platform/ai-governance/pii/scan", headers=plat, json={"text": text}
    )
    assert scan.status_code == 200, scan.text
    assert scan.json()["detected"]["email"] == 1

    # Unit: la máscara no rompe texto limpio.
    from src.platform.ai_governance.ai_governance import mask_pii

    clean, counts = mask_pii("Hola, este es un texto sin datos personales.")
    assert clean == "Hola, este es un texto sin datos personales."
    assert counts == {}


@pytest.mark.asyncio
async def test_ai_policies_and_public_query_guardrail(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "AI Policies Org")
    org["session"] = await _owner_session(org["organization_id"])
    plat = await _platform_admin(async_client, f"padmin-pol-{uuid4().hex[:8]}@zent.example")
    oid = org["organization_id"]

    # Políticas roundtrip.
    put = await async_client.put(
        f"/api/v1/platform/ai-governance/organizations/{oid}",
        headers=plat,
        json={"pii_masking_enabled": True, "guardrails": {"max_tokens_per_query": 2000}},
    )
    assert put.status_code == 200, put.text
    got = await async_client.get(
        f"/api/v1/platform/ai-governance/organizations/{oid}", headers=plat
    )
    assert got.status_code == 200, got.text
    assert got.json()["pii_masking_enabled"] is True
    assert got.json()["guardrails"]["max_tokens_per_query"] == 2000

    # Guardrail aplicado en el endpoint público (runtime fake con PII en la respuesta).
    from src.agents.runtime.agent_runtime import AgentRunResult
    from src.api.deps import get_agent_runtime
    from src.api.main import app

    class _FakeRuntime:
        async def run(self, request):
            return AgentRunResult(
                run_id=uuid4(),
                agent_id=request.agent.id,
                organization_id=request.agent.organization_id,
                status="completed",
                answer="El contacto es juan@corp.example y su teléfono +51 999 111 222.",
                message=request.message,
                total_latency_ms=5.0,
                total_tokens=10,
                cost=0.0001,
            )

    app.dependency_overrides[get_agent_runtime] = lambda: _FakeRuntime()

    # Deployment para el public query.
    agent = (
        await async_client.post(
            "/api/v1/agents",
            headers={**_headers(org), "Idempotency-Key": f"ai-{uuid4().hex}"},
            json={"name": "AI Agent", "system_prompt": "t", "model": "gpt-4o-mini", "tools": []},
        )
    ).json()
    version = (
        await async_client.post(f"/api/v1/agents/{agent['id']}/versions", headers=_headers(org), json={})
    ).json()
    await async_client.post(
        f"/api/v1/agents/{agent['id']}/versions/{version['id']}/promote",
        headers=_headers(org),
        json={"status": "ready"},
    )
    envs = (await async_client.get("/api/v1/environments", headers=_headers(org))).json()["environments"]
    prod = next(e for e in envs if e["slug"] == "production")
    dep = (
        await async_client.post(
            "/api/v1/deployments",
            headers={**_headers(org), "Idempotency-Key": f"ai-dep-{uuid4().hex}"},
            json={
                "agent_id": agent["id"],
                "agent_version_id": version["id"],
                "environment_id": prod["id"],
            },
        )
    ).json()
    assert dep["status"] == "healthy"

    q = await async_client.post(
        f"/api/v1/deployments/{dep['slug']}/query",
        headers={**_headers(org), "Idempotency-Key": f"ai-q-{uuid4().hex}"},
        json={"input": "¿quién es el contacto?"},
    )
    assert q.status_code == 200, q.text
    body = q.json()
    assert "juan@corp.example" not in body["answer"]
    assert body["guardrails"]["pii_masked"]["email"] == 1

    # Sin política: sin enmascarar.
    await async_client.put(
        f"/api/v1/platform/ai-governance/organizations/{oid}",
        headers=plat,
        json={"pii_masking_enabled": False},
    )
    q2 = await async_client.post(
        f"/api/v1/deployments/{dep['slug']}/query",
        headers={**_headers(org), "Idempotency-Key": f"ai-q2-{uuid4().hex}"},
        json={"input": "¿quién es el contacto?"},
    )
    assert "juan@corp.example" in q2.json()["answer"]


@pytest.mark.asyncio
async def test_anomaly_detection_and_resolve(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "AI Anomaly Org")
    org["session"] = await _owner_session(org["organization_id"])
    plat = await _platform_admin(async_client, f"padmin-anom-{uuid4().hex[:8]}@zent.example")
    oid = org["organization_id"]

    # Seed: burst de logins fallidos en Redis + api_logs con error spike + 403s.
    from src.infrastructure.redis.cache import _get_redis

    redis = await _get_redis()
    for i in range(6):
        await redis.incr(f"auth:fail:anomaly-test-{i}")
        await redis.expire(f"auth:fail:anomaly-test-{i}", 300)

    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        for _ in range(25):
            await session.execute(
                text(
                    "INSERT INTO api_logs (request_id, organization_id, deployment_id, "
                    "api_key_id, endpoint, method, status, latency_ms, tokens, cost, created_at) "
                    "VALUES (gen_random_uuid(), :oid, NULL, NULL, '/query', 'POST', 500, "
                    "800.0, 100, 0.001, NOW())"
                ),
                {"oid": UUID(oid)},
            )
        await session.commit()
    finally:
        await session.close()

    check = await async_client.post(
        "/api/v1/platform/audit-intelligence/check",
        headers=plat,
        json={"organization_id": oid},
    )
    assert check.status_code == 200, check.text
    types = {c["type"] for c in check.json()["anomalies_created"]}
    assert "failed_login_burst" in types
    assert "api_error_spike" in types

    # Dedupe: re-check no duplica.
    check2 = await async_client.post(
        "/api/v1/platform/audit-intelligence/check",
        headers=plat,
        json={"organization_id": oid},
    )
    assert check2.json()["count"] == 0

    listed = await async_client.get(
        f"/api/v1/platform/audit-intelligence/anomalies?organization_id={oid}", headers=plat
    )
    assert listed.status_code == 200, listed.text
    login_anom = next(a for a in listed.json()["anomalies"] if a["anomaly_type"] == "failed_login_burst")
    assert login_anom["severity"] == "critical"

    resolved = await async_client.post(
        f"/api/v1/platform/audit-intelligence/anomalies/{login_anom['id']}/resolve",
        headers=plat,
        json={},
    )
    assert resolved.status_code == 200, resolved.text


@pytest.mark.asyncio
async def test_audit_intelligence_summary(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "AI Audit Org")
    org["session"] = await _owner_session(org["organization_id"])
    plat = await _platform_admin(async_client, f"padmin-intel-{uuid4().hex[:8]}@zent.example")

    # Generar eventos de auditoría (login del owner crea auth.login).
    _headers(org)

    summary = await async_client.get(
        "/api/v1/platform/audit-intelligence/summary", headers=plat
    )
    assert summary.status_code == 200, summary.text
    body = summary.json()
    assert body["total_events"] >= 1
    actions = {a["action"] for a in body["top_actions"]}
    assert any("login" in a for a in actions)

    per_org = await async_client.get(
        f"/api/v1/platform/audit-intelligence/summary?organization_id={org['organization_id']}",
        headers=plat,
    )
    assert per_org.status_code == 200, per_org.text
    assert per_org.json()["organization_id"] == org["organization_id"]


@pytest.mark.asyncio
async def test_prompt_revisions(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "AI Prompt Org")
    org["session"] = await _owner_session(org["organization_id"])
    h = _headers(org)
    plat = await _platform_admin(async_client, f"padmin-rev-{uuid4().hex[:8]}@zent.example")

    # Actualizar el prompt dos veces → 2 revisiones.
    for i in range(2):
        upd = await async_client.put(
            "/api/v1/admin/prompt",
            headers={**h, "Idempotency-Key": f"ai-pr-{uuid4().hex}"},
            json={"system_prompt": f"Prompt versión {i + 1}", "role": "admin"},
        )
        assert upd.status_code == 200, upd.text

    revs = await async_client.get(
        f"/api/v1/platform/ai-governance/prompts/system_prompt_admin/revisions?organization_id={org['organization_id']}",
        headers=plat,
    )
    assert revs.status_code == 200, revs.text
    revisions = revs.json()["revisions"]
    assert len(revisions) >= 2
    assert revisions[0]["version"] > revisions[1]["version"]
    assert revisions[0]["content"] == "Prompt versión 2"
