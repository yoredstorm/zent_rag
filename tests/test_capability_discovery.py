from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.test_workflows import _create_org, _headers, _owner_session


@pytest.mark.asyncio
async def test_capability_discovery_uses_the_single_catalog(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "P10 Discovery")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    found = await async_client.get(
        "/api/v1/workflows/capabilities/discover?q=demo.echo", headers=h
    )
    assert found.status_code == 200, found.text
    body = found.json()
    assert body["duplicate_catalog"] is False
    assert body["source"] == "canvas_context"
    echo = next(item for item in body["items"] if item["action_id"] == "demo.echo")
    assert echo["installed"] is False
    assert echo["marketplace_required"] is True
    assert echo["integration_slug"] == "demo-echo"

    installed = await async_client.post(
        "/api/v1/workflows/marketplace/install",
        headers={**h, "Idempotency-Key": f"p10-{uuid4().hex}"},
        json={"integration_slug": "demo-echo"},
    )
    assert installed.status_code == 200, installed.text
    install_id = installed.json()["install_id"]

    after = await async_client.get(
        "/api/v1/workflows/capabilities/discover?q=demo.echo", headers=h
    )
    assert after.status_code == 200, after.text
    rows = [item for item in after.json()["items"] if item["action_id"] == "demo.echo"]
    assert rows
    assert rows[0]["installed"] is True
    assert rows[0]["install_id"] == install_id
    assert rows[0]["marketplace_required"] is False


@pytest.mark.asyncio
async def test_discovery_is_bounded_and_empty_query_is_safe(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "P10 Discovery Bounds")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)
    response = await async_client.get(
        "/api/v1/workflows/capabilities/discover?q=no-such-capability-xyz&limit=500",
        headers=h,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["items"] == []
    assert body["limit"] == 200
