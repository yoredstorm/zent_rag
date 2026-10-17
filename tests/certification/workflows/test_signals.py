# =============================================================================
# Certification — señales (SIGNAL)
# =============================================================================
# Una instancia WAITING solo se despierta por lo que declaró esperar, con la
# correlación correcta y una sola vez por evento. Un evento tardío o con otro
# tipo no puede producir un segundo efecto de negocio.
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


@pytest.mark.asyncio
async def test_other_event_type_does_not_wake_the_payment_wait(
    async_client: AsyncClient,
) -> None:
    """`payment.failed` no despierta un WAIT de `payment.succeeded`."""
    org = await ready_tenant(async_client, "Cert Signals Type", catalog=CATALOG)
    workflow_id = await install_funnel(async_client, org)
    started = await start_funnel(async_client, org, workflow_id, text="quiero 1 kilo de arroz")
    instance_id, conversation_id = started["instance_id"], started["conversation_id"]
    for turn in GOLD_TURNS:
        await say(async_client, org, instance_id, text=turn, conversation_id=conversation_id)
    state = await instance(async_client, org, instance_id)
    assert state["current_node_id"] == "esperar_pago"
    assert state["waiting_event_type"] == "payment.succeeded"

    mismatch = await async_client.post(
        f"/api/v1/workflows/instances/{instance_id}/signal",
        headers={**_headers(org), "Idempotency-Key": f"sig-{uuid4().hex}"},
        json={
            "event_type": "payment.failed",
            "correlation": {"payment_reference": state["waiting_correlation_key"].split("=", 1)[1]},
            "payload": {"text": "no pagué"},
            "idempotency_key": f"mismatch:{uuid4().hex}",
        },
    )
    assert mismatch.status_code == 200, mismatch.text
    body = mismatch.json()
    assert body["status"] == "event_mismatch", body
    assert body["expected_event_type"] == "payment.succeeded"

    state = await instance(async_client, org, instance_id)
    assert state["status"] == "WAITING"
    assert state["current_node_id"] == "esperar_pago"
    orders = await fetch_orders(async_client, org)
    assert orders[0]["status"] == "AWAITING_PAYMENT"


@pytest.mark.asyncio
async def test_wrong_correlation_does_not_wake_the_payment_wait(
    async_client: AsyncClient,
) -> None:
    """Un pago de OTRA referencia no despierta este proceso."""
    org = await ready_tenant(async_client, "Cert Signals Corr", catalog=CATALOG)
    workflow_id = await install_funnel(async_client, org)
    started = await start_funnel(async_client, org, workflow_id, text="quiero 1 kilo de arroz")
    instance_id, conversation_id = started["instance_id"], started["conversation_id"]
    for turn in GOLD_TURNS:
        await say(async_client, org, instance_id, text=turn, conversation_id=conversation_id)

    mismatch = await async_client.post(
        f"/api/v1/workflows/instances/{instance_id}/signal",
        headers={**_headers(org), "Idempotency-Key": f"sig-{uuid4().hex}"},
        json={
            "event_type": "payment.succeeded",
            "correlation": {"payment_reference": "Z-000000-00000-XXXX"},
            "payload": {"amount": 1.0},
            "idempotency_key": f"corr:{uuid4().hex}",
        },
    )
    assert mismatch.status_code == 200, mismatch.text
    assert mismatch.json()["status"] == "correlation_mismatch", mismatch.json()

    state = await instance(async_client, org, instance_id)
    assert state["status"] == "WAITING"


@pytest.mark.asyncio
async def test_late_provider_event_with_new_id_has_no_second_effect(
    async_client: AsyncClient,
) -> None:
    """Un segundo evento del proveedor (otro id) no duplica venta ni inventario."""
    org = await ready_tenant(async_client, "Cert Signals Late", catalog=CATALOG)
    workflow_id = await install_funnel(async_client, org)
    started = await start_funnel(async_client, org, workflow_id, text="quiero 1 kilo de arroz")
    instance_id, conversation_id = started["instance_id"], started["conversation_id"]
    for turn in GOLD_TURNS:
        await say(async_client, org, instance_id, text=turn, conversation_id=conversation_id)
    orders = await fetch_orders(async_client, org)
    reference = orders[0]["order_number"]

    from uuid import UUID

    from src.platform.commerce import store as commerce_store

    checkout = await commerce_store.find_checkout(
        UUID(str(org["organization_id"])), reference=reference
    )
    assert checkout is not None

    first = await send_provider_event(
        async_client,
        reference=reference,
        provider_reference=checkout.get("provider_reference"),
        amount_cents=GOLD_TOTAL_CENTS,
    )
    assert first.status_code == 200 and first.json()["status"] == "processed"
    state = await instance(async_client, org, instance_id)
    assert state["status"] == "COMPLETED"

    # El proveedor reintenta con OTRO id de evento (caso real de reintento).
    late = await send_provider_event(
        async_client,
        reference=reference,
        provider_reference=checkout.get("provider_reference"),
        amount_cents=GOLD_TOTAL_CENTS,
    )
    assert late.status_code == 200, late.text
    assert late.json()["status"] == "processed"
    assert late.json()["signal"]["resumed"] in (False, None), late.json()

    orders = await fetch_orders(async_client, org)
    assert len(orders) == 1
    assert orders[0]["status"] == "PAID"
    integral = await fetch_stock(org["organization_id"], "ARZ-INT-1KG")
    assert integral["available"] == 14, "un solo descuento de inventario"
    state = await instance(async_client, org, instance_id)
    assert state["status"] == "COMPLETED"
