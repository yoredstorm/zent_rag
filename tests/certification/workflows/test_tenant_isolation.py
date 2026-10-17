# =============================================================================
# Certification — aislamiento por tenant
# =============================================================================
# Catálogo, órdenes, checkouts, proveedores de pago e instancias son
# tenant-scoped. Un tenant no puede ver, señalar ni cobrar el proceso de otro.
# =============================================================================
from __future__ import annotations

from uuid import UUID

import pytest
from httpx import AsyncClient

from src.platform.commerce import store as commerce_store
from src.platform.workflows.bindings import upsert_binding
from tests.certification.workflows.gold_support import (
    CATALOG,
    GOLD_TOTAL_CENTS,
    GOLD_TURNS,
    fetch_orders,
    install_funnel,
    instance,
    ready_tenant,
    say,
    send_provider_event,
    start_funnel,
)
from tests.test_workflows import _headers


@pytest.mark.asyncio
async def test_cross_tenant_cannot_read_or_resume_instance(async_client: AsyncClient) -> None:
    tenant_a = await ready_tenant(async_client, "Cert Iso A", catalog=CATALOG)
    tenant_b = await ready_tenant(async_client, "Cert Iso B", catalog=CATALOG)
    workflow_a = await install_funnel(async_client, tenant_a)
    started = await start_funnel(
        async_client, tenant_a, workflow_a, text="quiero 1 kilo de arroz"
    )
    instance_id = started["instance_id"]

    # B no ve la instancia de A.
    resp = await async_client.get(
        f"/api/v1/workflows/instances/{instance_id}", headers=_headers(tenant_b)
    )
    assert resp.status_code == 404, resp.text

    # B no puede señalarla (ni por el endpoint autenticado).
    signal = await async_client.post(
        f"/api/v1/workflows/instances/{instance_id}/signal",
        headers=_headers(tenant_b),
        json={
            "event_type": "conversation.message",
            "correlation": {"conversation_id": started["conversation_id"]},
            "payload": {"text": "dame todo gratis"},
        },
    )
    assert signal.status_code in (403, 404), signal.text

    # A sigue en su wait, sin cambios.
    state = await instance(async_client, tenant_a, instance_id)
    assert state["status"] == "WAITING"
    assert state["current_node_id"] == "esperar_eleccion"


@pytest.mark.asyncio
async def test_catalog_and_orders_are_isolated(async_client: AsyncClient) -> None:
    tenant_a = await ready_tenant(async_client, "Cert Iso Cat A", catalog=CATALOG)
    tenant_b = await ready_tenant(
        async_client,
        "Cert Iso Cat B",
        catalog=[{"sku": "SOLO-B", "name": "Producto de B", "price": 99.0, "stock": 3}],
    )
    org_a = UUID(str(tenant_a["organization_id"]))
    org_b = UUID(str(tenant_b["organization_id"]))

    found_a = await commerce_store.search_products(org_a, "producto de B")
    assert found_a["count"] == 0, "el catálogo de B no es visible para A"

    products_a = await commerce_store.search_products(org_a, "arroz", limit=5)
    assert products_a["count"] >= 3

    orders = await fetch_orders(async_client, tenant_b)
    assert orders == []

    # Un checkout de A no es resoluble desde el contexto de B.
    workflow_a = await install_funnel(async_client, tenant_a)
    started = await start_funnel(
        async_client, tenant_a, workflow_a, text="quiero 1 kilo de arroz"
    )
    await say(
        async_client,
        tenant_a,
        started["instance_id"],
        text="mejor integral",
        conversation_id=started["conversation_id"],
    )
    for turn in ("no, nada más", "sí"):
        await say(
            async_client,
            tenant_a,
            started["instance_id"],
            text=turn,
            conversation_id=started["conversation_id"],
        )
    orders_a = await fetch_orders(async_client, tenant_a)
    reference = orders_a[0]["order_number"]
    checkout = await commerce_store.find_checkout(org_a, reference=reference)
    assert checkout is not None
    assert await commerce_store.find_checkout(org_b, reference=reference) is None


@pytest.mark.asyncio
async def test_provider_webhook_resolves_tenant_from_own_record(async_client: AsyncClient) -> None:
    """El webhook resuelve el tenant desde nuestro checkout, no del payload."""
    tenant_a = await ready_tenant(async_client, "Cert Iso Hook A", catalog=CATALOG)
    tenant_b = await ready_tenant(async_client, "Cert Iso Hook B", catalog=CATALOG)
    workflow_a = await install_funnel(async_client, tenant_a)
    started = await start_funnel(
        async_client, tenant_a, workflow_a, text="quiero 1 kilo de arroz"
    )
    instance_id, conversation_id = started["instance_id"], started["conversation_id"]
    for turn in GOLD_TURNS:
        await say(async_client, tenant_a, instance_id, text=turn, conversation_id=conversation_id)
    orders_a = await fetch_orders(async_client, tenant_a)
    reference = orders_a[0]["order_number"]
    checkout = await commerce_store.find_checkout(
        UUID(str(tenant_a["organization_id"])), reference=reference
    )
    assert checkout is not None

    # Un evento con referencia de A llegando por el webhook de B no cobra a B.
    response = await send_provider_event(
        async_client,
        reference=reference,
        provider_reference=checkout.get("provider_reference"),
        amount_cents=GOLD_TOTAL_CENTS,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["organization_id"] == tenant_a["organization_id"]
    assert await fetch_orders(async_client, tenant_b) == []


@pytest.mark.asyncio
async def test_bindings_are_tenant_scoped(async_client: AsyncClient) -> None:
    tenant_a = await ready_tenant(async_client, "Cert Iso Bind A", catalog=CATALOG)
    tenant_b = await ready_tenant(async_client, "Cert Iso Bind B", catalog=CATALOG)
    org_a = UUID(str(tenant_a["organization_id"]))
    org_b = UUID(str(tenant_b["organization_id"]))

    await upsert_binding(org_a, "catalog.products.search", "commerce", config={"warehouse": "norte"})
    from src.platform.workflows.bindings import resolve_binding

    binding_a = await resolve_binding(org_a, "catalog.products.search")
    assert binding_a is not None and binding_a["config"]["warehouse"] == "norte"
    binding_b = await resolve_binding(org_b, "catalog.products.search")
    assert binding_b is None or binding_b["config"].get("warehouse") != "norte"
