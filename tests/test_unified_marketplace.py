# =============================================================================
# Unified Marketplace — invariantes y paridad entre superficies.
#
# Demuestra: ONE PRODUCT / ONE CATALOG / ONE INSTALLATION / ONE RUNTIME /
# MANY SURFACES. Cualquier catálogo paralelo hace fallar estos tests.
# =============================================================================
from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.test_marketplace_factory import _cc_admin, _product_payload
from tests.test_workflows import _create_org, _headers, _owner_session

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ROUTES_DIR = _REPO_ROOT / "src" / "api" / "routes"

# Tablas que pertenecen al marketplace único o a sus assets/legacy congelado.
# Agregar un catálogo paralelo nuevo hace fallar el invariante a propósito.
_ALLOWED_CATALOG_TABLES = {
    # catálogo único + instalación de producto
    "marketplace_providers",
    "marketplace_products",
    "marketplace_product_versions",
    "marketplace_product_dependencies",
    "marketplace_product_installations",
    # assets técnicos (no son catálogo)
    "integration_manifests",
    "integration_capabilities",
    "integration_actions",
    "installed_integrations",
    "integration_credentials",
    "integration_usage_ledger",
    "integration_budget_counters",
    "integration_drafts",
    "external_evidence",
    "workflow_templates",
    # legacy congelado (adaptadores; sin nuevas superficies)
    "marketplace_listings",
    "marketplace_reviews",
    "marketplace_agents",
    "marketplace_installs",
    "marketplace_orders",
    "public_listings",
    "listing_versions",
    "listing_reviews",
    "payouts",
    # partner programs (no es catálogo de productos)
    "partners",
    "partner_programs",
    "partner_commissions",
    "partner_subtenants",
    "partner_usage",
    # datos de NEGOCIO del tenant (migración 158): catálogo del comercio,
    # inventario, órdenes y pagos. NO son catálogo de marketplace: no hay
    # listings, ni instalaciones, ni superficies de venta aquí.
    "commerce_products",
    "commerce_stock",
    "commerce_orders",
    "commerce_order_items",
    "commerce_reservations",
    "commerce_checkout_sessions",
    "commerce_payment_providers",
    "commerce_provider_events",
}
_CATALOG_TABLE_RE = re.compile(r"(marketplace|listing|product|ecosystem|payout)", re.I)

# Rutas que pueden exponer superficies marketplace (única + contextual +
# legacy congelado). Un archivo nuevo con rutas /marketplace falla a propósito.
_ALLOWED_ROUTE_FILES = {
    "marketplace.py",           # v1 integraciones (assets + ejecución)
    "marketplace_factory.py",   # catálogo canónico + Control Center
    "workflows.py",             # vista contextual (agrega desde marketplace)
    "copilot.py",               # legacy congelado (adaptador)
    "ecosystem.py",             # legacy congelado (listings/órdenes)
    "platform.py",              # legacy congelado (publicar/clonar; CC)
}


@pytest.mark.asyncio
async def test_single_catalog_tables_invariant(async_client: AsyncClient) -> None:
    """Falla si aparece una tabla de catálogo paralelo sin registrar aquí."""
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public'"
                )
            )
        ).fetchall()
    finally:
        await session.close()
    found = sorted(
        str(r.table_name)
        for r in rows
        if _CATALOG_TABLE_RE.search(str(r.table_name))
    )
    unknown = [t for t in found if t not in _ALLOWED_CATALOG_TABLES]
    assert not unknown, (
        "Catálogo paralelo detectado — unifica en marketplace_products o "
        f"registra la tabla aquí: {unknown}"
    )


def test_single_catalog_routes_invariant() -> None:
    """Falla si un módulo nuevo crea rutas /marketplace o /products propias."""
    offending: list[str] = []
    for py in _ROUTES_DIR.glob("*.py"):
        body = py.read_text(encoding="utf-8")
        if py.name not in _ALLOWED_ROUTE_FILES and '"/marketplace' in body:
            offending.append(f"{py.name}: decoradores /marketplace")
        if re.search(r'APIRouter\(prefix="/api/v1/(marketplace|products)', body):
            if py.name not in {"marketplace_factory.py", "ecosystem.py"}:
                offending.append(f"{py.name}: router de catálogo propio")
    assert not offending, (
        "Superficie paralela de marketplace en src/api/routes — unifica en el "
        f"catálogo global o registra el archivo aquí: {offending}"
    )


