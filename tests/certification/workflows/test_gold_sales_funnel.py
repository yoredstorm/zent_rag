# =============================================================================
# GOLD TEST — Retail Sales Funnel end-to-end
# =============================================================================
# CONVERSATION → DURABLE WORKFLOW → REAL BUSINESS DATA → CART → WAIT/RESUME →
# PAYMENT → VERIFIED EVENT → BUSINESS TRANSACTION → COMPLETION
#
# Cada aserción es una promesa arquitectónica: la MISMA instancia durante todo
# el proceso, datos reales del catálogo, un solo checkout, una sola venta, un
# solo descuento de inventario.
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.certification.workflows.gold_support import (
    CATALOG,
    GOLD_TOTAL_CENTS,
    GOLD_TURNS,
    fetch_orders,
    fetch_stock,
    install_funnel,
    instance,
    ready_tenant,
    say,
    send_provider_event,
    start_funnel,
)
from tests.test_workflows import _headers


async def _timeline(client: AsyncClient, org: dict, instance_id: str) -> dict:
    resp = await client.get(
        f"/api/v1/workflows/instances/{instance_id}/timeline", headers=_headers(org)
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_gold_retail_sales_funnel_end_to_end(async_client: AsyncClient) -> None:
    org = await ready_tenant(async_client, "Gold Funnel", catalog=CATALOG)
    workflow_id = await install_funnel(async_client, org)

    # --- Turno 1: "quiero 1 kilo de arroz" ----------------------------------
    started = await start_funnel(
        async_client, org, workflow_id, text="quiero 1 kilo de arroz"
    )
    instance_id = started["instance_id"]
    conversation_id = started["conversation_id"]

    state = await instance(async_client, org, instance_id)
    assert state["status"] == "WAITING", state
    assert state["current_node_id"] == "esperar_eleccion"
    assert state["workflow_id"] == workflow_id

    timeline = await _timeline(async_client, org, instance_id)
    assert timeline.get("events"), timeline
    # Una sola búsqueda de catálogo en el primer turno (no se repite el paso).
    assert _finished(timeline, "buscar") == 1, _kinds(timeline)

    # Opciones reales con precio del catálogo (server-side, no del LLM).
    options = (state.get("state") or {}).get("catalog", {}).get("options") or []
    names = {o["name"] for o in options}
    assert {"Arroz Costeño", "Arroz Paisana", "Arroz Integral"} <= names
    prices = {o["name"]: o["price"] for o in options}
    assert prices["Arroz Costeño"] == 5.90
    assert prices["Arroz Paisana"] == 5.50
    assert prices["Arroz Integral"] == 7.20

    # --- Turno 2: "mejor integral" -----------------------------------------
    await say(
        async_client,
        org,
        instance_id,
        text="mejor integral",
        conversation_id=conversation_id,
    )
    state = await instance(async_client, org, instance_id)
    assert state["status"] == "WAITING", state
    assert state["current_node_id"] == "esperar_mas"
    assert state["run_seq"] >= 2, state  # MISMA instancia, segundo segmento

    cart = (state.get("state") or {}).get("cart", {}).get("items") or []
    assert len(cart) == 1, cart
    assert cart[0]["name"] == "Arroz Integral"
    assert cart[0]["quantity"] == 1.0
    assert cart[0]["unit_price"] == 7.20

    # --- Turno 3: "también una leche" → vuelve al bucle de producto --------
    await say(
        async_client,
        org,
        instance_id,
        text="también una leche",
        conversation_id=conversation_id,
    )
    state = await instance(async_client, org, instance_id)
    assert state["status"] == "WAITING", state
    assert state["current_node_id"] == "esperar_mas"
    cart = (state.get("state") or {}).get("cart", {}).get("items") or []
    assert len(cart) == 2, cart
    assert {line["name"] for line in cart} == {"Arroz Integral", "Leche Gloria"}

    # El bucle re-ejecutó el cuerpo sin duplicar el arroz: la búsqueda sí volvió.
    timeline = await _timeline(async_client, org, instance_id)
    assert _finished(timeline, "buscar") == 2, _kinds(timeline)

    # --- Turno 4: "nada más" → resumen y confirmación ----------------------
    await say(
        async_client,
        org,
        instance_id,
        text="no, nada más",
        conversation_id=conversation_id,
    )
    state = await instance(async_client, org, instance_id)
    assert state["status"] == "WAITING", state
    assert state["current_node_id"] == "esperar_confirmacion"

    # --- Turno 5: "sí" → checkout + QR ------------------------------------
    await say(async_client, org, instance_id, text="sí", conversation_id=conversation_id)
    state = await instance(async_client, org, instance_id)
    assert state["status"] == "WAITING", state
    assert state["current_node_id"] == "esperar_pago"

    orders = await fetch_orders(async_client, org)
    assert len(orders) == 1, orders
    order = orders[0]
    assert order["status"] == "AWAITING_PAYMENT"
    assert order["total"] == pytest.approx(11.40, abs=0.01)  # 7.20 + 4.20
    assert order["currency"] == "PEN"
    assert order["workflow_instance_id"] == instance_id
    reference = order["order_number"]

    # Un solo checkout, con QR/link y monto server-side.
    checkout = (state.get("state") or {}).get("cart", {})
    resp = await async_client.get("/api/v1/commerce/orders", headers=_headers(org))
    assert resp.status_code == 200

    # --- Pago confirmado (webhook firmado del proveedor) -------------------
    provider_reference = await _checkout_provider_reference(org, reference)
    webhook = await send_provider_event(
        async_client,
        reference=reference,
        provider_reference=provider_reference,
        status="paid",
        amount_cents=1140,
    )
    assert webhook.status_code == 200, webhook.text
    assert webhook.json()["status"] == "processed", webhook.text
    assert webhook.json()["matched"] is True
    assert webhook.json()["signal"]["resumed"] is True, webhook.text

    state = await instance(async_client, org, instance_id)
    assert state["status"] == "COMPLETED", state

    # El cierre ejecutó los pasos de negocio exactamente una vez cada uno.
    timeline = await _timeline(async_client, org, instance_id)
    for node_id in ("marcar_pagada", "confirmar_inventario", "mensaje_final", "resultado"):
        assert _finished(timeline, node_id) == 1, (node_id, _kinds(timeline))

    orders = await fetch_orders(async_client, org)
    assert len(orders) == 1, orders
    assert orders[0]["status"] == "PAID"
    assert orders[0]["paid_at"]
    assert orders[0]["payment_provider"] == "sandbox"

    # Inventario confirmado exactamente una vez.
    integral = await fetch_stock(org["organization_id"], "ARZ-INT-1KG")
    leche = await fetch_stock(org["organization_id"], "LEC-GLO-1L")
    assert integral["available"] == 14  # 15 - 1
    assert integral["reserved"] == 0
    assert leche["available"] == 29  # 30 - 1
    assert leche["reserved"] == 0

    # Timeline: la instancia pasó por wait_entered y terminó una sola vez.
    timeline = await _timeline(async_client, org, instance_id)
    kinds = _kinds(timeline)
    assert kinds.count("wait_entered") >= 4, kinds
    assert kinds.count("instance_completed") == 1, kinds


@pytest.mark.asyncio
async def test_gold_change_of_mind_keeps_same_instance_and_empty_cart(
    async_client: AsyncClient,
) -> None:
    """El cliente rechaza la opción: nada entra al carrito y el proceso sigue."""
    org = await ready_tenant(async_client, "Gold Mind", catalog=CATALOG)
    workflow_id = await install_funnel(async_client, org)
    started = await start_funnel(async_client, org, workflow_id, text="quiero 1 kilo de arroz")
    instance_id, conversation_id = started["instance_id"], started["conversation_id"]

    # "no quiero ese" no es un producto: el embudo vuelve a preguntar.
    await say(
        async_client,
        org,
        instance_id,
        text="no quiero ese",
        conversation_id=conversation_id,
    )
    state = await instance(async_client, org, instance_id)
    assert state["status"] == "WAITING", state
    assert state["current_node_id"] == "esperar_reintento_eleccion", state
    cart = (state.get("state") or {}).get("cart", {}).get("items") or []
    assert cart == [], cart
    assert state["run_seq"] >= 2

    # El mismo proceso acepta la nueva elección sin reiniciarse.
    await say(
        async_client,
        org,
        instance_id,
        text="mejor integral",
        conversation_id=conversation_id,
    )
    state = await instance(async_client, org, instance_id)
    assert state["current_node_id"] == "esperar_mas", state
    cart = (state.get("state") or {}).get("cart", {}).get("items") or []
    assert [line["name"] for line in cart] == ["Arroz Integral"], cart

    # Y sigue vivo para cerrar la venta.
    await say(async_client, org, instance_id, text="no, nada más", conversation_id=conversation_id)
    await say(async_client, org, instance_id, text="sí", conversation_id=conversation_id)
    state = await instance(async_client, org, instance_id)
    assert state["current_node_id"] == "esperar_pago", state
    orders = await fetch_orders(async_client, org)
    assert len(orders) == 1
    assert orders[0]["total"] == pytest.approx(7.20, abs=0.01)


def _kinds(timeline: dict) -> list[str]:
    return [e.get("kind") or e.get("event") for e in (timeline.get("events") or [])]


def _finished(timeline: dict, node_id: str) -> int:
    return sum(
        1
        for event in timeline.get("events") or []
        if event.get("kind") == "node_finished" and event.get("node_id") == node_id
    )


async def _checkout_provider_reference(org: dict, reference: str) -> str | None:
    from src.platform.commerce import store as commerce_store

    checkout = await commerce_store.find_checkout(org_uuid(org), reference=reference)
    assert checkout is not None, "el checkout debía existir antes del pago"
    assert checkout["status"] == "pending"
    assert checkout["qr_payload"], checkout
    return checkout.get("provider_reference")


def org_uuid(org: dict):
    from uuid import UUID

    return UUID(str(org["organization_id"]))


@pytest.mark.asyncio
async def test_gold_duplicate_webhook_has_single_business_effect(
    async_client: AsyncClient,
) -> None:
    """El mismo evento de pago dos veces: un solo efecto de negocio."""
    org = await ready_tenant(async_client, "Gold Duplicate", catalog=CATALOG)
    workflow_id = await install_funnel(async_client, org)
    started = await start_funnel(async_client, org, workflow_id, text="quiero 1 kilo de arroz")
    instance_id, conversation_id = started["instance_id"], started["conversation_id"]
    for text in GOLD_TURNS:
        await say(
            async_client, org, instance_id, text=text, conversation_id=conversation_id
        )
    orders = await fetch_orders(async_client, org)
    reference = orders[0]["order_number"]
    provider_reference = await _checkout_provider_reference(org, reference)
    event_id = f"evt-dup-{uuid4().hex}"

    first = await send_provider_event(
        async_client,
        reference=reference,
        provider_reference=provider_reference,
        event_id=event_id,
        amount_cents=GOLD_TOTAL_CENTS,
    )
    assert first.status_code == 200 and first.json()["status"] == "processed"
    second = await send_provider_event(
        async_client,
        reference=reference,
        provider_reference=provider_reference,
        event_id=event_id,
        amount_cents=GOLD_TOTAL_CENTS,
    )
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate"

    orders = await fetch_orders(async_client, org)
    assert len(orders) == 1
    assert orders[0]["status"] == "PAID"
    integral = await fetch_stock(org["organization_id"], "ARZ-INT-1KG")
    assert integral["available"] == 14  # un solo descuento
    state = await instance(async_client, org, instance_id)
    assert state["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_gold_invalid_signature_is_rejected(async_client: AsyncClient) -> None:
    """Sin firma válida no hay señal, ni siquiera con payload correcto."""
    org = await ready_tenant(async_client, "Gold Signature", catalog=CATALOG)
    workflow_id = await install_funnel(async_client, org)
    started = await start_funnel(async_client, org, workflow_id, text="quiero 1 kilo de arroz")
    instance_id, conversation_id = started["instance_id"], started["conversation_id"]
    for text in ("mejor integral", "no, nada más", "sí"):
        await say(async_client, org, instance_id, text=text, conversation_id=conversation_id)
    orders = await fetch_orders(async_client, org)
    reference = orders[0]["order_number"]
    provider_reference = await _checkout_provider_reference(org, reference)

    bad = await send_provider_event(
        async_client,
        reference=reference,
        provider_reference=provider_reference,
        secret="wrong-secret",
    )
    assert bad.status_code == 400, bad.text
    body = bad.json()
    assert body.get("details", {}).get("code") == "SIGNATURE_INVALID", body

    orders = await fetch_orders(async_client, org)
    assert orders[0]["status"] == "AWAITING_PAYMENT"
    state = await instance(async_client, org, instance_id)
    assert state["status"] == "WAITING"
    integral = await fetch_stock(org["organization_id"], "ARZ-INT-1KG")
    assert integral["available"] == 15  # nada se descontó
    assert integral["reserved"] == 1  # la reserva sigue viva
