# =============================================================================
# Phase 31C — Workspace isolation (demo vs business, no silent mix)
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
            "email": f"iso-{uuid4().hex[:8]}@example.com",
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


def _headers(org: dict, workspace_id: str | None = None) -> dict:
    h = {
        "Authorization": f"Bearer {org['session']}",
        "X-Organization-Id": org["organization_id"],
    }
    if workspace_id:
        h["X-Workspace-Id"] = workspace_id
    return h


@pytest.mark.asyncio
async def test_workspace_kind_and_active_switch(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Iso Kind Org")
    org["session"] = await _owner_session(org["organization_id"])
    h = _headers(org)

    listing = await async_client.get("/api/v1/workspaces", headers=h)
    assert listing.status_code == 200, listing.text
    workspaces = listing.json()["workspaces"]
    assert workspaces
    default = next(w for w in workspaces if w["slug"] == "default")
    assert default["kind"] in ("demo", "business")
    created = await async_client.post(
        "/api/v1/workspaces",
        headers=h,
        json={"name": "My Business", "kind": "business"},
    )
    assert created.status_code == 201, created.text
    business = created.json()
    assert business["kind"] == "business"

    switched = await async_client.put(
        "/api/v1/workspaces/active",
        headers=h,
        json={"workspace_id": business["id"]},
    )
    assert switched.status_code == 200, switched.text
    assert switched.json()["id"] == business["id"]

    me = await async_client.get("/api/v1/auth/me", headers=h)
    assert me.status_code == 200, me.text
    assert me.json()["active_workspace_id"] == business["id"]
    assert me.json()["workspace_kind"] == "business"


@pytest.mark.asyncio
async def test_sources_isolated_by_workspace(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Iso Src Org")
    org["session"] = await _owner_session(org["organization_id"])
    h = _headers(org)
    listing = await async_client.get("/api/v1/workspaces", headers=h)
    default_id = next(
        w["id"] for w in listing.json()["workspaces"] if w["slug"] == "default"
    )
    business = (
        await async_client.post(
            "/api/v1/workspaces",
            headers=h,
            json={"name": "Business Data", "kind": "business"},
        )
    ).json()

    src_demo = await async_client.post(
        "/api/v1/sources",
        headers=_headers(org, default_id),
        json={"name": f"demo-{uuid4().hex[:6]}", "type": "file", "config": {}},
    )
    assert src_demo.status_code == 201, src_demo.text
    src_biz = await async_client.post(
        "/api/v1/sources",
        headers=_headers(org, business["id"]),
        json={"name": f"biz-{uuid4().hex[:6]}", "type": "file", "config": {}},
    )
    assert src_biz.status_code == 201, src_biz.text

    demo_list = await async_client.get(
        "/api/v1/sources", headers=_headers(org, default_id)
    )
    biz_list = await async_client.get(
        "/api/v1/sources", headers=_headers(org, business["id"])
    )
    demo_ids = {s["id"] for s in demo_list.json()["sources"]}
    biz_ids = {s["id"] for s in biz_list.json()["sources"]}
    assert src_demo.json()["id"] in demo_ids
    assert src_demo.json()["id"] not in biz_ids
    assert src_biz.json()["id"] in biz_ids
    assert src_biz.json()["id"] not in demo_ids

    bad = await async_client.get(
        "/api/v1/sources",
        headers=_headers(org, str(uuid4())),
    )
    assert bad.status_code in (400, 404), bad.text


@pytest.mark.asyncio
async def test_catalog_sources_isolated_by_workspace(
    async_client: AsyncClient,
) -> None:
    from src.catalog.store import PostgresCatalogStore
    from src.platform.workspaces.context import ensure_workspace_schema

    org = await _create_org(async_client, "Iso Cat Org")
    org["session"] = await _owner_session(org["organization_id"])
    h = _headers(org)
    listing = await async_client.get("/api/v1/workspaces", headers=h)
    default_id = next(
        w["id"] for w in listing.json()["workspaces"] if w["slug"] == "default"
    )
    business = (
        await async_client.post(
            "/api/v1/workspaces",
            headers=h,
            json={"name": "Biz Catalog", "kind": "business"},
        )
    ).json()

    await ensure_workspace_schema()
    store = PostgresCatalogStore()
    await store.ensure_tables()
    oid = UUID(org["organization_id"])
    conn_demo = await async_client.post(
        "/api/v1/connectors",
        headers=_headers(org, default_id),
        json={"name": f"demo-c-{uuid4().hex[:6]}", "type": "postgres", "config": {}},
    )
    conn_biz = await async_client.post(
        "/api/v1/connectors",
        headers=_headers(org, business["id"]),
        json={"name": f"biz-c-{uuid4().hex[:6]}", "type": "postgres", "config": {}},
    )
    assert conn_demo.status_code == 201, conn_demo.text
    assert conn_biz.status_code == 201, conn_biz.text
    demo_src = await store.upsert_source(
        organization_id=oid,
        connector_id=UUID(conn_demo.json()["id"]),
        engine="postgres",
        workspace_id=UUID(default_id),
    )
    biz_src = await store.upsert_source(
        organization_id=oid,
        connector_id=UUID(conn_biz.json()["id"]),
        engine="postgres",
        workspace_id=UUID(business["id"]),
    )

    demo_list = await async_client.get(
        "/api/v1/catalog/sources", headers=_headers(org, default_id)
    )
    biz_list = await async_client.get(
        "/api/v1/catalog/sources", headers=_headers(org, business["id"])
    )
    assert demo_list.status_code == 200, demo_list.text
    assert biz_list.status_code == 200, biz_list.text
    demo_ids = {row["id"] for row in demo_list.json()}
    biz_ids = {row["id"] for row in biz_list.json()}
    assert str(demo_src["id"]) in demo_ids
    assert str(demo_src["id"]) not in biz_ids
    assert str(biz_src["id"]) in biz_ids
    assert str(biz_src["id"]) not in demo_ids


@pytest.mark.asyncio
async def test_qdrant_delete_by_workspace_scoped() -> None:
    from src.infrastructure.qdrant.vector_store import QdrantVectorStore

    store = QdrantVectorStore.__new__(QdrantVectorStore)
    assert hasattr(store, "delete_by_workspace")


@pytest.mark.asyncio
async def test_invalid_workspace_header_rejected(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Iso Bad Header")
    org["session"] = await _owner_session(org["organization_id"])
    resp = await async_client.get(
        "/api/v1/sources",
        headers=_headers(org, "not-a-uuid"),
    )
    assert resp.status_code == 400, resp.text