@pytest.mark.asyncio
async def test_applies_to_filter_facets_and_search(async_client: AsyncClient) -> None:
    from src.platform.marketplace.factory import sync_catalog_from_assets

    await sync_catalog_from_assets()
    org = await _create_org(async_client, "Unified Facets")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    agents = await async_client.get("/api/v1/products?applies_to=AGENTS", headers=h)
    assert agents.status_code == 200, agents.text
    products = agents.json()["products"]
    assert products, "el catálogo debe tener productos para AGENTS"
    assert all("AGENTS" in (p.get("applies_to") or []) for p in products)

    search = await async_client.get("/api/v1/products?q=demo-echo", headers=h)
    assert search.status_code == 200, search.text
    assert any("demo-echo" in p["slug"] for p in search.json()["products"])

    facets = await async_client.get("/api/v1/products/categories", headers=h)
    assert facets.status_code == 200, facets.text
    body = facets.json()
    assert body["categories"] and body["applies_to"]
    assert any(item["key"] == "AGENTS" for item in body["applies_to"])


@pytest.mark.asyncio
async def test_workflow_canvas_install_is_the_global_install(
    async_client: AsyncClient,
) -> None:
    """Instalar desde Workflows == instalar desde Marketplace (mismo registro)."""
    from src.platform.marketplace.factory import sync_catalog_from_assets

    await sync_catalog_from_assets()
    org = await _create_org(async_client, "Unified Canvas")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    catalog = await async_client.get("/api/v1/products?q=demo-echo", headers=h)
    product = next(
        p for p in catalog.json()["products"] if p["slug"] == "product-demo-echo"
    )

    # 1) Instalación desde la vista contextual (canvas de workflows), por producto.
    inline = await async_client.post(
        "/api/v1/workflows/marketplace/install",
        headers={**h, "Idempotency-Key": f"um-{uuid4().hex}"},
        json={"product_slug": "product-demo-echo"},
    )
    assert inline.status_code == 200, inline.text
    body = inline.json()
    product_install_id = body["product_install_id"]
    assert product_install_id

    # 2) La instalación global la ve /marketplace (misma instalación, no copia).
    installs = await async_client.get("/api/v1/products/installs", headers=h)
    assert installs.status_code == 200, installs.text
    mine = [
        i for i in installs.json()["installs"] if i["id"] == product_install_id
    ]
    assert mine, "la instalación contextual debe aparecer en la biblioteca global"
    assert mine[0]["product"]["slug"] == product["slug"]

    # 3) Instalar de nuevo desde el catálogo reutiliza la MISMA instalación.
    again = await async_client.post(
        f"/api/v1/products/{product['id']}/install",
        headers={**h, "Idempotency-Key": f"um-{uuid4().hex}"},
        json={"answers": {}},
    )
    assert again.status_code in (200, 201), again.text
    assert again.json()["reused"] is True
    assert again.json()["install_id"] == product_install_id

    # 4) El canvas también reutiliza el install de integración (runtime único).
    ctx = await async_client.get("/api/v1/workflows/marketplace/context", headers=h)
    installed = ctx.json()["installed"]
    demo = [s for s in installed if s["integration"]["slug"] == "demo-echo"]
    assert demo, installed
    assert demo[0]["install_id"] == body["install_id"]


