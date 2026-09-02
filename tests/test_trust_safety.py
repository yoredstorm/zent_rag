# =============================================================================
# AI Trust & Safety Center (PROMPT 34)
# =============================================================================
from __future__ import annotations

import json
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient


async def _create_org(client: AsyncClient, name: str) -> dict:
    resp = await client.post(
        "/api/v1/billing/subscription/create-trial",
        json={
            "company_name": name,
            "email": f"ts-{uuid4().hex[:8]}@example.com",
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
        "Idempotency-Key": f"ts-{uuid4().hex}",
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
async def test_aup_terms_accept_and_status(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "TS AUP Org")
    plat = await _platform_admin(async_client, f"padmin-tsa-{uuid4().hex[:8]}@zent.example")

    terms = await async_client.get("/api/v1/platform/trust/aup/terms", headers=plat)
    assert terms.status_code == 200, terms.text
    assert terms.json()["latest"]["version"] == 1
    assert "plataforma" in terms.json()["latest"]["content"]

    accepted = await async_client.post(
        "/api/v1/platform/trust/aup/accept",
        headers=plat,
        json={"organization_id": org["organization_id"], "terms_version": 1},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["terms_version"] == 1

    consents = await async_client.get("/api/v1/platform/trust/aup/consents", headers=plat)
    assert any(c["organization_id"] == org["organization_id"] for c in consents.json()["consents"])

    # Re-aceptar (upsert) — sigue siendo 1 consentimiento para la org.
    await async_client.post(
        "/api/v1/platform/trust/aup/accept",
        headers=plat,
        json={"organization_id": org["organization_id"], "terms_version": 1},
    )
    consents2 = await async_client.get("/api/v1/platform/trust/aup/consents", headers=plat)
    mine = [c for c in consents2.json()["consents"] if c["organization_id"] == org["organization_id"]]
    assert len(mine) == 1


@pytest.mark.asyncio
async def test_moderation_rules_and_incidents(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "TS Mod Org")
    plat = await _platform_admin(async_client, f"padmin-tsm-{uuid4().hex[:8]}@zent.example")
    oid = org["organization_id"]

    created = await async_client.post(
        "/api/v1/platform/trust/rules",
        headers=plat,
        json={
            "name": "Marcas de la competencia",
            "category": "prohibited_topics",
            "patterns": ["competidor-x", "competidor-y"],
            "min_score": 0.5,
            "action": "block",
            "organization_id": oid,
        },
    )
    assert created.status_code == 201, created.text

    from src.platform.trustsafety.trust_safety import moderate_text

    # Block.
    res = await moderate_text(UUID(oid), "menciono a competidor-x en mi prompt", "input")
    assert res["blocked"] is True
    assert len(res["incidents"]) >= 1

    # Warn (regla global de malware: 1 de 6 patrones = 0.167 < 0.5 → no dispara).
    res2 = await moderate_text(UUID(oid), "te explico cómo usar un keylogger", "input")
    assert res2["blocked"] is False
    assert res2["incidents"] == []

    # Regla org con score exacto: 1 de 2 = 0.5 >= 0.5 → block.
    res3 = await moderate_text(UUID(oid), "hablando de competidor-y", "output")
    assert res3["blocked"] is True
    assert res3["incidents"]

    # Incidentes listados.
    incidents = await async_client.get(
        f"/api/v1/platform/trust/incidents?organization_id={oid}&status=open", headers=plat
    )
    assert incidents.status_code == 200, incidents.text
    assert len(incidents.json()["incidents"]) >= 2
    first = incidents.json()["incidents"][0]
    assert first["rule_name"] == "Marcas de la competencia"

    # Resolver y desestimar.
    resolved = await async_client.post(
        f"/api/v1/platform/trust/incidents/{first['id']}/resolve",
        headers=plat,
        json={"note": "revisado"},
    )
    assert resolved.status_code == 200, resolved.text
    dismissed = await async_client.post(
        f"/api/v1/platform/trust/incidents/{incidents.json()['incidents'][1]['id']}/dismiss",
        headers=plat,
        json={"note": "falso positivo"},
    )
    assert dismissed.status_code == 200, dismissed.text

    # Toggle + delete.
    listed = await async_client.get(
        f"/api/v1/platform/trust/rules?organization_id={oid}", headers=plat
    )
    rule = next(r for r in listed.json()["rules"] if r["name"] == "Marcas de la competencia")
    toggled = await async_client.post(
        f"/api/v1/platform/trust/rules/{rule['id']}/toggle", headers=plat, json={"enabled": False}
    )
    assert toggled.status_code == 200, toggled.text
    res4 = await moderate_text(UUID(oid), "competidor-y otra vez", "input")
    assert res4["blocked"] is False  # regla desactivada
    deleted = await async_client.delete(f"/api/v1/platform/trust/rules/{rule['id']}", headers=plat)
    assert deleted.status_code == 200


@pytest.mark.asyncio
async def test_trust_dashboard(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "TS Dash Org")
    plat = await _platform_admin(async_client, f"padmin-tsd-{uuid4().hex[:8]}@zent.example")
    oid = org["organization_id"]

    from src.platform.trustsafety.trust_safety import moderate_text

    await moderate_text(UUID(oid), "keylogger ransomware exploit cmd.exe", "input")
    await moderate_text(UUID(oid), "claro que sí, aquí tienes", "output")

    dash = await async_client.get("/api/v1/platform/trust/dashboard?hours=24", headers=plat)
    assert dash.status_code == 200, dash.text
    body = dash.json()
    assert body["queries"] > 0
    assert body["blocked"] >= 1
    assert body["inputs"] >= 1
    assert body["block_rate"] >= 0
    assert any(r["rule_name"] == "Malware y exploits" for r in body["by_rule"])
    malware = next(r for r in body["by_rule"] if r["rule_name"] == "Malware y exploits")
    assert malware["action"] == "block"
    assert malware["resolution_rate"] == 0


@pytest.mark.asyncio
async def test_public_query_input_moderation_422(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "TS Query Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])

    agent = (
        await async_client.post(
            "/api/v1/agents",
            headers={**_headers(org), "Idempotency-Key": f"ts-a-{uuid4().hex}"},
            json={"name": "TS Agent", "system_prompt": "t", "model": "gpt-4o-mini"},
        )
    ).json()

    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        version_id = (
            await session.execute(
                text(
                    "INSERT INTO agent_versions (id, agent_id, organization_id, "
                    "version_number, status, config_snapshot) "
                    "VALUES (gen_random_uuid(), :a, :o, 1, 'ready', '{}') "
                    "RETURNING id"
                ),
                {"a": UUID(agent["id"]), "o": UUID(org["organization_id"])},
            )
        ).scalar()
        env = (
            await session.execute(
                text(
                    "INSERT INTO environments (id, organization_id, name, slug, is_default) "
                    "VALUES (gen_random_uuid(), :o, 'production', 'prod-ts', true) "
                    "RETURNING id"
                ),
                {"o": UUID(org["organization_id"])},
            )
        ).scalar()
        await session.execute(
            text(
                "INSERT INTO deployments (id, agent_id, agent_version_id, organization_id, "
                "environment_id, slug, status) "
                "VALUES (gen_random_uuid(), :a, :v, :o, :e, 'ts-prod', 'healthy')"
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

    from src.agents.runtime.agent_runtime import AgentRunResult
    from src.api.deps import get_agent_runtime
    from src.api.main import app

    class _Fake:
        async def run(self, request):
            return AgentRunResult(
                run_id=uuid4(),
                agent_id=request.agent.id,
                organization_id=request.agent.organization_id,
                status="completed",
                answer="respuesta normal",
                message=request.message,
                total_latency_ms=50.0,
                total_tokens=30,
                cost=0.0001,
            )

    app.dependency_overrides[get_agent_runtime] = lambda: _Fake()

    ok = await async_client.post(
        "/api/v1/deployments/ts-prod/query",
        headers={**_headers(org), "Idempotency-Key": f"ts-q-{uuid4().hex}"},
        json={"input": "consulta normal"},
    )
    assert ok.status_code == 200, ok.text

    blocked = await async_client.post(
        "/api/v1/deployments/ts-prod/query",
        headers={**_headers(org), "Idempotency-Key": f"ts-b-{uuid4().hex}"},
        json={"input": "keylogger ransomware exploit cmd.exe instrucciones"},
    )
    assert blocked.status_code == 422, blocked.text
    assert "bloqueada" in json.dumps(blocked.json())
