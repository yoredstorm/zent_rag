# =============================================================================
# Onboarding & Tenancy Self-Serve (PROMPT 21)
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


@pytest.mark.asyncio
async def test_provision_tenant_one_click(async_client: AsyncClient) -> None:
    plat = await _platform_admin(async_client, f"padmin-ob-{uuid4().hex[:8]}@zent.example")

    email = f"provisioned-{uuid4().hex[:8]}@corp.example"
    prov = await async_client.post(
        "/api/v1/platform/onboarding/provision",
        headers=plat,
        json={"company_name": "Corp Provisioned", "email": email, "plan_name": "pro", "with_demo": True},
    )
    assert prov.status_code == 201, prov.text
    body = prov.json()
    assert body["status"] == "provisioned"
    oid = body["organization_id"]
    assert body["plan"] == "pro"
    assert body["api_token"].startswith("zent_sk_live_")
    assert body["demo_kb_id"]
    assert body["demo_agent_id"]
    assert body["owner_user_id"]

    # El owner existe con rol owner y puede autenticarse.
    from src.infrastructure.postgres.relational_db import (
        PostgresMembershipRepository,
        PostgresUserRepository,
    )

    user = await PostgresUserRepository().get_by_email(email)
    assert user is not None
    assert str(user.organization_id) == oid
    roles = await PostgresMembershipRepository().get_user_roles(
        user.id, UUID(oid)
    )
    assert any(r.name == "owner" for r in roles), roles

    # Suscripción pro activa.
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        plan = (
            await session.execute(
                text(
                    "SELECT p.name FROM subscriptions s JOIN plans p ON p.id = s.plan_id "
                    "WHERE s.organization_id = :oid"
                ),
                {"oid": UUID(oid)},
            )
        ).scalar()
        kb_count = int(
            (
                await session.execute(
                    text(
                        "SELECT COUNT(*) FROM knowledge_bases WHERE organization_id = :oid"
                    ),
                    {"oid": UUID(oid)},
                )
            ).scalar()
            or 0
        )
        agent_count = int(
            (
                await session.execute(
                    text("SELECT COUNT(*) FROM agents WHERE organization_id = :oid"),
                    {"oid": UUID(oid)},
                )
            ).scalar()
            or 0
        )
    finally:
        await session.close()
    assert plan == "pro"
    assert kb_count == 1
    assert agent_count == 1

    # Catálogo de planes disponible.
    plans = await async_client.get("/api/v1/platform/onboarding/plans", headers=plat)
    assert plans.status_code == 200, plans.text
    assert len(plans.json()["plans"]) >= 1


@pytest.mark.asyncio
async def test_provision_with_sso_and_trial(async_client: AsyncClient) -> None:
    plat = await _platform_admin(async_client, f"padmin-ob2-{uuid4().hex[:8]}@zent.example")

    prov = await async_client.post(
        "/api/v1/platform/onboarding/provision",
        headers=plat,
        json={
            "company_name": "Sso Corp",
            "email": f"sso-{uuid4().hex[:8]}@corp.example",
            "plan_name": "trial",
            "with_demo": False,
            "sso_issuer": "https://idp.example.com",
            "sso_client_id": "app-provisioned",
            "sso_client_secret": "sk-provisioned-secret",
        },
    )
    assert prov.status_code == 201, prov.text
    oid = prov.json()["organization_id"]
    assert prov.json()["plan"] == "trial"

    from src.platform.enterprise.sso import get_sso_config

    cfg = await get_sso_config(UUID(oid))
    assert cfg["sso_enabled"] is True
    assert cfg["issuer"] == "https://idp.example.com"
    assert cfg["client_id"] == "app-provisioned"


