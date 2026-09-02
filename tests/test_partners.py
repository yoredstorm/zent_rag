# =============================================================================
# Partner Ecosystem (PROMPT 24)
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
            "email": f"prt-{uuid4().hex[:8]}@example.com",
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
        "Idempotency-Key": f"prt-{uuid4().hex}",
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
async def test_partner_create_and_key(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Partner Org")
    org["session"] = await _owner_session(org["organization_id"])
    plat = await _platform_admin(async_client, f"padmin-prt-{uuid4().hex[:8]}@zent.example")

    created = await async_client.post(
        "/api/v1/platform/partners",
        headers=plat,
        json={
            "organization_id": org["organization_id"],
            "name": "Integrador XYZ",
            "contact_email": "partners@xyz.example",
            "rev_share_pct": 20,
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    partner_id = body["id"]
    assert body["rev_share_pct"] == 20.0
    token = body["api_token"]
    assert token.startswith("zent_sk_partner_")

    # La key del partner está vinculada (partner_id en api_keys).
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT partner_id, scopes FROM api_keys "
                    "WHERE partner_id = :pid LIMIT 1"
                ),
                {"pid": UUID(partner_id)},
            )
        ).fetchone()
    finally:
        await session.close()
    assert str(row.partner_id) == partner_id
    assert "partner:*" in row.scopes

    # El token autentica con el contexto de partner.
    from src.infrastructure.postgres.relational_db import (
        PostgresApiKeyRepository,
        PostgresBillingRepository,
    )
    from src.platform.billing.service import BillingService

    billing = BillingService(PostgresBillingRepository(), PostgresApiKeyRepository())
    ctx = await billing.validate_token(token)
    assert "partner:*" in ctx.scopes

    # Listar.
    listed = await async_client.get("/api/v1/platform/partners", headers=plat)
    assert listed.status_code == 200, listed.text
    assert any(p["id"] == partner_id for p in listed.json()["partners"])


