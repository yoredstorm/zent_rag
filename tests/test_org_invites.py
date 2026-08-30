# =============================================================================
# Organization invites — create / list / accept + isolation + plan limits
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text


async def _create_org(client: AsyncClient, name: str) -> dict:
    response = await client.post(
        "/api/v1/billing/subscription/create-trial",
        json={
            "company_name": name,
            "email": f"inv-{uuid4().hex[:8]}@example.com",
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


def _error_code(response) -> str:
    body = response.json()
    detail = body.get("detail")
    if isinstance(detail, dict):
        return str(detail.get("error_code") or "")
    return str(body.get("error_code") or "")


@pytest.mark.asyncio
async def test_owner_creates_invite_once(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Invite Org")
    org["session"] = await _owner_session(org["organization_id"])
    email = f"guest-{uuid4().hex[:8]}@example.com"

    created = await async_client.post(
        "/api/v1/organizations/invites",
        json={"email": email, "role": "member"},
        headers=_headers(org),
    )
    assert created.status_code == 201, created.text
    data = created.json()
    assert data["email"] == email
    assert data["role"] == "member"
    assert data["status"] == "pending"
    assert "token" in data and data["token"]
    assert "expires_at" in data

    listed = await async_client.get(
        "/api/v1/organizations/invites", headers=_headers(org)
    )
    assert listed.status_code == 200, listed.text
    emails = [row["email"] for row in listed.json()["invites"]]
    assert email in emails
    assert all("token" not in row for row in listed.json()["invites"])

    audit = await async_client.get("/api/v1/audit-logs", headers=_headers(org))
    assert audit.status_code == 200, audit.text
    assert "invite.created" in {e["action"] for e in audit.json()["entries"]}

    duplicate = await async_client.post(
        "/api/v1/organizations/invites",
        json={"email": email.upper(), "role": "viewer"},
        headers=_headers(org),
    )
    assert duplicate.status_code == 409, duplicate.text


@pytest.mark.asyncio
async def test_invite_accept_does_not_leak_other_org_data(
    async_client: AsyncClient,
) -> None:
    host = await _create_org(async_client, "Host Org")
    host["session"] = await _owner_session(host["organization_id"])

    guest_email = f"guest-{uuid4().hex[:8]}@example.com"
    guest_password = "invite-pass-9"
    signup = await async_client.post(
        "/api/v1/auth/signup",
        json={
            "company_name": "Guest Co",
            "email": guest_email,
            "password": guest_password,
        },
    )
    assert signup.status_code == 200, signup.text
    guest = signup.json()
    guest_headers = {
        "Authorization": f"Bearer {guest['access_token']}",
        "X-Organization-Id": guest["organization_id"],
    }

    secret = await async_client.post(
        "/api/v1/sources",
        json={"name": "guest-only", "type": "web", "config": {"url": "https://guest.example"}},
        headers=guest_headers,
    )
    assert secret.status_code == 201, secret.text

    invited = await async_client.post(
        "/api/v1/organizations/invites",
        json={"email": guest_email, "role": "member"},
        headers=_headers(host),
    )
    assert invited.status_code == 201, invited.text
    invite = invited.json()

    accepted = await async_client.post(
        f"/api/v1/organizations/invites/{invite['id']}/accept",
        json={"token": invite["token"]},
        headers=guest_headers,
    )
    assert accepted.status_code == 200, accepted.text
    body = accepted.json()
    assert body["organization_id"] == host["organization_id"]
    assert body["status"] == "accepted"
    assert "access_token" in body

    host_session_headers = {
        "Authorization": f"Bearer {body['access_token']}",
        "X-Organization-Id": host["organization_id"],
    }
    listing = await async_client.get("/api/v1/sources", headers=host_session_headers)
    assert listing.status_code == 200, listing.text
    names = [s["name"] for s in listing.json()["sources"]]
    assert "guest-only" not in names

    audit = await async_client.get("/api/v1/audit-logs", headers=_headers(host))
    assert "invite.accepted" in {e["action"] for e in audit.json()["entries"]}


@pytest.mark.asyncio
async def test_invite_respects_plan_user_limit(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Limit Invite Org")
    org["session"] = await _owner_session(org["organization_id"])

    session = None
    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        await session.execute(
            text("UPDATE plans SET max_users_per_organization = 1 WHERE is_trial = true")
        )
        await session.commit()
    finally:
        await session.close()

    try:
        created = await async_client.post(
            "/api/v1/organizations/invites",
            json={"email": f"over-{uuid4().hex[:8]}@example.com", "role": "member"},
            headers=_headers(org),
        )
        assert created.status_code == 409, created.text
        assert _error_code(created) == "plan_limit_reached"
    finally:
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    "UPDATE plans SET max_users_per_organization = 10 "
                    "WHERE is_trial = true"
                )
            )
            await session.commit()
        finally:
            await session.close()