@pytest.mark.asyncio
async def test_migrate_and_extend_trial(async_client: AsyncClient) -> None:
    plat = await _platform_admin(async_client, f"padmin-ob3-{uuid4().hex[:8]}@zent.example")

    # Org fuente con KB + agente.
    source = await _create_org(async_client, "Migrate Source")
    source["session"] = await _owner_session(source["organization_id"])
    h = {
        "Authorization": f"Bearer {source['session']}",
        "X-Organization-Id": source["organization_id"],
        "Idempotency-Key": f"ob-k-{uuid4().hex}",
    }
    kb = await async_client.post(
        "/api/v1/knowledge-bases",
        headers=h,
        json={"name": "KB Fuente", "description": "d"},
    )
    assert kb.status_code in (200, 201), kb.text
    agent = (
        await async_client.post(
            "/api/v1/agents",
            headers={**h, "Idempotency-Key": f"ob-a-{uuid4().hex}"},
            json={"name": "Agent Fuente", "system_prompt": "p", "model": "gpt-4o-mini"},
        )
    ).json()

    # Org destino.
    target = await _create_org(async_client, "Migrate Target")
    target["session"] = await _owner_session(target["organization_id"])

    mig = await async_client.post(
        "/api/v1/platform/onboarding/migrate",
        headers=plat,
        json={
            "source_organization_id": source["organization_id"],
            "target_organization_id": target["organization_id"],
            "migrate_kbs": True,
            "migrate_agents": True,
        },
    )
    assert mig.status_code == 200, mig.text
    out = mig.json()
    assert out["status"] == "migrated"
    assert out["knowledge_bases"] == 1
    assert out["agents"] == 1

    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        kb_names = (
            await session.execute(
                text(
                    "SELECT name FROM knowledge_bases WHERE organization_id = :oid"
                ),
                {"oid": UUID(target["organization_id"])},
            )
        ).fetchall()
        agent_names = (
            await session.execute(
                text("SELECT name FROM agents WHERE organization_id = :oid"),
                {"oid": UUID(target["organization_id"])},
            )
        ).fetchall()
    finally:
        await session.close()
    assert any(k.name == "KB Fuente" for k in kb_names)
    assert any(a.name == "Agent Fuente (migrado)" for a in agent_names)

    # Migrar a org inexistente → 404.
    missing = await async_client.post(
        "/api/v1/platform/onboarding/migrate",
        headers=plat,
        json={
            "source_organization_id": source["organization_id"],
            "target_organization_id": str(uuid4()),
        },
    )
    assert missing.status_code == 404

    # Extender trial del target (recientemente creado, en trial).
    before = (
        await session.execute(
            text(
                "SELECT trial_end FROM subscriptions WHERE organization_id = :oid"
            ),
            {"oid": UUID(target["organization_id"])},
        )
    ).scalar()
    ext = await async_client.post(
        "/api/v1/platform/onboarding/extend-trial",
        headers=plat,
        json={"organization_id": target["organization_id"], "days": 14},
    )
    assert ext.status_code == 200, ext.text
    assert ext.json()["status"] == "extended"
    after = ext.json()["trial_end"]
    assert after > before.isoformat()

    # Org provisionada con pro sigue en status trialing → extender devuelve 200.
    prov = await async_client.post(
        "/api/v1/platform/onboarding/provision",
        headers=plat,
        json={"company_name": "Pro Corp", "email": f"pro-{uuid4().hex[:8]}@corp.example", "plan_name": "pro"},
    )
    ext_pro = await async_client.post(
        "/api/v1/platform/onboarding/extend-trial",
        headers=plat,
        json={"organization_id": prov.json()["organization_id"], "days": 7},
    )
    assert ext_pro.status_code == 200, ext_pro.text
    assert ext_pro.json()["status"] == "extended"

    # Org NO trialing → 400.
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE subscriptions SET status = 'active' "
                "WHERE organization_id = :oid"
            ),
            {"oid": UUID(prov.json()["organization_id"])},
        )
        await session.commit()
    finally:
        await session.close()
    ext_active = await async_client.post(
        "/api/v1/platform/onboarding/extend-trial",
        headers=plat,
        json={"organization_id": prov.json()["organization_id"], "days": 7},
    )
    assert ext_active.status_code == 400
