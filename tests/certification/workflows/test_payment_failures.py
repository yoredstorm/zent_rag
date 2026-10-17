# =============================================================================
# Certification — pagos: fallo, expiración, reintento y aviso al cliente
# =============================================================================
# Un pago que NO se confirma no puede producir una venta. La reserva de
# inventario se libera, el cliente recibe un mensaje y el proceso sigue vivo
# para que pueda reintentar con el mismo checkout.
# =============================================================================
from __future__ import annotations

from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from src.infrastructure.postgres.session import get_async_session
from tests.certification.workflows.gold_support import (
    CATALOG,
    GOLD_TOTAL_CENTS,
    GOLD_TURNS,
    fetch_orders,
    fetch_stock,
    force_wait_deadline,
    force_wait_timeout,
    install_funnel,
    instance,
    ready_tenant,
    say,
    send_provider_event,
    start_funnel,
)
from tests.certification.workflows.gold_support import fetch_orders as _orders


async def _notifications(organization_id: str, event_type: str) -> int:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT COUNT(*) AS n FROM tenant_notifications "
                    "WHERE organization_id = :oid AND event_type = :et"
                ),
                {"oid": str(organization_id), "et": event_type},
            )
        ).fetchone()
    finally:
        await session.close()
    return int(row.n)


async def _checkout_of(organization_id: str, reference: str) -> dict:
    from src.platform.commerce import store as commerce_store

    checkout = await commerce_store.find_checkout(UUID(str(organization_id)), reference=reference)
    assert checkout is not None
    return checkout


async def _ready_for_payment(client: AsyncClient, name: str) -> tuple[dict, str, str, dict]:
    org = await ready_tenant(client, name, catalog=CATALOG)
    workflow_id = await install_funnel(client, org)
    started = await start_funnel(client, org, workflow_id, text="quiero 1 kilo de arroz")
    instance_id, conversation_id = started["instance_id"], started["conversation_id"]
    for turn in GOLD_TURNS:
        await say(client, org, instance_id, text=turn, conversation_id=conversation_id)
    orders = await _orders(client, org)
    assert len(orders) == 1
    return org, instance_id, conversation_id, orders[0]


@pytest.mark.asyncio
async def test_payment_failed_releases_stock_and_keeps_order_unpaid(
    async_client: AsyncClient,
) -> None:
    org, instance_id, _conv, order = await _ready_for_payment(async_client, "Cert PayFail")
    reference = order["order_number"]
    checkout = await _checkout_of(org["organization_id"], reference)

    response = await send_provider_event(
        async_client,
        reference=reference,
        provider_reference=checkout.get("provider_reference"),
        status="failed",
    )
    assert response.status_code == 200, response.text
    assert response.json()["event_type"] == "payment.failed"

    orders = await fetch_orders(async_client, org)
    assert orders[0]["status"] == "AWAITING_PAYMENT", "un pago fallido no vende"

    integral = await fetch_stock(org["organization_id"], "ARZ-INT-1KG")
    assert integral["reserved"] == 0, "la reserva se libera"
    assert integral["available"] == 15, "el stock no se descuenta"

    assert await _notifications(org["organization_id"], "payment.failed") >= 1, "cliente informado"

    # El proceso sigue vivo: puede reintentar con el mismo checkout.
    state = await instance(async_client, org, instance_id)
    assert state["status"] == "WAITING"
    assert state["current_node_id"] == "esperar_pago"

    retry = await send_provider_event(
        async_client,
        reference=reference,
        provider_reference=checkout.get("provider_reference"),
        status="paid",
        amount_cents=GOLD_TOTAL_CENTS,
    )
    assert retry.status_code == 200
    assert retry.json()["signal"]["resumed"] is True, retry.text

    orders = await fetch_orders(async_client, org)
    assert orders[0]["status"] == "PAID"
    integral = await fetch_stock(org["organization_id"], "ARZ-INT-1KG")
    assert integral["available"] == 14, "el reintento sí confirma el inventario"
    state = await instance(async_client, org, instance_id)
    assert state["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_payment_expired_releases_stock(async_client: AsyncClient) -> None:
    org, _instance_id, _conv, order = await _ready_for_payment(async_client, "Cert PayExpire")
    reference = order["order_number"]
    checkout = await _checkout_of(org["organization_id"], reference)

    response = await send_provider_event(
        async_client,
        reference=reference,
        provider_reference=checkout.get("provider_reference"),
        status="expired",
    )
    assert response.status_code == 200
    assert response.json()["event_type"] == "payment.expired"
    assert await _notifications(org["organization_id"], "payment.expired") >= 1

    integral = await fetch_stock(org["organization_id"], "ARZ-INT-1KG")
    assert integral["reserved"] == 0 and integral["available"] == 15
    orders = await fetch_orders(async_client, org)
    assert orders[0]["status"] == "AWAITING_PAYMENT"


@pytest.mark.asyncio
async def test_checkout_timeout_branch_cancels_order(async_client: AsyncClient) -> None:
    """Sin pago antes del timeout del wait, el flujo deriva a la rama de cierre."""
    org = await ready_tenant(async_client, "Cert PayTimeout", catalog=CATALOG)
    workflow_id = await install_funnel(async_client, org)
    started = await start_funnel(async_client, org, workflow_id, text="quiero 1 kilo de arroz")
    instance_id, conversation_id = started["instance_id"], started["conversation_id"]
    for turn in GOLD_TURNS:
        await say(
            async_client, org, instance_id, text=turn, conversation_id=conversation_id
        )
    state = await instance(async_client, org, instance_id)
    assert state["current_node_id"] == "esperar_pago", state

    await force_wait_deadline(instance_id)
    await force_wait_timeout(async_client, org, instance_id)

    state = await instance(async_client, org, instance_id)
    assert state["status"] == "COMPLETED", state  # la rama de cierre termina el proceso

    orders = await fetch_orders(async_client, org)
    assert orders[0]["status"] == "CANCELLED", orders[0]
    integral = await fetch_stock(org["organization_id"], "ARZ-INT-1KG")
    assert integral["reserved"] == 0, "la rama de timeout libera el inventario"
