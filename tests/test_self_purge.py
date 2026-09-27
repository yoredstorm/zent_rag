# =============================================================================
# Self purge — borrado total self-service (allowlist + step-up + wipe real)
# =============================================================================
from __future__ import annotations

import time
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from src.core.config import get_settings
from src.infrastructure.postgres.relational_db import PostgresUserRepository
from src.infrastructure.postgres.session import get_async_session


async def _create_org(client: AsyncClient, name: str) -> dict:
    email = f"self-purge-{uuid4().hex[:8]}@example.com"
    resp = await client.post(
        "/api/v1/billing/subscription/create-trial",
        json={"company_name": name, "email": email, "country": "CL"},
    )
    assert resp.status_code == 200, resp.text
    org = resp.json()
    user = await PostgresUserRepository().get_by_external_id(
        UUID(org["organization_id"]), "default-admin"
    )
    assert user is not None
    session = await get_async_session()
    try:
        await session.execute(
            text("UPDATE users SET email = :email WHERE id = :uid"),
            {"email": email, "uid": user.id},
        )
        await session.commit()
    finally:
        await session.close()
    org["owner_id"] = str(user.id)
    org["owner_email"] = email
    return org


def _session_for(organization_id: str, user_id: str, *, fresh: bool) -> str:
    from src.platform.auth.session import encrypt_session

    kwargs = (
        {"assurance": "password", "mfa_confirmed_at": int(time.time())}
        if fresh
        else {}
    )
    return encrypt_session(UUID(user_id), UUID(organization_id), **kwargs)


def _headers(org: dict, token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "X-Organization-Id": org["organization_id"],
    }


async def _count(table: str, organization_id: str) -> int:
    session = await get_async_session()
    try:
        value = (
            await session.execute(
                text(f'SELECT COUNT(*) FROM "{table}" WHERE organization_id = :oid'),
                {"oid": UUID(organization_id)},
            )
        ).scalar()
        return int(value or 0)
    finally:
        await session.close()


async def _organization_exists(organization_id: str) -> bool:
    session = await get_async_session()
    try:
        value = (
            await session.execute(
                text("SELECT COUNT(*) FROM organizations WHERE id = :oid"),
                {"oid": UUID(organization_id)},
            )
        ).scalar()
        return bool(value)
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_status_hidden_and_blocked_without_allowlist(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    org = await _create_org(async_client, "Self Purge Off")
    monkeypatch.setattr(get_settings(), "SELF_PURGE_EMAILS", "")
    token = _session_for(org["organization_id"], org["owner_id"], fresh=True)

    status = await async_client.get(
        "/api/v1/self-purge/status", headers=_headers(org, token)
    )
    assert status.status_code == 200, status.text
    assert status.json() == {"enabled": False, "allowed": False, "email": None}

    preview = await async_client.get(
        "/api/v1/self-purge/preview", headers=_headers(org, token)
    )
    assert preview.status_code == 403
    assert preview.json()["error_code"] == "self_purge_not_allowed"

    execute = await async_client.post(
        "/api/v1/self-purge/execute",
        headers=_headers(org, token),
        json={"confirmation": org["owner_email"]},
    )
    assert execute.status_code == 403


@pytest.mark.asyncio
async def test_step_up_required_and_confirmation_mismatch(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    org = await _create_org(async_client, "Self Purge Guard")
    monkeypatch.setattr(
        get_settings(), "SELF_PURGE_EMAILS", org["owner_email"]
    )

    stale = _session_for(org["organization_id"], org["owner_id"], fresh=False)
    resp = await async_client.post(
        "/api/v1/self-purge/execute",
        headers=_headers(org, stale),
        json={"confirmation": org["owner_email"]},
    )
    assert resp.status_code == 403
    assert resp.json()["error_code"] == "step_up_required"

    fresh = _session_for(org["organization_id"], org["owner_id"], fresh=True)
    mismatch = await async_client.post(
        "/api/v1/self-purge/execute",
        headers=_headers(org, fresh),
        json={"confirmation": "otro@example.com"},
    )
    assert mismatch.status_code == 400
    assert mismatch.json()["error_code"] == "confirmation_mismatch"


@pytest.mark.asyncio
async def test_self_purge_wipes_org_and_keeps_identity(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.company.demo_seed import seed_fare_audit_demo

    org = await _create_org(async_client, "Self Purge Org")
    other = await _create_org(async_client, "Self Purge Other")
    await seed_fare_audit_demo(UUID(org["organization_id"]), with_learning=False)
    await seed_fare_audit_demo(UUID(other["organization_id"]), with_learning=False)
    monkeypatch.setattr(
        get_settings(), "SELF_PURGE_EMAILS", org["owner_email"]
    )

    assert await _count("company_entities", org["organization_id"]) > 0
    other_entities = await _count("company_entities", other["organization_id"])

    fresh = _session_for(org["organization_id"], org["owner_id"], fresh=True)
    preview = await async_client.get(
        "/api/v1/self-purge/preview", headers=_headers(org, fresh)
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["total_rows"] > 0
    assert body["tables"]["company_entities"] > 0

    resp = await async_client.post(
        "/api/v1/self-purge/execute",
        headers=_headers(org, fresh),
        json={"confirmation": org["owner_email"]},
    )
    assert resp.status_code == 200, resp.text
    result = resp.json()
    assert result["failures"] == []
    assert result["after"]["total_rows"] == 0
    assert result["before"]["total_rows"] > 0

    # Datos borrados
    assert await _count("company_entities", org["organization_id"]) == 0
    assert await _count("company_relationships", org["organization_id"]) == 0
    # Un único registro de auditoría: el del reset
    assert await _count("audit_logs", org["organization_id"]) == 1
    session = await get_async_session()
    try:
        action = (
            await session.execute(
                text(
                    "SELECT action FROM audit_logs WHERE organization_id = :oid"
                ),
                {"oid": UUID(org["organization_id"])},
            )
        ).scalar()
    finally:
        await session.close()
    assert action == "self_purge.executed"

    # Identidad y suscripción intactas
    assert await _count("users", org["organization_id"]) >= 1
    assert await _count("memberships", org["organization_id"]) >= 1
    assert await _count("subscriptions", org["organization_id"]) == 1
    assert await _organization_exists(org["organization_id"])

    # Otra organización intacta
    assert await _count("company_entities", other["organization_id"]) == other_entities

    # Idempotente: la segunda corrida solo ve el registro del reset anterior
    again = _session_for(org["organization_id"], org["owner_id"], fresh=True)
    second = await async_client.post(
        "/api/v1/self-purge/execute",
        headers=_headers(org, again),
        json={"confirmation": org["owner_email"]},
    )
    assert second.status_code == 200, second.text
    assert second.json()["before"]["tables"] == {"audit_logs": 1}
    assert second.json()["failures"] == []
    assert second.json()["after"]["total_rows"] == 0
    assert await _count("audit_logs", org["organization_id"]) == 1
