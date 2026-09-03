# =============================================================================
# AI Agent Marketplace & Ecosystem v2 (PROMPT 48)
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
            "email": f"eco-{uuid4().hex[:8]}@example.com",
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
        "Idempotency-Key": f"eco-{uuid4().hex}",
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
async def test_publish_lifecycle_and_catalog(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "ECO Publish Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    created = await async_client.post(
        "/api/v1/marketplace/listings",
        headers={**_headers(org), "Idempotency-Key": f"eco-l-{uuid4().hex}"},
        json={
            "name": "Bot de Ventas Pro",
            "description": "Califica leads y cierra ventas",
            "category": "sales",
            "pricing_type": "one_time",
            "price_cents": 4900,
            "config_template": {"model": "gpt-4o", "max_tokens": 2000},
            "prompt_template": "Eres el asistente de ventas de {company}.",
        },
    )
    assert created.status_code == 200, created.text
    lid = created.json()["listing_id"]

    # Borrador no aparece en el catálogo.
    catalog = await async_client.get("/api/v1/marketplace", headers=h)
    assert all(it["id"] != lid for it in catalog.json()["listings"])

    published = await async_client.post(f"/api/v1/marketplace/{lid}/publish", headers={**_headers(org)})
    assert published.json()["status"] == "published"

    catalog2 = await async_client.get("/api/v1/marketplace?category=sales", headers=h)
    entry = next(it for it in catalog2.json()["listings"] if it["id"] == lid)
    assert entry["price_cents"] == 4900
    assert entry["version"] == "1.0.0"

    # Versión nueva.
    ver = await async_client.post(
        f"/api/v1/marketplace/{lid}/versions",
        headers={**_headers(org), "Idempotency-Key": f"eco-v-{uuid4().hex}"},
        json={"version": "2.0.0", "changelog": "mejor prompt"},
    )
    assert ver.status_code == 200, ver.text
    detail = await async_client.get(f"/api/v1/marketplace/{lid}", headers=h)
    assert detail.json()["version"] == "2.0.0"
    assert len(detail.json()["versions"]) == 2

    # Search.
    catalog3 = await async_client.get("/api/v1/marketplace?search=ventas", headers=h)
    assert any(it["id"] == lid for it in catalog3.json()["listings"])

    # Despublicar → oculto.
    await async_client.post(f"/api/v1/marketplace/{lid}/unpublish", headers={**_headers(org)})
    catalog4 = await async_client.get("/api/v1/marketplace", headers=h)
    assert all(it["id"] != lid for it in catalog4.json()["listings"])

    mine = await async_client.get("/api/v1/marketplace/my/listings", headers=h)
    assert any(it["id"] == lid and it["status"] == "unpublished" for it in mine.json()["listings"])


@pytest.mark.asyncio
async def test_reviews_verified_and_rating(async_client: AsyncClient) -> None:
    publisher = await _create_org(async_client, "ECO Publisher Org")
    publisher["session"] = await _owner_session(async_client, publisher["organization_id"])
    buyer = await _create_org(async_client, "ECO Buyer Org")
    buyer["session"] = await _owner_session(async_client, buyer["organization_id"])

    from src.platform.marketplacev2.ecosystem import create_listing, set_listing_status

    listing = await create_listing(UUID(publisher["organization_id"]), "Agente FAQ", "responder dudas", "support", "free", 0)
    lid = UUID(listing["listing_id"])
    await set_listing_status(UUID(publisher["organization_id"]), lid, "published")

    # Review sin compra → no verificada.
    r1 = await async_client.post(
        f"/api/v1/marketplace/{lid}/reviews",
        headers={**_headers(buyer), "Idempotency-Key": f"eco-r-{uuid4().hex}"},
        json={"rating": 4, "comment": "bueno"},
    )
    assert r1.status_code == 200, r1.text
    assert r1.json()["verified"] is False

    # Compra → review verificada (upsert).
    purchased = await async_client.post(f"/api/v1/marketplace/{lid}/purchase", headers={**_headers(buyer)})
    assert purchased.status_code == 200, purchased.text
    assert purchased.json()["purchased"] is True

    r2 = await async_client.post(
        f"/api/v1/marketplace/{lid}/reviews",
        headers={**_headers(buyer), "Idempotency-Key": f"eco-r2-{uuid4().hex}"},
        json={"rating": 5, "comment": "excelente"},
    )
    assert r2.json()["verified"] is True

    reviews = await async_client.get(f"/api/v1/marketplace/{lid}/reviews", headers={**_headers(buyer)})
    assert len(reviews.json()["reviews"]) == 1  # upsert por org
    assert reviews.json()["reviews"][0]["verified"] is True

    detail = await async_client.get(f"/api/v1/marketplace/{lid}", headers={**_headers(buyer)})
    assert detail.json()["rating"] == 5.0
    assert detail.json()["reviews_count"] == 1


