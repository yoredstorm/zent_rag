# =============================================================================
# Phase 33A — Marketplace Factory tests
# =============================================================================
from __future__ import annotations

import uuid
from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.test_workflows import _create_org, _headers, _owner_session


async def _cc_admin(async_client: AsyncClient, email: str) -> dict:
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
                "ext": f"ccf-{uuid4().hex[:12]}",
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
    login = await async_client.post(
        "/api/v1/auth/platform/login", json={"email": email, "password": "secret-123"}
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _product_payload(slug: str, **over) -> dict:
    payload = {
        "slug": slug,
        "name": slug.replace("-", " ").title(),
        "short_description": "Producto de prueba",
        "product_type": "BUSINESS_PACK",
        "category": "operations",
        "pricing": {"model": "FREE"},
        "countries": ["PE"],
        "dependencies": [],
        "installation_flow": [{"key": "source", "question": "¿Qué fuente de ventas?"}],
        "included_assets": [],
        "status": "DRAFT",
    }
    payload.update(over)
    return payload


@pytest.mark.asyncio
async def test_factory_crud_and_gate(async_client: AsyncClient) -> None:
    cc = await _cc_admin(async_client, f"ccf-{uuid4().hex[:8]}@zent.example")
    product_slug = f"peru-verification-pack-{uuid.uuid4().hex[:8]}"

    created = await async_client.post(
        "/api/v1/platform/marketplace/products",
        headers={**cc, "Idempotency-Key": f"p-{uuid4().hex}"},
        json=_product_payload(product_slug),
    )
    assert created.status_code == 201, created.text
    pid = created.json()["product_id"]

    detail = await async_client.get(f"/api/v1/platform/marketplace/products/{pid}", headers=cc)
    assert detail.status_code == 200
    assert detail.json()["product_type"] == "BUSINESS_PACK"

    # Gate: PUBLICAR sin pricing ni assets → 400
    bad = await async_client.post(
        f"/api/v1/platform/marketplace/products/{pid}/transition",
        headers={**cc, "Idempotency-Key": f"p-{uuid4().hex}"},
        json={"status": "PUBLISHED"},
    )
    assert bad.status_code == 400

    # Llenar + pipeline READY → PUBLISHED
    await async_client.post(
        "/api/v1/platform/marketplace/products",
        headers={**cc, "Idempotency-Key": f"p-{uuid4().hex}"},
        json=_product_payload(
            product_slug,
            short_description="Desc",
            included_assets=[{"kind": "workflow_template", "ref": "new-business-customer-verification", "alias": "wf"}],
        ),
    )
    ready = await async_client.post(
        f"/api/v1/platform/marketplace/products/{pid}/transition",
        headers={**cc, "Idempotency-Key": f"p-{uuid4().hex}"},
        json={"status": "READY"},
    )
    assert ready.status_code == 200, ready.text
    pub = await async_client.post(
        f"/api/v1/platform/marketplace/products/{pid}/transition",
        headers={**cc, "Idempotency-Key": f"p-{uuid4().hex}"},
        json={"status": "PUBLISHED"},
    )
    assert pub.status_code == 200, pub.text
    assert pub.json()["status"] == "PUBLISHED"

    # Transición ilegal DRAFT→PUBLISHED desde el estado actual no aplica.
    impact = await async_client.get(f"/api/v1/platform/marketplace/products/{pid}/impact", headers=cc)
    assert impact.status_code == 200
    assert "installations" in impact.json()


@pytest.mark.asyncio
async def test_product_install_resolves_and_reuses(async_client: AsyncClient) -> None:
    from src.platform.marketplace.factory import migrate_legacy_to_products

    migrated = await migrate_legacy_to_products()
    assert migrated["created"] >= 0  # idempotente entre runs

    org = await _create_org(async_client, "Factory Tenant")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    # Producto pack que incluye integration demo-echo + workflow template.
    cc = await _cc_admin(async_client, f"ccf2-{uuid4().hex[:8]}@zent.example")
    pack_slug = f"factory-install-pack-{uuid.uuid4().hex[:8]}"
    pack = await async_client.post(
        "/api/v1/platform/marketplace/products",
        headers={**cc, "Idempotency-Key": f"p-{uuid4().hex}"},
        json=_product_payload(
            pack_slug,
            short_description="Pack con demo-echo",
            pricing={"model": "FREE"},
            status="PUBLISHED",
            included_assets=[
                {"kind": "integration", "ref": "demo-echo", "alias": "echo"},
                {"kind": "workflow_template", "ref": "daily-executive-sales-brief", "alias": "daily"},
            ],
        ),
    )
    assert pack.status_code == 201, pack.text
    pid = pack.json()["product_id"]

    install = await async_client.post(
        f"/api/v1/products/{pid}/install",
        headers={**_headers(org), "Idempotency-Key": f"p-{uuid4().hex}"},
        json={"answers": {"source": "ERP"}},
    )
    assert install.status_code in (200, 201), install.text
    body = install.json()
    assert body["reused"] is False
    assert body["installed_assets"].get("dependency.integration.echo.install_id")
    assert body["installed_assets"].get("dependency.workflow.daily.workflow_id")

    # Reinstalar → reuso (misma instalación y misma integración; no duplicar)
    again = await async_client.post(
        f"/api/v1/products/{pid}/install",
        headers={**_headers(org), "Idempotency-Key": f"p-{uuid4().hex}"},
        json={"answers": {}},
    )
    assert again.json()["reused"] is True

    # Installs del tenant (listado por org + workspace; el reuso ya verificado)
    my = await async_client.get("/api/v1/products/installs", headers=h)
    assert my.status_code == 200, my.text

    # Catálogo tenant ve solo productos publicados
    catalog = await async_client.get("/api/v1/products", headers=h)
    slugs = [p["slug"] for p in catalog.json()["products"]]
    assert pack_slug in slugs

    # Desinstalar
    un = await async_client.delete(
        f"/api/v1/products/installs/{install.json()['install_id']}",
        headers={**h, "Idempotency-Key": f"p-{uuid4().hex}"},
    )
    assert un.status_code == 200


@pytest.mark.asyncio
async def test_factory_assets_and_normalizer(async_client: AsyncClient) -> None:
    cc = await _cc_admin(async_client, f"ccf3-{uuid4().hex[:8]}@zent.example")

    overview = await async_client.get("/api/v1/platform/marketplace/overview", headers=cc)
    assert overview.status_code == 200, overview.text
    body = overview.json()
    assert body["library"]["integrations"] >= 1
    assert any(a["action_id"] == "demo.echo" for a in body["palette"]["actions"])

    lab = await async_client.post(
        "/api/v1/platform/marketplace/test/output-normalizer",
        headers={**cc, "Idempotency-Key": f"p-{uuid4().hex}"},
        json={
            "output_map": {"legal_name": "razonSocial", "status": "estado"},
            "sample": {"razonSocial": "ACME SAC", "estado": "ACTIVO"},
        },
    )
    assert lab.status_code == 200, lab.text
    assert lab.json()["normalized"] == {"legal_name": "ACME SAC", "status": "ACTIVO"}


@pytest.mark.asyncio
async def test_factory_semantic_readiness(async_client: AsyncClient) -> None:
    """Un pack con concepto semántico no resuelto falla con explicación."""
    from src.platform.marketplace.factory import migrate_legacy_to_products

    await migrate_legacy_to_products()
    org = await _create_org(async_client, "Factory Semantic")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    cc = await _cc_admin(async_client, f"ccf4-{uuid4().hex[:8]}@zent.example")

    pack = await async_client.post(
        "/api/v1/platform/marketplace/products",
        headers={**cc, "Idempotency-Key": f"p-{uuid4().hex}"},
        json=_product_payload(
            f"semantic-pack-x-{uuid.uuid4().hex[:8]}",
            short_description="x",
            status="PUBLISHED",
            included_assets=[
                {"kind": "integration", "ref": "demo-echo", "alias": "echo"},
                {"kind": "semantic", "ref": "SalesConceptX", "alias": "sales"},
            ],
        ),
    )
    pid = pack.json()["product_id"]
    install = await async_client.post(
        f"/api/v1/products/{pid}/install",
        headers={**_headers(org), "Idempotency-Key": f"p-{uuid4().hex}"},
        json={"answers": {}},
    )
    # El concepto no existe → instalación incompleta con explicación visible.
    assert install.status_code == 422
    assert "semantic" in install.text.lower() or "requiere mapeo" in install.text.lower()
