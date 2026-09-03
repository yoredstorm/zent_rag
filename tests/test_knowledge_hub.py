# =============================================================================
# AI Knowledge Hub v2 — Auto-Discovery & Curation (PROMPT 46)
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
            "email": f"kh-{uuid4().hex[:8]}@example.com",
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
        "Idempotency-Key": f"kh-{uuid4().hex}",
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
async def test_sources_crud_and_status(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "KH CRUD Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    created = await async_client.post(
        "/api/v1/knowledge-hub/sources",
        headers={**_headers(org), "Idempotency-Key": f"kh-c-{uuid4().hex}"},
        json={"name": "Docs Web", "source_type": "url", "config": {"url": "https://docs.x.dev", "prefix": "Web"}, "refresh_interval_h": 12},
    )
    assert created.status_code == 200, created.text
    sid = created.json()["source_id"]

    detail = await async_client.get(f"/api/v1/knowledge-hub/sources/{sid}", headers=h)
    assert detail.json()["source_type"] == "url"
    assert detail.json()["status"] == "active"

    paused = await async_client.post(f"/api/v1/knowledge-hub/sources/{sid}/pause", headers={**_headers(org)})
    assert paused.json()["status"] == "paused"
    resumed = await async_client.post(f"/api/v1/knowledge-hub/sources/{sid}/resume", headers={**_headers(org)})
    assert resumed.json()["status"] == "active"

    # Tipo inválido → 400.
    bad = await async_client.post(
        "/api/v1/knowledge-hub/sources",
        headers={**_headers(org), "Idempotency-Key": f"kh-b-{uuid4().hex}"},
        json={"name": "Bad", "source_type": "ftp"},
    )
    assert bad.status_code in (400, 422)  # Pydantic pattern → 422

    listed = await async_client.get("/api/v1/knowledge-hub/sources", headers=h)
    assert any(s["id"] == sid for s in listed.json()["sources"])

    deleted = await async_client.delete(f"/api/v1/knowledge-hub/sources/{sid}", headers={**_headers(org)})
    assert deleted.json()["deleted"] is True


@pytest.mark.asyncio
async def test_refresh_ingest_and_deduplication(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "KH Ingest Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    items = [
        {"title": "Manual de soporte", "content": "Guía de troubleshooting de la API"},
        {"title": "Pricing FAQ", "content": "Planes y precios del producto"},
    ]
    created = await async_client.post(
        "/api/v1/knowledge-hub/sources",
        headers={**_headers(org), "Idempotency-Key": f"kh-i-{uuid4().hex}"},
        json={
            "name": "Soporte Docs",
            "source_type": "manual",
            "config": {"items": items, "author": "equipo soporte", "confidence": 95},
        },
    )
    sid = created.json()["source_id"]

    refresh = await async_client.post(f"/api/v1/knowledge-hub/sources/{sid}/refresh", headers={**_headers(org)})
    assert refresh.status_code == 200, refresh.text
    body = refresh.json()
    assert body["status"] == "success"
    assert body["docs_added"] == 2
    assert body["docs_duplicated"] == 0

    # Segundo refresco → duplicados detectados por firma.
    refresh2 = await async_client.post(f"/api/v1/knowledge-hub/sources/{sid}/refresh", headers={**_headers(org)})
    assert refresh2.json()["docs_added"] == 0
    assert refresh2.json()["docs_duplicated"] == 2

    # Metadatos enriquecidos.
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        docs = (
            await session.execute(
                text(
                    "SELECT title, category, author, confidence_score, freshness_score, "
                    "signature, source_id FROM documents WHERE source_id = :sid ORDER BY title"
                ),
                {"sid": UUID(sid)},
            )
        ).fetchall()
    finally:
        await session.close()
    assert len(docs) == 2
    assert docs[0].author == "equipo soporte"
    assert docs[0].confidence_score == 95.0
    assert docs[0].freshness_score == 100.0
    assert len(docs[0].signature) == 64
    assert docs[0].signature != docs[1].signature
    assert any(d.category == "soporte" for d in docs)  # "soporte" en título
    assert any(d.category == "ventas" for d in docs)  # "precios/planes"

    history = await async_client.get(f"/api/v1/knowledge-hub/sources/{sid}/refreshes", headers=h)
    assert len(history.json()["refreshes"]) == 2
    assert history.json()["refreshes"][0]["docs_duplicated"] == 2