@pytest.mark.asyncio
async def test_purchase_revenue_sharing_and_install(async_client: AsyncClient) -> None:
    publisher = await _create_org(async_client, "ECO Rev Org")
    publisher["session"] = await _owner_session(async_client, publisher["organization_id"])
    buyer = await _create_org(async_client, "ECO Buyer2 Org")
    buyer["session"] = await _owner_session(async_client, buyer["organization_id"])

    from src.platform.marketplacev2.ecosystem import create_listing, set_listing_status

    listing = await create_listing(
        UUID(publisher["organization_id"]), "AutoBot", "automatiza",
        "operations", "one_time", 10000,
        {"model": "gpt-4o-mini"}, "Eres AutoBot de {company}.",
    )
    lid = UUID(listing["listing_id"])
    await set_listing_status(UUID(publisher["organization_id"]), lid, "published")

    purchased = await async_client.post(f"/api/v1/marketplace/{lid}/purchase", headers={**_headers(buyer)})
    assert purchased.status_code == 200, purchased.text
    body = purchased.json()
    assert body["price_cents"] == 10000
    assert body["platform_fee_cents"] == 2000  # 20%
    assert body["publisher_payout_cents"] == 8000

    # El agente se instaló en el tenant comprador.
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        agent = (
            await session.execute(
                text(
                    "SELECT name, config_json FROM agents "
                    "WHERE organization_id = :oid AND name = 'AutoBot (marketplace)'"
                ),
                {"oid": UUID(buyer["organization_id"])},
            )
        ).fetchone()
        installs = (
            await session.execute(
                text("SELECT installs FROM public_listings WHERE id = :lid"),
                {"lid": lid},
            )
        ).scalar()
    finally:
        await session.close()
    assert agent is not None
    assert agent.config_json.get("marketplace_listing") == str(lid)
    assert int(installs) == 1

    # Compra duplicada → rechazada.
    dup = await async_client.post(f"/api/v1/marketplace/{lid}/purchase", headers={**_headers(buyer)})
    assert dup.json()["purchased"] is False

    purchases = await async_client.get("/api/v1/marketplace/my/purchases", headers={**_headers(buyer)})
    assert len(purchases.json()["purchases"]) == 1
    assert purchases.json()["purchases"][0]["publisher_payout_cents"] == 8000


@pytest.mark.asyncio
async def test_payouts_and_partner_badges(async_client: AsyncClient) -> None:
    publisher = await _create_org(async_client, "ECO Payout Org")
    publisher["session"] = await _owner_session(async_client, publisher["organization_id"])
    buyer = await _create_org(async_client, "ECO Buyer3 Org")
    buyer["session"] = await _owner_session(async_client, buyer["organization_id"])

    from src.platform.marketplacev2.ecosystem import (
        create_listing,
        generate_payouts,
        purchase,
        set_listing_status,
    )

    listing = await create_listing(UUID(publisher["organization_id"]), "Bot Pago", "x", "engineering", "one_time", 5000)
    lid = UUID(listing["listing_id"])
    await set_listing_status(UUID(publisher["organization_id"]), lid, "published")
    await purchase(UUID(buyer["organization_id"]), lid)

    result = await generate_payouts()
    mine_payout = next(
        (p for p in result["payouts"] if p["publisher_org_id"] == str(UUID(publisher["organization_id"]))),
        None,
    )
    assert mine_payout is not None
    assert mine_payout["amount_cents"] == 4000  # 5000 - 20%

    payouts = await async_client.get("/api/v1/marketplace/my/payouts", headers={**_headers(publisher)})
    assert payouts.status_code == 200, payouts.text
    assert payouts.json()["payouts"][0]["amount_cents"] == 4000
    assert payouts.json()["payouts"][0]["status"] == "pending"

    # Badge de partner.
    badge0 = await async_client.get("/api/v1/marketplace/partner/badges", headers={**_headers(publisher)})
    assert badge0.json()["badge"] is None

    applied = await async_client.post(
        "/api/v1/marketplace/partner/apply",
        headers={**_headers(publisher), "Idempotency-Key": f"eco-pa-{uuid4().hex}"},
        json={"level": "premier"},
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["badge"] == "premier"

    badge1 = await async_client.get("/api/v1/marketplace/partner/badges", headers={**_headers(publisher)})
    assert badge1.json()["badge"] == "premier"


@pytest.mark.asyncio
async def test_ecosystem_dashboard(async_client: AsyncClient) -> None:
    publisher = await _create_org(async_client, "ECO Dash Org")
    publisher["session"] = await _owner_session(async_client, publisher["organization_id"])
    buyer = await _create_org(async_client, "ECO Buyer4 Org")
    buyer["session"] = await _owner_session(async_client, buyer["organization_id"])
    plat = await _platform_admin(async_client, f"padmin-eco-{uuid4().hex[:8]}@zent.example")

    from src.platform.marketplacev2.ecosystem import (
        apply_partner,
        create_listing,
        purchase,
        set_listing_status,
    )

    listing = await create_listing(UUID(publisher["organization_id"]), "Bot Dash", "dash", "analytics", "one_time", 3000)
    lid = UUID(listing["listing_id"])
    await set_listing_status(UUID(publisher["organization_id"]), lid, "published")
    await purchase(UUID(buyer["organization_id"]), lid)
    await apply_partner(UUID(publisher["organization_id"]), "partner")

    dash = await async_client.get("/api/v1/platform/ecosystem/dashboard", headers=plat)
    assert dash.status_code == 200, dash.text
    body = dash.json()
    assert body["listings_total"] >= 1
    assert body["listings_published"] >= 1
    assert body["total_installs"] >= 1
    assert body["gmv_cents"] >= 3000
    assert body["platform_fees_cents"] >= 600
    assert body["orders_count"] >= 1
    assert any(c["category"] == "analytics" for c in body["by_category"])

    # Badge verificado directamente en el tenant del publicador.
    badges = await async_client.get("/api/v1/marketplace/partner/badges", headers={**_headers(publisher)})
    assert badges.json()["badge"] == "partner"
