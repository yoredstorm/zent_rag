# =============================================================================
# Certification — resolución de dependencias del Marketplace global
# =============================================================================
# El producto del embudo vive en el catálogo único. Instalarlo resuelve sus
# dependencias capability-first y nunca crea un marketplace paralelo ni publica
# un workflow con dependencias críticas sin resolver.
# =============================================================================
from __future__ import annotations

import pytest
from httpx import AsyncClient

from src.platform.commerce import contracts as C
from tests.certification.workflows.gold_support import (
    CATALOG,
    bind_commerce,
    bind_conversation,
    configure_sandbox_payments,
    make_tenant,
    seed_catalog,
)
from tests.test_workflows import _headers

PRODUCT_SLUG = "retail-sales-funnel"


async def _catalog_product(client: AsyncClient, org: dict, slug: str) -> dict:
    resp = await client.get(
        "/api/v1/products", headers=_headers(org), params={"q": slug}
    )
    assert resp.status_code == 200, resp.text
    for product in resp.json().get("products") or []:
        if product.get("slug") == slug:
            return product
    raise AssertionError(f"producto {slug} no está en el catálogo: {resp.text[:400]}")


@pytest.mark.asyncio
async def test_funnel_product_is_published_in_global_marketplace(
    async_client: AsyncClient,
) -> None:
    org = await make_tenant(async_client, "Marketplace Funnel")
    product = await _catalog_product(async_client, org, PRODUCT_SLUG)
    assert product["status"] == "PUBLISHED"
    assert product["product_type"] == "WORKFLOW_TEMPLATE"
    assert "WORKFLOWS" in product["applies_to"]
    assert "AGENTS" in product["applies_to"]
    assert product["pricing"]["model"] == "FREE"

    detail = await async_client.get(
        f"/api/v1/products/{product.get('product_id') or product['id']}", headers=_headers(org)
    )
    assert detail.status_code == 200, detail.text
    detail_body = detail.json()
    full = detail_body.get("product") or detail_body
    assert C.CAP_CATALOG_SEARCH in full["capabilities"]
    assert C.CAP_PAYMENT_CHECKOUT_CREATE in full["capabilities"]
    assert "payment.succeeded" in full["events"]
    assert "conversac" in full["short_description"].lower()


@pytest.mark.asyncio
async def test_readiness_checklist_reports_gaps_and_marketplace_cta(
    async_client: AsyncClient,
) -> None:
    org = await make_tenant(async_client, "Readiness Funnel")
    resp = await async_client.get(
        "/api/v1/commerce/sales-funnel/readiness", headers=_headers(org)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["title"] == "Configura tu embudo"
    assert body["ready"] is False
    items = {item["key"]: item for item in body["items"]}
    assert items["catalog"]["status"] == "attention"
    assert items["inventory"]["status"] == "attention"
    assert items["payment"]["status"] == "attention"
    assert items["messaging"]["status"] == "ok"
    assert items["sales"]["status"] == "ok"
    assert items["payment"]["action"]["kind"] == "marketplace"
    assert items["payment"]["action"]["filter"] == "payments"
    # Sin errores técnicos: el texto es humano.
    assert "payments.checkout.create" not in (items["payment"]["hint"] or "")

    # Tras configurar el tenant, el checklist queda en verde.
    await seed_catalog(org["organization_id"], CATALOG)
    await bind_commerce(org["organization_id"])
    await bind_conversation(org["organization_id"])
    await configure_sandbox_payments(org["organization_id"])
    resp = await async_client.get(
        "/api/v1/commerce/sales-funnel/readiness", headers=_headers(org)
    )
    body = resp.json()
    assert body["ready"] is True, body


@pytest.mark.asyncio
async def test_installing_product_without_dependencies_creates_no_published_workflow(
    async_client: AsyncClient,
) -> None:
    """Sin catálogo/inventario/pago el producto no deja un workflow publicado."""
    org = await make_tenant(async_client, "Marketplace Deps")
    product = await _catalog_product(async_client, org, PRODUCT_SLUG)
    product_id = product.get("product_id") or product["id"]

    install = await async_client.post(
        f"/api/v1/products/{product_id}/install", headers=_headers(org), json={}
    )
    # La instalación falla explicada (sin estados parciales) o queda en
    # NEEDS_CONFIGURATION: en ningún caso hay un workflow publicado.
    assert install.status_code in (200, 422), install.text

    resp = await async_client.get("/api/v1/workflows", headers=_headers(org))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    workflows = body.get("workflows") if isinstance(body, dict) else body
    if isinstance(workflows, dict):
        workflows = list(workflows.values())
    assert isinstance(workflows, list), body
    published = [
        w for w in workflows if isinstance(w, dict) and str(w.get("status")) == "active"
    ]
    assert published == [], published


@pytest.mark.asyncio
async def test_capability_first_resolution_uses_installed_provider(
    async_client: AsyncClient,
) -> None:
    """Una capacidad se resuelve por el proveedor del tenant, no por un UUID."""
    from src.platform.marketplace.resolver import resolve_capability

    org = await make_tenant(async_client, "Marketplace Resolve")
    resolved = await resolve_capability(org["organization_id"], C.CAP_CATALOG_SEARCH)
    assert resolved["resolved"] is False, resolved

    await seed_catalog(org["organization_id"], CATALOG)
    await bind_commerce(org["organization_id"], [C.CAP_CATALOG_SEARCH])

    from src.platform.workflows.bindings import resolve_binding

    binding = await resolve_binding(org["organization_id"], C.CAP_CATALOG_SEARCH)
    assert binding is not None
    assert binding["provider_kind"] == "commerce"
    # El binding declara el contrato: un import puede avisar si el proveedor no
    # cumple la forma esperada.
    assert binding["contract_input_schema"].get("required") == ["query"]
    assert "products" in binding["contract_output_schema"].get("properties", {})


@pytest.mark.asyncio
async def test_messaging_capability_is_provided_by_builtin_addon(
    async_client: AsyncClient,
) -> None:
    from src.platform.marketplace.resolver import resolve_capability

    org = await make_tenant(async_client, "Marketplace Messaging")
    resolved = await resolve_capability(org["organization_id"], "conversation.send")
    assert resolved["resolved"] is True, resolved
    assert resolved.get("provider_name") or resolved.get("integration_slug")
