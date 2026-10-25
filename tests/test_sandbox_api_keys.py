from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from src.infrastructure.postgres.session import get_async_session
from src.platform.auth.scopes import api_key_environment_allows
from tests.test_workflows import _create_org, _headers, _owner_session


def test_development_key_cannot_reach_production_deployment() -> None:
    assert api_key_environment_allows("test", "staging") is True
    assert api_key_environment_allows("test", "development") is True
    assert api_key_environment_allows("test", "production") is False
    assert api_key_environment_allows("live", "production") is True


@pytest.mark.asyncio
async def test_development_api_key_expires_in_one_day(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Sandbox Keys")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    created = await async_client.post(
        "/api/v1/organizations/api-keys",
        headers=_headers(org),
        json={
            "name": f"dev-{uuid4().hex[:8]}",
            "scopes": ["rag:query"],
            "environment": "test",
        },
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["token"].startswith("zent_sk_test_")
    assert body["environment"] == "test"
    assert body["expires_at"]
    expires = datetime.fromisoformat(body["expires_at"])
    remaining = (expires - datetime.now(timezone.utc)).total_seconds()
    assert 23 * 3600 <= remaining <= 25 * 3600
    assert "expire after 1 day" in body["message"]

    listed = await async_client.get(
        "/api/v1/organizations/api-keys", headers=_headers(org)
    )
    assert listed.status_code == 200, listed.text
    row = next(item for item in listed.json()["keys"] if item["id"] == body["key_id"])
    assert row["environment"] == "test"
    assert row["expires_at"] == body["expires_at"]


@pytest.mark.asyncio
async def test_expired_development_key_is_rejected(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Expired Sandbox Key")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    created = await async_client.post(
        "/api/v1/organizations/api-keys",
        headers=_headers(org),
        json={
            "name": f"exp-{uuid4().hex[:8]}",
            "scopes": ["rag:query"],
            "environment": "test",
        },
    )
    assert created.status_code == 200, created.text
    body = created.json()
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE api_keys SET expires_at = NOW() - interval '1 minute' "
                "WHERE id = :kid AND organization_id = :oid"
            ),
            {"kid": body["key_id"], "oid": org["organization_id"]},
        )
        await session.commit()
    finally:
        await session.close()

    response = await async_client.post(
        "/api/v1/rag/query",
        headers={
            "Authorization": f"Bearer {body['token']}",
            "X-Organization-Id": org["organization_id"],
        },
        json={"query": "hola"},
    )
    assert response.status_code == 401, response.text
