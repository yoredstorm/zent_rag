# =============================================================================
# Marketplace & Sharing (PROMPT 16)
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
            "email": f"mkt-{uuid4().hex[:8]}@example.com",
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
        "Idempotency-Key": f"mkt-{uuid4().hex}",
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


async def _create_agent(client: AsyncClient, org: dict, name: str) -> dict:
    resp = await client.post(
        "/api/v1/agents",
        headers={**_headers(org), "Idempotency-Key": f"ag-{uuid4().hex}"},
        json={
            "name": name,
            "description": f"Desc de {name}",
            "system_prompt": f"Eres {name}.",
            "model": "gpt-4o-mini",
            "tools": ["web_search"],
            "config": {"temperature": 0.3},
        },
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_marketplace_publish_install_and_clone(async_client: AsyncClient) -> None:
    org_a = await _create_org(async_client, "Mkt Publisher")
    org_a["session"] = await _owner_session(org_a["organization_id"])
    org_b = await _create_org(async_client, "Mkt Installer")
    org_b["session"] = await _owner_session(org_b["organization_id"])
    plat = await _platform_admin(async_client, f"padmin-mkt-{uuid4().hex[:8]}@zent.example")

    agent = await _create_agent(async_client, org_a, "Agente Marketplace")

    # Publicar.
    pub = await async_client.post(
        "/api/v1/platform/marketplace/listings",
        headers=plat,
        json={
            "organization_id": org_a["organization_id"],
            "agent_id": agent["id"],
            "name": "Agente Marketplace",
            "description": "Snap del agente",
            "category": "sales",
            "tags": ["ventas", "demo"],
        },
    )
    assert pub.status_code == 201, pub.text
    listing_id = pub.json()["listing"]["id"]

    # Listar + detalle con snapshot.
    listed = await async_client.get("/api/v1/platform/marketplace/listings", headers=plat)
    assert listed.status_code == 200, listed.text
    assert any(x["id"] == listing_id for x in listed.json()["listings"])
    detail = await async_client.get(
        f"/api/v1/platform/marketplace/listings/{listing_id}", headers=plat
    )
    assert detail.status_code == 200, detail.text
    snap = detail.json()["agent_snapshot"]
    assert snap["system_prompt"] == "Eres Agente Marketplace."
    assert snap["tools"] == ["web_search"]

    # Reviews: 5 (org_b) + 3 (org_a dueño? otro org) → avg 4.0.
    org_c = await _create_org(async_client, "Mkt Reviewer")
    org_c["session"] = await _owner_session(org_c["organization_id"])
    r1 = await async_client.post(
        f"/api/v1/platform/marketplace/listings/{listing_id}/reviews",
        headers=plat,
        json={"organization_id": org_b["organization_id"], "rating": 5, "comment": "Excelente"},
    )
    assert r1.status_code == 200, r1.text
    r2 = await async_client.post(
        f"/api/v1/platform/marketplace/listings/{listing_id}/reviews",
        headers=plat,
        json={"organization_id": org_c["organization_id"], "rating": 3, "comment": "OK"},
    )
    assert r2.status_code == 200, r2.text
    dup = await async_client.post(
        f"/api/v1/platform/marketplace/listings/{listing_id}/reviews",
        headers=plat,
        json={"organization_id": org_b["organization_id"], "rating": 1},
    )
    assert dup.json()["status"] == "already_reviewed"

    detail2 = await async_client.get(
        f"/api/v1/platform/marketplace/listings/{listing_id}", headers=plat
    )
    assert detail2.json()["rating_avg"] == pytest.approx(4.0, abs=0.01)
    assert detail2.json()["rating_count"] == 2

    # Instalar en org_b → agente clonado con snapshot.
    inst = await async_client.post(
        f"/api/v1/platform/marketplace/listings/{listing_id}/install",
        headers=plat,
        json={"organization_id": org_b["organization_id"]},
    )
    assert inst.status_code == 200, inst.text
    assert inst.json()["status"] == "installed"
    cloned_id = inst.json()["agent_id"]

    agents_b = await async_client.get(
        f"/api/v1/platform/organizations/{org_b['organization_id']}/agents", headers=plat
    )
    cloned = next(a for a in agents_b.json()["agents"] if a["id"] == cloned_id)
    assert cloned["name"] == "Agente Marketplace (mkt)"
    assert cloned["model"] == "gpt-4o-mini"

    detail3 = await async_client.get(
        f"/api/v1/platform/marketplace/listings/{listing_id}", headers=plat
    )
    assert detail3.json()["installs"] == 1

    # Clone in-org (tenant).
    clone = await async_client.post(
        f"/api/v1/agents/{agent['id']}/clone", headers=_headers(org_a), json={}
    )
    assert clone.status_code == 200, clone.text
    assert clone.json()["status"] == "cloned"
    assert clone.json()["agent_id"] != agent["id"]


@pytest.mark.asyncio
async def test_share_links_public_flow(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Mkt Share Org")
    org["session"] = await _owner_session(org["organization_id"])
    h = _headers(org)
    agent = await _create_agent(async_client, org, "Agente Compartido")

    link = await async_client.post(
        f"/api/v1/agents/{agent['id']}/share",
        headers=h,
        json={"expires_days": 7, "max_uses": 2},
    )
    assert link.status_code == 200, link.text
    body = link.json()
    assert body["status"] == "created"
    token = body["token"]

    # Público (sin auth): devuelve el agente.
    shared = await async_client.get(f"/api/v1/share/agents/{token}")
    assert shared.status_code == 200, shared.text
    assert shared.json()["name"] == "Agente Compartido"
    assert shared.json()["system_prompt"] == "Eres Agente Compartido."

    # Listar links.
    links = await async_client.get(f"/api/v1/agents/{agent['id']}/share-links", headers=h)
    assert links.status_code == 200, links.text
    assert links.json()["count"] == 1

    # max_uses=2: dos consultas OK, la tercera 404.
    second = await async_client.get(f"/api/v1/share/agents/{token}")
    assert second.status_code == 200
    third = await async_client.get(f"/api/v1/share/agents/{token}")
    assert third.status_code == 404

    # Revocar → 404 tras revoke (nuevo link).
    link2 = await async_client.post(
        f"/api/v1/agents/{agent['id']}/share", headers=_headers(org), json={}
    )
    token2 = link2.json()["token"]
    link_id2 = link2.json()["link_id"]
    revoked = await async_client.delete(
        f"/api/v1/agents/{agent['id']}/share-links/{link_id2}", headers=h
    )
    assert revoked.status_code == 200, revoked.text
    gone = await async_client.get(f"/api/v1/share/agents/{token2}")
    assert gone.status_code == 404

    # Token inexistente.
    bad = await async_client.get("/api/v1/share/agents/token-que-no-existe")
    assert bad.status_code == 404


@pytest.mark.asyncio
async def test_prompt_templates_repo(async_client: AsyncClient) -> None:
    plat = await _platform_admin(async_client, f"padmin-tpl-{uuid4().hex[:8]}@zent.example")

    listed = await async_client.get("/api/v1/platform/marketplace/templates", headers=plat)
    assert listed.status_code == 200, listed.text
    templates = listed.json()["templates"]
    assert len(templates) >= 4  # builtins sembrados
    builtins = [t for t in templates if t["is_builtin"]]
    assert len(builtins) >= 4
    categories = {t["category"] for t in templates}
    assert "support" in categories and "sales" in categories

    created = await async_client.post(
        "/api/v1/platform/marketplace/templates",
        headers=plat,
        json={
            "name": "Legal QA",
            "category": "legal",
            "description": "Prompt legal",
            "content": "Eres un abogado…",
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["is_builtin"] is False

    # Filtrar por categoría.
    legal = await async_client.get(
        "/api/v1/platform/marketplace/templates?category=legal", headers=plat
    )
    assert legal.status_code == 200, legal.text
    assert any(t["name"] == "Legal QA" for t in legal.json()["templates"])

    # Actualizar + eliminar (los builtin no se borran).
    tpl_id = created.json()["id"]
    updated = await async_client.put(
        f"/api/v1/platform/marketplace/templates/{tpl_id}",
        headers=plat,
        json={"name": "Legal QA v2", "category": "legal", "description": "x", "content": "Nuevo contenido"},
    )
    assert updated.status_code == 200, updated.text
    deleted = await async_client.delete(
        f"/api/v1/platform/marketplace/templates/{tpl_id}", headers=plat
    )
    assert deleted.status_code == 200, deleted.text

    builtin_id = builtins[0]["id"]
    blocked = await async_client.delete(
        f"/api/v1/platform/marketplace/templates/{builtin_id}", headers=plat
    )
    assert blocked.status_code == 404  # builtin no se borra
