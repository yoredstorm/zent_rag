# =============================================================================
# Tenant Data Migration Tools (PROMPT 41)
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
            "email": f"mg-{uuid4().hex[:8]}@example.com",
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
        "Idempotency-Key": f"mg-{uuid4().hex}",
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
async def test_preview_dry_run_and_apply_kbs(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "MG KB Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    TAG = uuid4().hex[:6]
    csv = (
        f"name,description,embedding_model\n"
        f"KB Importada {TAG} 1,Base uno,text-embedding-3-small\n"
        f"KB Importada {TAG} 2,Base dos,text-embedding-3-small\n"
        f",sin nombre,text-embedding-3-small\n"
    )
    preview = await async_client.post(
        "/api/v1/migrations/import/preview",
        headers={**_headers(org), "Idempotency-Key": f"mg-p-{uuid4().hex}"},
        json={"kind": "kb", "content": csv, "filename": "kbs.csv"},
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["rows_total"] == 3
    assert body["rows_valid"] == 2
    assert body["rows_failed"] == 1
    assert len(body["preview"]) == 2
    assert len(body["errors"]) == 1
    assert "name requerido" in body["errors"][0]["errors"]

    applied = await async_client.post(
        "/api/v1/migrations/import/apply",
        headers={**_headers(org), "Idempotency-Key": f"mg-a-{uuid4().hex}"},
        json={"migration_id": body["migration_id"]},
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["rows_applied"] == 2

    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        count = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM knowledge_bases WHERE organization_id = :oid "
                    f"AND name LIKE 'KB Importada {TAG}%'"
                ),
                {"oid": UUID(org["organization_id"])},
            )
        ).scalar()
    finally:
        await session.close()
    assert count == 2

    # Aplicar de nuevo → 404 (migración ya aplicada).
    applied2 = await async_client.post(
        "/api/v1/migrations/import/apply",
        headers={**_headers(org), "Idempotency-Key": f"mg-a2-{uuid4().hex}"},
        json={"migration_id": body["migration_id"]},
    )
    assert applied2.status_code == 404

    # Nuevo preview del mismo CSV → duplicados fallan al aplicar.
    preview2 = await async_client.post(
        "/api/v1/migrations/import/preview",
        headers={**_headers(org), "Idempotency-Key": f"mg-p2-{uuid4().hex}"},
        json={"kind": "kb", "content": csv, "filename": "kbs.csv"},
    )
    dup = await async_client.post(
        "/api/v1/migrations/import/apply",
        headers={**_headers(org), "Idempotency-Key": f"mg-a3-{uuid4().hex}"},
        json={"migration_id": preview2.json()["migration_id"]},
    )
    assert dup.json()["rows_applied"] == 0
    assert dup.json()["rows_failed"] == 3  # 1 inválida + 2 duplicadas

    listed = await async_client.get("/api/v1/migrations", headers=h)
    assert listed.json()["count"] >= 1


@pytest.mark.asyncio
async def test_preview_json_agents_and_validation(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "MG Agent Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    payload = {
        "rows": [
            {"name": "Agent Uno", "model": "gpt-4o-mini", "system_prompt": "ayuda"},
            {"name": "Agent Dos", "model": "modelo-inexistente"},
            {"name": "", "model": "gpt-4o"},
        ]
    }
    preview = await async_client.post(
        "/api/v1/migrations/import/preview",
        headers={**_headers(org), "Idempotency-Key": f"mg-j-{uuid4().hex}"},
        json={"kind": "agents", "content": __import__("json").dumps(payload), "filename": "agents.json"},
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["rows_valid"] == 1
    assert body["rows_failed"] == 2
    assert "model desconocido" in __import__("json").dumps(body["errors"])

    applied = await async_client.post(
        "/api/v1/migrations/import/apply",
        headers={**_headers(org), "Idempotency-Key": f"mg-ja-{uuid4().hex}"},
        json={"migration_id": body["migration_id"]},
    )
    assert applied.json()["rows_applied"] == 1


@pytest.mark.asyncio
async def test_export_with_manifest_and_download(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "MG Exp Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO agents (id, organization_id, name, description, system_prompt, "
                "model, status, config_json) "
                "VALUES (gen_random_uuid(), :oid, 'Exp Agent', 'd', 'p', 'gpt-4o-mini', "
                "'draft', '{\"cost_tags\": {\"team\": \"finanzas\"}}')"
            ),
            {"oid": UUID(org["organization_id"])},
        )
        await session.commit()
    finally:
        await session.close()

    exported = await async_client.post(
        "/api/v1/migrations/export",
        headers={**_headers(org), "Idempotency-Key": f"mg-e-{uuid4().hex}"},
        json={"kind": "agents"},
    )
    assert exported.status_code == 200, exported.text
    body = exported.json()
    assert body["status"] == "exported"
    assert body["manifest"]["kind"] == "agents"
    assert body["manifest"]["schema_version"] == 1
    assert body["manifest"]["counts"]["agents"] == 1

    dl = await async_client.get(
        f"/api/v1/migrations/export/{body['migration_id']}/download", headers=h
    )
    assert dl.status_code == 200, dl.text
    data = __import__("json").loads(dl.content)
    assert data["manifest"]["direction"] == "export"
    assert data["data"]["agents"][0]["name"] == "Exp Agent"
    assert data["data"]["agents"][0]["cost_tags"]["team"] == "finanzas"


@pytest.mark.asyncio
async def test_reversion_agent(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "MG Rev Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    agent = (
        await async_client.post(
            "/api/v1/agents",
            headers={**_headers(org), "Idempotency-Key": f"mg-r-{uuid4().hex}"},
            json={"name": "Rev Agent", "system_prompt": "v1", "model": "gpt-4o-mini"},
        )
    ).json()

    rev = await async_client.post(
        f"/api/v1/migrations/agents/{agent['id']}/reversion",
        headers={**_headers(org), "Idempotency-Key": f"mg-rv-{uuid4().hex}"},
    )
    assert rev.status_code == 200, rev.text
    assert rev.json()["version_number"] == 1

    rev2 = await async_client.post(
        f"/api/v1/migrations/agents/{agent['id']}/reversion",
        headers={**_headers(org), "Idempotency-Key": f"mg-rv2-{uuid4().hex}"},
    )
    assert rev2.json()["version_number"] == 2

    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        count = (
            await session.execute(
                text("SELECT COUNT(*) FROM agent_versions WHERE agent_id = :aid"),
                {"aid": UUID(agent["id"])},
            )
        ).scalar()
    finally:
        await session.close()
    assert count == 2


@pytest.mark.asyncio
async def test_platform_dashboard(async_client: AsyncClient) -> None:
    plat = await _platform_admin(async_client, f"padmin-mgd-{uuid4().hex[:8]}@zent.example")
    dash = await async_client.get("/api/v1/platform/migrations/dashboard", headers=plat)
    assert dash.status_code == 200, dash.text
    assert dash.json()["total"] >= 1
    assert "dry_run" in dash.json()["by_status"] or "applied" in dash.json()["by_status"]
    assert dash.json()["rows_applied_total"] >= 1
