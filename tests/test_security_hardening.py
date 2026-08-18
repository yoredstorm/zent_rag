# =============================================================================
# Security Hardening Tests — tenant isolation, role elevation, admin authz
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_rag_query_rejects_mismatched_tenant_header(
    async_client: AsyncClient, trial_auth: dict[str, str]
) -> None:
    """X-Tenant-Id distinto del Bearer -> 403 (anti cross-tenant)."""
    other = str(uuid4())
    response = await async_client.post(
        "/api/v1/rag/query",
        json={"query": "hola"},
        headers={**trial_auth, "X-Tenant-Id": other},
    )
    assert response.status_code == 403, response.text


@pytest.mark.asyncio
async def test_prompt_endpoint_rejects_mismatched_tenant_header(
    async_client: AsyncClient, trial_auth: dict[str, str]
) -> None:
    response = await async_client.get(
        "/api/v1/admin/prompt",
        headers={**trial_auth, "X-Tenant-Id": str(uuid4())},
    )
    assert response.status_code == 403, response.text


@pytest.mark.asyncio
async def test_eval_feedback_rejects_mismatched_tenant_header(
    async_client: AsyncClient, trial_auth: dict[str, str]
) -> None:
    response = await async_client.post(
        "/api/v1/eval/feedback",
        json={"query": "hola", "rating": "up"},
        headers={**trial_auth, "X-Tenant-Id": str(uuid4())},
    )
    assert response.status_code == 403, response.text


@pytest.mark.asyncio
async def test_admin_tables_require_tenant_admin(
    async_client: AsyncClient, trial_auth: dict[str, str]
) -> None:
    """API token normal (sin admin:*) no puede listar/crear tablas."""
    response = await async_client.get(
        "/api/v1/admin/tables",
        headers={**trial_auth, "X-Tenant-Id": trial_auth["X-Tenant-Id"]},
    )
    assert response.status_code == 403, response.text


@pytest.mark.asyncio
async def test_billing_admin_requires_platform_admin_scope(
    async_client: AsyncClient, trial_auth: dict[str, str]
) -> None:
    """Listar todos los tenants exige scope admin:* (no basta token de tenant)."""
    response = await async_client.get(
        "/api/v1/billing/admin/tenants",
        headers=trial_auth,
    )
    assert response.status_code == 403, response.text


@pytest.mark.asyncio
async def test_upgrade_plan_disabled_without_payment_flow(
    async_client: AsyncClient, trial_auth: dict[str, str]
) -> None:
    """Upgrade self-service deshabilitado (RAG_SELF_SERVICE_UPGRADE_ENABLED=false)."""
    response = await async_client.post(
        "/api/v1/billing/subscription/upgrade",
        headers={**trial_auth, "X-New-Plan": "enterprise"},
    )
    assert response.status_code == 403, response.text


@pytest.mark.asyncio
async def test_create_trial_requires_email(
    async_client: AsyncClient,
) -> None:
    response = await async_client.post(
        "/api/v1/billing/subscription/create-trial",
        json={"company_name": "Sin Email S.A."},
    )
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_role_cannot_be_elevated_above_server_role(
    async_client: AsyncClient,
    trial_auth: dict[str, str],
    mock_orchestrator,
) -> None:
    """body.role solo degrada: un token owner con role=customer opera como customer."""
    response = await async_client.post(
        "/api/v1/rag/query",
        json={"query": "hola", "role": "customer"},
        headers=trial_auth,
    )
    assert response.status_code == 200, response.text
    assert mock_orchestrator.last_kwargs["role"] == "customer"


@pytest.mark.asyncio
async def test_admin_sql_rejects_select_into(
    async_client: AsyncClient, dev_api_token: str
) -> None:
    response = await async_client.post(
        "/api/v1/admin/sql",
        json={"query": "SELECT * INTO hack_table FROM farmacia.products"},
        headers={
            "Authorization": f"Bearer {dev_api_token}",
            "X-Tenant-Id": "00000000-0000-0000-0000-000000000001",
        },
    )
    assert response.status_code == 403, response.text


@pytest.mark.asyncio
async def test_admin_sql_rejects_pg_sleep(
    async_client: AsyncClient, dev_api_token: str
) -> None:
    response = await async_client.post(
        "/api/v1/admin/sql",
        json={"query": "SELECT pg_sleep(60)"},
        headers={
            "Authorization": f"Bearer {dev_api_token}",
            "X-Tenant-Id": "00000000-0000-0000-0000-000000000001",
        },
    )
    assert response.status_code == 403, response.text


@pytest.mark.asyncio
async def test_admin_sql_rejects_multi_statement(
    async_client: AsyncClient, dev_api_token: str
) -> None:
    response = await async_client.post(
        "/api/v1/admin/sql",
        json={"query": "SELECT 1; SELECT 2"},
        headers={
            "Authorization": f"Bearer {dev_api_token}",
            "X-Tenant-Id": "00000000-0000-0000-0000-000000000001",
        },
    )
    assert response.status_code == 403, response.text


@pytest.mark.asyncio
async def test_body_size_limit_returns_413(
    async_client: AsyncClient, trial_auth: dict[str, str]
) -> None:
    """Bodies > MAX_BODY_BYTES son rechazados por el middleware."""
    from src.config import get_settings

    limit = get_settings().MAX_BODY_BYTES
    response = await async_client.post(
        "/api/v1/rag/query",
        json={"query": "x" * (limit + 1024)},
        headers=trial_auth,
    )
    assert response.status_code == 413, response.text


@pytest.mark.asyncio
async def test_session_token_contains_sid_and_revokes(
    async_client: AsyncClient, trial_auth: dict[str, str]
) -> None:
    """encrypt_session incluye sid; revoke_session lo marca revocado."""
    from uuid import UUID as _UUID

    from src.infrastructure.portal_session import (
        decrypt_session,
        encrypt_session,
        revoke_session,
        session_is_active,
    )

    token = encrypt_session(uuid4(), _UUID(trial_auth["X-Tenant-Id"]))
    payload = decrypt_session(token)
    assert payload.sid is not None
    assert await session_is_active(payload.sid) is True
    await revoke_session(token)
    assert await session_is_active(payload.sid) is False


@pytest.mark.asyncio
async def test_signup_rejects_overlong_password_bytes(
    async_client: AsyncClient,
) -> None:
    """Password > 72 bytes (límite bcrypt) es rechazado en signup."""
    email = f"longpw-{uuid4().hex[:8]}@example.com"
    response = await async_client.post(
        "/api/v1/auth/signup",
        json={
            "company_name": "Long PW Co",
            "email": email,
            "password": "ñ" * 40,  # 80 bytes UTF-8
        },
    )
    assert response.status_code == 422, response.text