@pytest.mark.asyncio
async def test_capability_first_dependency_resolution(async_client: AsyncClient) -> None:
    """kind=capability resuelve a un provider concreto (no a un plugin fijo)."""
    cc = await _cc_admin(async_client, f"um-cc-{uuid4().hex[:8]}@zent.example")
    slug = f"capability-pack-{uuid4().hex[:8]}"
    created = await async_client.post(
        "/api/v1/platform/marketplace/products",
        headers={**cc, "Idempotency-Key": f"um-{uuid4().hex}"},
        json=_product_payload(
            slug,
            short_description="Pack por capability",
            product_type="INTEGRATION",
            status="PUBLISHED",
            pricing={"model": "FREE"},
            included_assets=[],
            dependencies=[
                {"kind": "capability", "ref": "echo", "requirement": "required", "alias": "echo"}
            ],
        ),
    )
    assert created.status_code == 201, created.text
    pid = created.json()["product_id"]

    org = await _create_org(async_client, "Unified Capability")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)
    install = await async_client.post(
        f"/api/v1/products/{pid}/install",
        headers={**h, "Idempotency-Key": f"um-{uuid4().hex}"},
        json={"answers": {}},
    )
    assert install.status_code in (200, 201), install.text
    assets = install.json()["installed_assets"]
    assert assets.get("dependency.capability.echo.install_id")
    assert install.json()["readiness"] == "READY"

    # Capability inexistente → instalación incompleta con explicación (no parcial).
    missing_slug = f"capability-missing-{uuid4().hex[:8]}"
    created2 = await async_client.post(
        "/api/v1/platform/marketplace/products",
        headers={**cc, "Idempotency-Key": f"um-{uuid4().hex}"},
        json=_product_payload(
            missing_slug,
            short_description="Pack sin provider",
            product_type="INTEGRATION",
            status="PUBLISHED",
            pricing={"model": "FREE"},
            included_assets=[],
            dependencies=[
                {"kind": "capability", "ref": "no.such.capability", "requirement": "required"}
            ],
        ),
    )
    assert created2.status_code == 201, created2.text
    failed = await async_client.post(
        f"/api/v1/products/{created2.json()['product_id']}/install",
        headers={**h, "Idempotency-Key": f"um-{uuid4().hex}"},
        json={"answers": {}},
    )
    assert failed.status_code == 422
    assert "no resoluble" in failed.text or "no.such.capability" in failed.text


@pytest.mark.asyncio
async def test_paused_product_not_installable_and_hidden(async_client: AsyncClient) -> None:
    cc = await _cc_admin(async_client, f"um-cc-{uuid4().hex[:8]}@zent.example")
    slug = f"paused-pack-{uuid4().hex[:8]}"
    created = await async_client.post(
        "/api/v1/platform/marketplace/products",
        headers={**cc, "Idempotency-Key": f"um-{uuid4().hex}"},
        json=_product_payload(
            slug,
            status="PUBLISHED",
            pricing={"model": "FREE"},
            included_assets=[{"kind": "integration", "ref": "demo-echo", "alias": "echo"}],
        ),
    )
    assert created.status_code == 201, created.text
    pid = created.json()["product_id"]

    org = await _create_org(async_client, "Unified Paused")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    paused = await async_client.post(
        f"/api/v1/platform/marketplace/products/{pid}/transition",
        headers={**cc, "Idempotency-Key": f"um-{uuid4().hex}"},
        json={"status": "PAUSED"},
    )
    assert paused.status_code == 200, paused.text

    catalog = await async_client.get("/api/v1/products", headers=h)
    assert all(p["id"] != pid for p in catalog.json()["products"])

    install = await async_client.post(
        f"/api/v1/products/{pid}/install",
        headers={**h, "Idempotency-Key": f"um-{uuid4().hex}"},
        json={"answers": {}},
    )
    assert install.status_code == 422


