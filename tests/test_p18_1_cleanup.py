# =============================================================================
# P18.1-10 — Saneamiento no destructivo del Explorador
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.main import app
from src.core.config import get_settings


async def _create_org(client: AsyncClient, name: str) -> dict:
    response = await client.post(
        "/api/v1/billing/subscription/create-trial",
        json={
            "company_name": name,
            "email": f"p181c-{uuid4().hex[:8]}@example.com",
            "country": "CL",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


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


@pytest.fixture
async def async_client():
    from tests.conftest import attach_auto_idempotency

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield attach_auto_idempotency(client)


@pytest.fixture
async def org(async_client: AsyncClient) -> dict:
    org = await _create_org(async_client, "P18.1 Cleanup")
    org["session"] = await _owner_session(org["organization_id"])
    return org


async def _seed_object(org_id: str, name: str) -> UUID:
    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        workspace_id = (
            await session.execute(
                text(
                    "SELECT id FROM workspaces WHERE organization_id = :oid "
                    "ORDER BY created_at ASC LIMIT 1"
                ),
                {"oid": org_id},
            )
        ).scalar_one()
        object_id = uuid4()
        await session.execute(
            text(
                "INSERT INTO knowledge_canonical_objects "
                "(id, organization_id, workspace_id, kind, natural_key, title, name, "
                "display_name, description, provenance, status, confidence, metadata) "
                "VALUES (:id, :oid, :wid, 'concept', :key, :name, :name, :name, "
                "'fragmento de diálogo', 'OBSERVED', 'discovered', 0.7, '{}'::jsonb)"
            ),
            {
                "id": object_id,
                "oid": org_id,
                "wid": workspace_id,
                "key": f"fixture:{name}:{uuid4().hex[:8]}",
                "name": name,
            },
        )
        await session.commit()
        return object_id
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_cleanup_dry_run_then_hide_and_restore(
    async_client, org, monkeypatch
) -> None:
    object_id = await _seed_object(org["organization_id"], "planeta?")
    endpoint = "/api/v1/knowledge/maintenance/explorer-cleanup"

    dry = await async_client.post(
        endpoint,
        headers=_headers(org),
        json={"dry_run": True},
    )
    assert dry.status_code == 200, dry.text
    payload = dry.json()
    assert payload["dry_run"] is True
    assert any(item["id"] == str(object_id) for item in payload["candidates"])
    assert payload["limits"]["deletes"] == 0

    blocked = await async_client.post(
        endpoint,
        headers=_headers(org),
        json={"dry_run": False},
    )
    assert blocked.status_code == 403

    monkeypatch.setattr(
        get_settings(), "KNOWLEDGE_HISTORICAL_CLEANUP_ENABLED", True
    )
    applied = await async_client.post(
        endpoint,
        headers=_headers(org),
        json={"dry_run": False},
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["rollback"]["available"] is True

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        meta = (
            await session.execute(
                text(
                    "SELECT metadata->>'explorer_visibility' FROM "
                    "knowledge_canonical_objects WHERE id = :id"
                ),
                {"id": object_id},
            )
        ).scalar_one()
        assert meta == "hidden"
    finally:
        await session.close()

    restored = await async_client.post(
        endpoint,
        headers=_headers(org),
        json={"dry_run": False, "action": "restore"},
    )
    assert restored.status_code == 200, restored.text

    session = await get_async_session()
    try:
        meta = (
            await session.execute(
                text(
                    "SELECT metadata->>'explorer_visibility' FROM "
                    "knowledge_canonical_objects WHERE id = :id"
                ),
                {"id": object_id},
            )
        ).scalar_one()
        assert meta is None
    finally:
        await session.close()