@pytest.mark.asyncio
async def test_curation_and_coverage(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "KH Curate Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    from src.platform.knowledgehub.hub import create_source, refresh_source

    source = await create_source(
        UUID(org["organization_id"]), "Docs", "manual",
        {"items": [{"title": "Guía técnica API", "content": "Integración con SDK"}]},
    )
    await refresh_source(UUID(org["organization_id"]), UUID(source["source_id"]))

    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        doc_id = (
            await session.execute(
                text("SELECT id FROM documents WHERE source_id = :sid"),
                {"sid": UUID(source["source_id"])},
            )
        ).scalar()
    finally:
        await session.close()

    curated = await async_client.post(
        f"/api/v1/knowledge-hub/documents/{doc_id}/curate",
        headers={**_headers(org), "Idempotency-Key": f"kh-cu-{uuid4().hex}"},
        json={"category": "técnico", "author": "maria", "confidence": 88.5, "title": "Guía técnica API v2"},
    )
    assert curated.status_code == 200, curated.text

    session = await get_async_session()
    try:
        doc = (
            await session.execute(
                text("SELECT category, author, confidence_score, title FROM documents WHERE id = :did"),
                {"did": doc_id},
            )
        ).fetchone()
    finally:
        await session.close()
    assert doc.category == "técnico"
    assert doc.author == "maria"
    assert doc.confidence_score == 88.5
    assert doc.title == "Guía técnica API v2"

    coverage = await async_client.get("/api/v1/knowledge-hub/coverage", headers=h)
    assert coverage.status_code == 200, coverage.text
    body = coverage.json()
    assert body["total_documents"] == 1
    assert any(s["name"] == "Docs" and s["documents"] == 1 for s in body["sources"])
    assert any(c["category"] == "técnico" and c["documents"] == 1 for c in body["categories"])


@pytest.mark.asyncio
async def test_gaps_detection_and_resolve(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "KH Gaps Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    from src.platform.copilot.copilot import chat

    # Mensajes sin intención → gap.
    await chat(UUID(org["organization_id"]), None, "qué stock tiene el almacén de Buenos Aires?")
    await chat(UUID(org["organization_id"]), None, "qué stock tiene el almacén de Buenos Aires?")

    gaps = await async_client.get("/api/v1/knowledge-hub/gaps", headers=h)
    assert gaps.status_code == 200, gaps.text
    body = gaps.json()
    assert len(body["gaps"]) == 1
    gap = body["gaps"][0]
    assert gap["occurrences"] == 2
    assert gap["status"] == "open"

    resolved = await async_client.post(f"/api/v1/knowledge-hub/gaps/{gap['id']}/resolve", headers={**_headers(org)})
    assert resolved.json()["status"] == "resolved"
    closed = await async_client.get("/api/v1/knowledge-hub/gaps?status=resolved", headers=h)
    assert len(closed.json()["gaps"]) == 1


@pytest.mark.asyncio
async def test_platform_dashboard(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "KH Dash Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    plat = await _platform_admin(async_client, f"padmin-khd-{uuid4().hex[:8]}@zent.example")

    from src.platform.knowledgehub.hub import create_source, refresh_source

    source = await create_source(
        UUID(org["organization_id"]), "Feed RSS", "rss",
        {"items": [{"title": "Post técnico", "content": "Novedades del producto"}]},
    )
    await refresh_source(UUID(org["organization_id"]), UUID(source["source_id"]))
    await refresh_source(UUID(org["organization_id"]), UUID(source["source_id"]))  # duplicados

    dash = await async_client.get("/api/v1/platform/knowledge-hub/dashboard", headers=plat)
    assert dash.status_code == 200, dash.text
    body = dash.json()
    assert body["total_sources"] >= 1
    assert body["total_documents"] >= 1
    assert body["duplicates_removed"] >= 1
    assert any(t["source_type"] == "rss" for t in body["sources_by_type"])