@pytest.mark.asyncio
async def test_partner_metering_and_commission(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Partner Meter Org")
    org["session"] = await _owner_session(org["organization_id"])
    plat = await _platform_admin(async_client, f"padmin-prtm-{uuid4().hex[:8]}@zent.example")

    created = await async_client.post(
        "/api/v1/platform/partners",
        headers=plat,
        json={"organization_id": org["organization_id"], "name": "Meter Partner", "rev_share_pct": 25},
    )
    partner_id = created.json()["id"]

    # Metering directo.
    from src.platform.partners.partners import record_partner_usage

    await record_partner_usage(UUID(partner_id), UUID(org["organization_id"]), tokens=1000, cost=0.04)
    await record_partner_usage(UUID(partner_id), UUID(org["organization_id"]), tokens=500, cost=0.02)

    usage = await async_client.get(
        f"/api/v1/platform/partners/{partner_id}/usage?days=30", headers=plat
    )
    assert usage.status_code == 200, usage.text
    u = usage.json()
    assert u["total_requests"] == 2
    assert u["total_cost"] == pytest.approx(0.06, abs=1e-4)

    # Comisión del período actual (rev-share 25% de $0.06 = 1.5 cents → redondeo a cents).
    period = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m")
    calc = await async_client.post(
        f"/api/v1/platform/partners/{partner_id}/commission/calculate",
        headers=plat,
        json={"period": period},
    )
    assert calc.status_code == 200, calc.text
    c = calc.json()
    assert c["status"] == "calculated"
    assert c["revenue"] == pytest.approx(0.06, abs=1e-4)
    assert c["commission"] in (0.01, 0.02)  # cents enteros

    commissions = await async_client.get(
        f"/api/v1/platform/partners/{partner_id}/commissions", headers=plat
    )
    assert commissions.status_code == 200, commissions.text
    assert commissions.json()["commissions"][0]["period"] == period

    # Subtenant.
    target = await _create_org(async_client, "Sub Org")
    sub = await async_client.post(
        f"/api/v1/platform/partners/{partner_id}/subtenants",
        headers=plat,
        json={"organization_id": target["organization_id"], "commission_share_pct": 80},
    )
    assert sub.status_code == 201, sub.text
    subs = await async_client.get(f"/api/v1/platform/partners/{partner_id}/subtenants", headers=plat)
    assert subs.json()["count"] == 1

    # Branding white-label.
    brand = await async_client.put(
        f"/api/v1/platform/partners/{partner_id}/branding",
        headers=plat,
        json={"branding": {"logo_url": "https://cdn.xyz/logo.png", "primary_color": "#7c3aed"}},
    )
    assert brand.status_code == 200, brand.text

    # Status suspend.
    sus = await async_client.post(
        f"/api/v1/platform/partners/{partner_id}/status",
        headers=plat,
        json={"status": "suspended"},
    )
    assert sus.status_code == 200, sus.text


@pytest.mark.asyncio
async def test_partner_context_and_public_query_metering(async_client: AsyncClient) -> None:
    """El middleware propaga partner_id y el public query registra uso del partner."""
    from src.agents.runtime.agent_runtime import AgentRunResult
    from src.api.deps import get_agent_runtime
    from src.api.main import app

    org = await _create_org(async_client, "Partner Flow Org")
    org["session"] = await _owner_session(org["organization_id"])
    h = _headers(org)
    plat = await _platform_admin(async_client, f"padmin-prtf-{uuid4().hex[:8]}@zent.example")

    created = await async_client.post(
        "/api/v1/platform/partners",
        headers=plat,
        json={"organization_id": org["organization_id"], "name": "Flow Partner", "rev_share_pct": 10},
    )
    partner_id = created.json()["id"]
    partner_token = created.json()["api_token"]

    # Deployment para el public query.
    agent = (
        await async_client.post(
            "/api/v1/agents",
            headers={**_headers(org), "Idempotency-Key": f"prt-a-{uuid4().hex}"},
            json={"name": "P Agent", "system_prompt": "t", "model": "gpt-4o-mini", "tools": []},
        )
    ).json()
    version = (
        await async_client.post(f"/api/v1/agents/{agent['id']}/versions", headers=h, json={})
    ).json()
    await async_client.post(
        f"/api/v1/agents/{agent['id']}/versions/{version['id']}/promote",
        headers=h,
        json={"status": "ready"},
    )
    envs = (await async_client.get("/api/v1/environments", headers=h)).json()["environments"]
    prod = next(e for e in envs if e["slug"] == "production")
    dep = (
        await async_client.post(
            "/api/v1/deployments",
            headers={**_headers(org), "Idempotency-Key": f"prt-d-{uuid4().hex}"},
            json={"agent_id": agent["id"], "agent_version_id": version["id"], "environment_id": prod["id"]},
        )
    ).json()

    class _FakeRuntime:
        async def run(self, request):
            return AgentRunResult(
                run_id=uuid4(),
                agent_id=request.agent.id,
                organization_id=request.agent.organization_id,
                status="completed",
                answer="respuesta",
                message=request.message,
                total_latency_ms=5.0,
                total_tokens=10,
                cost=0.0001,
            )

    app.dependency_overrides[get_agent_runtime] = lambda: _FakeRuntime()

    # Query con la key del partner.
    q = await async_client.post(
        f"/api/v1/deployments/{dep['slug']}/query",
        headers={"Authorization": f"Bearer {partner_token}"},
        json={"input": "hola"},
    )
    assert q.status_code == 200, q.text

    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text("SELECT partner_id, cost FROM partner_usage WHERE partner_id = :pid"),
                {"pid": UUID(partner_id)},
            )
        ).fetchall()
    finally:
        await session.close()
    assert len(rows) >= 1
    assert float(rows[0].cost) > 0


@pytest.mark.asyncio
async def test_integrations_catalog(async_client: AsyncClient) -> None:
    plat = await _platform_admin(async_client, f"padmin-prti-{uuid4().hex[:8]}@zent.example")

    listed = await async_client.get("/api/v1/platform/partners/integrations", headers=plat)
    assert listed.status_code == 200, listed.text
    integrations = listed.json()["integrations"]
    assert len(integrations) >= 6  # builtins sembrados
    keys = {i["key"] for i in integrations}
    assert "slack" in keys and "salesforce" in keys and "google_drive" in keys

    added = await async_client.post(
        "/api/v1/platform/partners/integrations",
        headers=plat,
        json={"key": "zendesk", "name": "Zendesk", "category": "support", "description": "Tickets"},
    )
    assert added.status_code == 201, added.text
    listed2 = await async_client.get("/api/v1/platform/partners/integrations", headers=plat)
    assert any(i["key"] == "zendesk" for i in listed2.json()["integrations"])
