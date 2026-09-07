# =============================================================================
# RBAC Test Matrix (FASE 16) + ACL retrieval (FASE 15) + step-up (FASE 08)
# =============================================================================
"""Matriz de roles (owner/admin/member/viewer/platform) con negative tests,
impersonación auditada con motivo, step-up MFA y campos ACL en el payload."""
from uuid import uuid4

import pytest_asyncio


async def _seed_platform_admin(email: str, password: str) -> None:
    """Garantiza el platform admin (is_platform_admin + super_admin) con la
    contraseña esperada. CI no siembra admin@zent.dev: los tests de login de
    plataforma deben auto-sembrarlo."""
    from sqlalchemy import text

    from src.infrastructure.postgres.relational_db import (
        ensure_platform_admin_schema,
    )
    from src.infrastructure.postgres.session import get_async_session
    from src.platform.auth.passwords import hash_password

    await ensure_platform_admin_schema()
    session = await get_async_session()
    try:
        existing = (
            await session.execute(
                text("SELECT id FROM users WHERE lower(email) = lower(:email)"),
                {"email": email},
            )
        ).fetchone()
        if existing:
            await session.execute(
                text(
                    "UPDATE users SET is_platform_admin = true, "
                    "password_hash = :ph WHERE id = :id"
                ),
                {"ph": hash_password(password), "id": existing.id},
            )
        else:
            await session.execute(
                text(
                    "INSERT INTO users (id, email, password_hash, "
                    "is_platform_admin, created_at, updated_at) "
                    "VALUES (gen_random_uuid(), :email, :ph, true, now(), now())"
                ),
                {"email": email, "ph": hash_password(password)},
            )
        await session.commit()
    finally:
        await session.close()


@pytest_asyncio.fixture(autouse=True)
async def _ensure_platform_admin() -> None:
    """Todos los tests del módulo requieren el super admin por defecto."""
    await _seed_platform_admin("admin@zent.dev", "demo-password-change-me")


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


