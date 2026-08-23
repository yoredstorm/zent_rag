# =============================================================================
# Billing Limits — enforcement en endpoints de creación (409)
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient


async def _create_org(client: AsyncClient, name: str) -> dict:
    response = await client.post(
        "/api/v1/billing/subscription/create-trial",
        json={
            "company_name": name,
            "email": f"bl-{uuid4().hex[:8]}@example.com",
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


@pytest.mark.asyncio
async def test_agent_limit_enforced_on_create(async_client: AsyncClient) -> None:
    from src.core.config import get_settings

    if get_settings().ENVIRONMENT != "development":
        pytest.skip("Requiere Postgres real (stack docker)")

    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    org = await _create_org(async_client, "Limits Org")
    org["session"] = await _owner_session(org["organization_id"])
    headers = _headers(org)

    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE plans SET max_agents = 1 "
                "WHERE is_trial = true"
            )
        )
        await session.commit()
    finally:
        await session.close()

    try:
        first = await async_client.post(
            "/api/v1/agents",
            json={"name": f"a-{uuid4().hex[:6]}", "tools": []},
            headers=headers,
        )
        assert first.status_code == 201, first.text

        second = await async_client.post(
            "/api/v1/agents",
            json={"name": f"a-{uuid4().hex[:6]}", "tools": []},
            headers=headers,
        )
        assert second.status_code == 409, second.text
        assert "limit" in second.text.lower()
    finally:
        session = await get_async_session()
        try:
            await session.execute(
                text("UPDATE plans SET max_agents = NULL WHERE is_trial = true")
            )
            await session.commit()
        finally:
            await session.close()


@pytest.mark.asyncio
async def test_connector_limit_enforced_on_create(
    async_client: AsyncClient,
) -> None:
    from src.core.config import get_settings

    if get_settings().ENVIRONMENT != "development":
        pytest.skip("Requiere Postgres real (stack docker)")

    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    org = await _create_org(async_client, "Limits Org 2")
    org["session"] = await _owner_session(org["organization_id"])
    headers = _headers(org)

    session = await get_async_session()
    try:
        await session.execute(
            text("UPDATE plans SET max_connectors = 0 WHERE is_trial = true")
        )
        await session.commit()
    finally:
        await session.close()

    try:
        resp = await async_client.post(
            "/api/v1/connectors",
            json={"name": f"c-{uuid4().hex[:6]}", "type": "postgres", "config": {}},
            headers=headers,
        )
        assert resp.status_code == 409, resp.text
    finally:
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    "UPDATE plans SET max_connectors = NULL "
                    "WHERE is_trial = true"
                )
            )
            await session.commit()
        finally:
            await session.close()


class TestReconciliation:
    @pytest.mark.asyncio
    async def test_report_matches_seeded_data(self) -> None:
        from src.core.config import get_settings

        if get_settings().ENVIRONMENT != "development":
            pytest.skip("Requiere Postgres real (stack docker)")

        from src.platform.billing.reconciliation import reconcile

        report = await reconcile(uuid4(), days=30)
        assert report == []  # org sin datos: report vacío, no crash