@pytest.mark.asyncio
async def test_updates_detected_and_applied(async_client: AsyncClient) -> None:
    cc = await _cc_admin(async_client, f"um-cc-{uuid4().hex[:8]}@zent.example")
    slug = f"update-pack-{uuid4().hex[:8]}"
    created = await async_client.post(
        "/api/v1/platform/marketplace/products",
        headers={**cc, "Idempotency-Key": f"um-{uuid4().hex}"},
        json=_product_payload(
            slug,
            status="PUBLISHED",
            pricing={"model": "FREE"},
            included_assets=[{"kind": "integration", "ref": "demo-echo", "alias": "echo"}],
        ),
    )
    assert created.status_code == 201, created.text
    pid = created.json()["product_id"]

    org = await _create_org(async_client, "Unified Updates")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)
    install = await async_client.post(
        f"/api/v1/products/{pid}/install",
        headers={**h, "Idempotency-Key": f"um-{uuid4().hex}"},
        json={"answers": {}},
    )
    assert install.status_code in (200, 201), install.text
    install_id = install.json()["install_id"]

    updates = await async_client.get("/api/v1/products/updates", headers=h)
    assert updates.status_code == 200, updates.text
    assert all(i["id"] != install_id for i in updates.json()["installs"])

    version = await async_client.post(
        f"/api/v1/platform/marketplace/products/{pid}/versions",
        headers={**cc, "Idempotency-Key": f"um-{uuid4().hex}"},
        json={"version": 2},
    )
    assert version.status_code == 200, version.text

    updates2 = await async_client.get("/api/v1/products/updates", headers=h)
    assert updates2.status_code == 200, updates2.text
    assert any(i["id"] == install_id for i in updates2.json()["installs"])

    applied = await async_client.post(
        f"/api/v1/products/installs/{install_id}/update",
        headers={**h, "Idempotency-Key": f"um-{uuid4().hex}"},
        json={},
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["updated"] is True

    updates3 = await async_client.get("/api/v1/products/updates", headers=h)
    assert all(i["id"] != install_id for i in updates3.json()["installs"])


@pytest.mark.asyncio
async def test_uninstall_impact_and_cascade(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Unified Uninstall")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    install = await async_client.post(
        "/api/v1/workflows/marketplace/install",
        headers={**h, "Idempotency-Key": f"um-{uuid4().hex}"},
        json={"integration_slug": "demo-echo"},
    )
    assert install.status_code == 200, install.text

    from src.platform.marketplace.factory import sync_catalog_from_assets

    await sync_catalog_from_assets()
    catalog = await async_client.get("/api/v1/products?q=demo-echo", headers=h)
    product = next(
        p for p in catalog.json()["products"] if p["slug"] == "product-demo-echo"
    )
    installed = await async_client.post(
        f"/api/v1/products/{product['id']}/install",
        headers={**h, "Idempotency-Key": f"um-{uuid4().hex}"},
        json={"answers": {}},
    )
    assert installed.status_code in (200, 201), installed.text
    product_install_id = installed.json()["install_id"]

    impact = await async_client.get(
        f"/api/v1/products/installs/{product_install_id}/impact", headers=h
    )
    assert impact.status_code == 200, impact.text
    assert impact.json()["assets"], "el impacto debe listar los assets"

    removed = await async_client.delete(
        f"/api/v1/products/installs/{product_install_id}?cascade=false",
        headers={**h, "Idempotency-Key": f"um-{uuid4().hex}"},
    )
    assert removed.status_code == 200, removed.text
    body = removed.json()
    assert body["deleted"] is True
    assert "impact" in body and "retained" in body


@pytest.mark.asyncio
async def test_cross_tenant_installation_isolation(async_client: AsyncClient) -> None:
    org_a = await _create_org(async_client, "Unified Tenant A")
    org_a["session"] = await _owner_session(async_client, org_a["organization_id"])
    org_b = await _create_org(async_client, "Unified Tenant B")
    org_b["session"] = await _owner_session(async_client, org_b["organization_id"])

    install = await async_client.post(
        "/api/v1/workflows/marketplace/install",
        headers={**_headers(org_a), "Idempotency-Key": f"um-{uuid4().hex}"},
        json={"integration_slug": "demo-echo"},
    )
    assert install.status_code == 200, install.text
    install_id = install.json()["install_id"]

    mine_b = await async_client.get("/api/v1/products/installs", headers=_headers(org_b))
    assert mine_b.status_code == 200, mine_b.text
    assert all(i["id"] != install_id for i in mine_b.json()["installs"])

    stolen = await async_client.delete(
        f"/api/v1/products/installs/{install_id}",
        headers={**_headers(org_b), "Idempotency-Key": f"um-{uuid4().hex}"},
    )
    assert stolen.status_code == 404