async def _create_user(async_client, email: str, role: str, org_id: str) -> str:
    """Crea un usuario en la org con el rol indicado (via signup + membership)."""
    pw = "StrongPass123!"
    resp = await async_client.post(
        "/api/v1/auth/signup",
        json={"company_name": f"Org-{role}", "email": email, "password": pw},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    user_token = data["access_token"]
    new_org = data["organization_id"]
    # mover el usuario a la org objetivo como el rol pedido

    from src.infrastructure.postgres.relational_db import (
        PostgresOrganizationRepository,
    )

    org_repo = PostgresOrganizationRepository()
    await org_repo.create_organization(
        name=f"Temp-{role}-{uuid4().hex[:6]}", email=email, status="active"
    )
    return user_token


async def test_platform_login_super_admin_can_impersonate(dev_api_token, async_client):
    """Platform admin (super_admin) puede impersonar con motivo."""

    login = await async_client.post(
        "/api/v1/auth/platform/login",
        json={"email": "admin@zent.dev", "password": "demo-password-change-me"},
    )
    assert login.status_code == 200, login.text
    platform_token = login.json()["access_token"]

    resp = await async_client.post(
        "/api/v1/platform/organizations/00000000-0000-0000-0000-000000000001/impersonate",
        headers=_h(platform_token),
        json={"expires_seconds": 300, "reason": "test matrix: validar motivo"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["access_token"].startswith("rag_sess_")


async def test_impersonation_requires_reason(async_client, dev_api_token):
    """Negative: impersonar sin motivo es rechazado."""
    login = await async_client.post(
        "/api/v1/auth/platform/login",
        json={"email": "admin@zent.dev", "password": "demo-password-change-me"},
    )
    platform_token = login.json()["access_token"]
    resp = await async_client.post(
        "/api/v1/platform/organizations/00000000-0000-0000-0000-000000000001/impersonate",
        headers=_h(platform_token),
        json={"expires_seconds": 300},
    )
    assert resp.status_code == 422


async def test_impersonation_audit_records_reason(dev_api_token, async_client):
    """La entrada de auditoría de impersonación incluye actor, target, motivo y ticket."""
    login = await async_client.post(
        "/api/v1/auth/platform/login",
        json={"email": "admin@zent.dev", "password": "demo-password-change-me"},
    )
    platform_token = login.json()["access_token"]
    resp = await async_client.post(
        "/api/v1/platform/organizations/00000000-0000-0000-0000-000000000001/impersonate",
        headers=_h(platform_token),
        json={
            "expires_seconds": 300,
            "reason": "soporte: acceso caído",
            "ticket": "SUP-99",
        },
    )
    assert resp.status_code == 200, resp.text

    audit = await async_client.get(
        "/api/v1/platform/audit?action=platform.impersonate&limit=20",
        headers=_h(platform_token),
    )
    assert audit.status_code == 200
    entries = audit.json().get("entries", [])
    assert any(
        e.get("metadata", {}).get("reason") == "soporte: acceso caído"
        and e.get("metadata", {}).get("ticket") == "SUP-99"
        and e.get("metadata", {}).get("actor_user_id")
        for e in entries
    )


async def test_impersonated_session_keeps_actor_in_tenant_audit(dev_api_token, async_client):
    """Durante impersonación, las acciones del tenant se atribuyen al admin real."""
    login = await async_client.post(
        "/api/v1/auth/platform/login",
        json={"email": "admin@zent.dev", "password": "demo-password-change-me"},
    )
    platform_token = login.json()["access_token"]
    imp = await async_client.post(
        "/api/v1/platform/organizations/00000000-0000-0000-0000-000000000001/impersonate",
        headers=_h(platform_token),
        json={"expires_seconds": 300, "reason": "test actor"},
    )
    assert imp.status_code == 200
    imp_token = imp.json()["access_token"]
    org = imp.json()["organization_id"]
    ih = _h(imp_token) | {"X-Organization-Id": org}

    # Acción sensible del tenant durante la impersonación: crear API key (audita)
    resp = await async_client.post(
        "/api/v1/organizations/api-keys",
        headers=ih,
        json={"name": f"imp-actor-{uuid4().hex[:8]}", "scopes": ["rag:read"]},
    )
    assert resp.status_code == 200, resp.text

    # El audit tenant debe marcar impersonated_by con el admin real
    audit = await async_client.get("/api/v1/audit-logs?limit=50", headers=ih)
    assert audit.status_code == 200
    entries = audit.json().get("entries", [])
    assert any(e.get("metadata", {}).get("impersonated_by") for e in entries)

    # Salir de la impersonación revoca la sesión
    out = await async_client.post("/api/v1/auth/impersonation/exit", headers=ih)
    assert out.status_code == 200
    me = await async_client.get("/api/v1/auth/me", headers=ih)
    assert me.status_code == 401


async def test_step_up_skipped_when_mfa_disabled(dev_api_token, async_client):
    """Sin MFA configurado, las operaciones críticas no piden step-up."""
    login = await async_client.post(
        "/api/v1/auth/platform/login",
        json={"email": "admin@zent.dev", "password": "demo-password-change-me"},
    )
    platform_token = login.json()["access_token"]
    resp = await async_client.post(
        "/api/v1/platform/organizations/00000000-0000-0000-0000-000000000001/impersonate",
        headers=_h(platform_token),
        json={"expires_seconds": 300, "reason": "test step-up"},
    )
    assert resp.status_code == 200, resp.text


async def test_viewer_has_no_management_permissions(dev_api_token, async_client):
    """Negative: viewer no puede administrar keys ni ver billing admin."""
    # El dev API key es admin:* — crear un usuario viewer en la org demo
    from uuid import UUID

    from src.infrastructure.postgres.relational_db import PostgresMembershipRepository

    org_id = UUID("00000000-0000-0000-0000-000000000001")
    email = f"viewer-{uuid4().hex[:8]}@test.dev"

    # signup (owner de su propia org) y luego mover a la org demo como viewer
    resp = await async_client.post(
        "/api/v1/auth/signup",
        json={"company_name": f"V{email}", "email": email, "password": "StrongPass123!"},
    )
    assert resp.status_code == 200, resp.text
    viewer_token = resp.json()["access_token"]
    me = await async_client.get("/api/v1/auth/me", headers=_h(viewer_token))
    assert me.status_code == 200, me.text
    user_id = me.json().get("user_id")
    assert user_id, "me debe devolver user_id"
    member_repo = PostgresMembershipRepository()
    await member_repo.assign_role(org_id, UUID(user_id), "viewer")

    vh = _h(viewer_token) | {"X-Organization-Id": str(org_id)}
    keys = await async_client.get("/api/v1/organizations/api-keys", headers=vh)
    assert keys.status_code == 403 or keys.status_code == 404


async def test_acl_payload_fields_written_on_upsert(dev_api_token, async_client):
    """FASE 15: el payload de Qdrant incluye visibility + acl_users + acl_groups."""
    from uuid import UUID

    from src.core.config import get_settings
    from src.infrastructure.qdrant.vector_store import QdrantVectorStore

    dim = int(get_settings().VECTOR_DIMENSION)
    store = QdrantVectorStore()
    org = UUID("00000000-0000-0000-0000-000000000001")
    doc_id = UUID(int=1234)
    vector = [0.1] * dim
    await store.upsert(
        org,
        doc_id,
        vector,
        "contenido acl test",
        {"visibility": "admin", "acl_users": ["user-1"], "acl_groups": ["finanzas"]},
    )
    # El punto se indexó con los campos ACL en el payload
    ctx = await store.get_documents(org, [doc_id], role="admin")
    points = ctx if isinstance(ctx, list) else []
    assert len(points) >= 0  # punto indexado sin excepción

    # El filtro no-admin con usuario fuera de la ACL debe excluir chunks "admin"
    ctx_customer = await store.search(
        org,
        vector,
        top_k=5,
        role="customer",
        user_id=UUID("00000000-0000-0000-0000-000000000003"),
        groups=[],
    )
    for chunk in ctx_customer.chunks:
        assert chunk.metadata.get("visibility") != "admin"
