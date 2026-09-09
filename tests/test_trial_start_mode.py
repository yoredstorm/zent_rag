# =============================================================================
# Trial start mode — signup leaves no workspace; demo vs blank on demand
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from src.infrastructure.postgres.relational_db import PostgresWorkspaceRepository


async def _signup(client: AsyncClient) -> dict:
    email = f"start_{uuid4().hex[:10]}@example.com"
    resp = await client.post(
        "/api/v1/auth/signup",
        json={
            "company_name": "Start Mode Co",
            "email": email,
            "password": "secure-pass-123",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    data["email"] = email
    return data


def _headers(signup: dict) -> dict:
    return {
        "Authorization": f"Bearer {signup['access_token']}",
        "X-Organization-Id": signup["organization_id"],
    }


async def choose_start_mode(
    client: AsyncClient, signup: dict, mode: str
) -> dict:
    resp = await client.post(
        "/api/v1/onboarding/start-mode",
        json={"mode": mode},
        headers=_headers(signup),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_signup_creates_no_workspace(async_client: AsyncClient) -> None:
    signup = await _signup(async_client)
    workspaces = await PostgresWorkspaceRepository().list_workspaces(
        UUID(signup["organization_id"])
    )
    assert workspaces == []

    me = await async_client.get("/api/v1/auth/me", headers=_headers(signup))
    assert me.status_code == 200, me.text
    body = me.json()
    assert body["needs_start_mode"] is True
    assert body["active_workspace_id"] is None
    assert body["workspace_kind"] is None

    listed = await async_client.get("/api/v1/workspaces", headers=_headers(signup))
    assert listed.status_code == 200, listed.text
    assert listed.json()["workspaces"] == []
    assert listed.json()["active_workspace_id"] is None


@pytest.mark.asyncio
async def test_resolve_workspace_requires_start_mode(
    async_client: AsyncClient,
) -> None:
    signup = await _signup(async_client)
    created = await async_client.post(
        "/api/v1/sources",
        json={"name": "blocked", "type": "web", "config": {"url": "https://x.example"}},
        headers=_headers(signup),
    )
    assert created.status_code == 409, created.text
    assert created.json()["error_code"] == "start_mode_required"


@pytest.mark.asyncio
async def test_start_mode_demo_creates_demo_workspace(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    called: dict[str, object] = {}

    async def _fake_provision(organization_id, workspace_id=None):
        called["org"] = organization_id
        called["workspace_id"] = workspace_id
        return True

    monkeypatch.setattr(
        "src.verticals.demo_farmacia.provisioning.provision_demo_kb",
        _fake_provision,
    )

    signup = await _signup(async_client)
    result = await choose_start_mode(async_client, signup, "demo")
    assert result["kind"] == "demo"
    assert result["needs_start_mode"] is False
    assert called["org"] == UUID(signup["organization_id"])
    assert called["workspace_id"] == UUID(result["workspace_id"])

    me = await async_client.get("/api/v1/auth/me", headers=_headers(signup))
    assert me.json()["needs_start_mode"] is False
    assert me.json()["workspace_kind"] == "demo"
    assert me.json()["active_workspace_id"] == result["workspace_id"]


@pytest.mark.asyncio
async def test_start_mode_blank_creates_business_without_provision(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _must_not_run(*_args, **_kwargs):
        raise AssertionError("provision_demo_kb must not run for blank")

    monkeypatch.setattr(
        "src.verticals.demo_farmacia.provisioning.provision_demo_kb",
        _must_not_run,
    )

    signup = await _signup(async_client)
    result = await choose_start_mode(async_client, signup, "blank")
    assert result["kind"] == "business"
    assert result["needs_start_mode"] is False

    me = await async_client.get("/api/v1/auth/me", headers=_headers(signup))
    assert me.json()["needs_start_mode"] is False
    assert me.json()["workspace_kind"] == "business"


@pytest.mark.asyncio
async def test_start_mode_is_idempotent(async_client: AsyncClient) -> None:
    signup = await _signup(async_client)
    first = await choose_start_mode(async_client, signup, "blank")
    second = await choose_start_mode(async_client, signup, "demo")
    assert second["workspace_id"] == first["workspace_id"]
    assert second["kind"] == "business"
