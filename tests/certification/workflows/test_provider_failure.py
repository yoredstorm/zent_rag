# =============================================================================
# Certification — fallo del proveedor de pagos
# =============================================================================
# Un timeout del proveedor NO puede crear un segundo cobro. La identidad de la
# operación financiera es estable (organización + instancia + nodo + operación),
# así que un retry repite la MISMA operación lógica y devuelve el mismo
# checkout. Además el circuito del proveedor se abre tras fallos seguidos.
# =============================================================================
from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest
from httpx import AsyncClient

from src.platform.commerce import contracts as C
from src.platform.commerce import store as commerce_store
from src.platform.commerce.payments import service as payment_service
from src.platform.commerce.payments.base import (
    CheckoutRequest,
    CheckoutResult,
    PaymentProviderError,
    PaymentTimeoutError,
)
from src.platform.commerce.payments.providers import SandboxPaymentAdapter
from tests.certification.workflows.gold_support import (
    CATALOG,
    GOLD_TURNS,
    configure_sandbox_payments,
    fetch_orders,
    install_funnel,
    instance,
    ready_tenant,
    say,
    start_funnel,
)


async def _order_ready(client: AsyncClient, name: str) -> tuple[dict, str, dict]:
    org = await ready_tenant(client, name, catalog=CATALOG)
    workflow_id = await install_funnel(client, org)
    started = await start_funnel(client, org, workflow_id, text="quiero 1 kilo de arroz")
    instance_id, conversation_id = started["instance_id"], started["conversation_id"]
    for turn in GOLD_TURNS:
        await say(client, org, instance_id, text=turn, conversation_id=conversation_id)
    orders = await fetch_orders(client, org)
    assert len(orders) == 1, orders
    return org, instance_id, orders[0]


async def _pending_order(client: AsyncClient, name: str) -> tuple[dict, dict]:
    """Orden creada y SIN checkout: el punto exacto antes de cobrar."""
    org = await ready_tenant(client, name, catalog=CATALOG)
    org_id = UUID(str(org["organization_id"]))
    product = await commerce_store.get_product(org_id, sku="ARZ-INT-1KG")
    assert product is not None
    order = await commerce_store.create_order(
        org_id,
        items=[{"product_id": product["product_id"], "quantity": 1}],
        business_operation_id=f"provider-op-{org_id}",
        status=C.ORDER_AWAITING_CONFIRMATION,
    )
    return org, order


@pytest.mark.asyncio
async def test_provider_timeout_then_retry_reuses_same_checkout(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Timeout del proveedor + retry ⇒ un solo checkout, sin doble cobro."""
    org, order = await _pending_order(async_client, "Cert ProviderTimeout")
    org_id = UUID(str(org["organization_id"]))
    order_id = order["order_id"]
    reference = order["order_number"]
    calls = {"n": 0}

    async def _timeout(self, request: CheckoutRequest) -> CheckoutResult:  # noqa: ANN001
        calls["n"] += 1
        raise PaymentTimeoutError("sandbox simulado caído")

    monkeypatch.setattr(SandboxPaymentAdapter, "create_checkout", _timeout)
    with pytest.raises(PaymentTimeoutError):
        await payment_service.create_checkout(
            org_id,
            {"order_id": order_id},
            workflow_instance_id=str(order.get("workflow_instance_id") or "") or None,
            node_id="crear_checkout",
        )
    assert calls["n"] == 1
    # Un timeout no deja checkout huérfano ni marca la orden como pagada.
    assert await commerce_store.find_checkout(org_id, reference=reference) is None
    orders = await fetch_orders(async_client, org)
    assert orders[0]["status"] == "AWAITING_CONFIRMATION"

    monkeypatch.undo()
    first = await payment_service.create_checkout(
        org_id, {"order_id": order_id}, node_id="crear_checkout"
    )
    second = await payment_service.create_checkout(
        org_id, {"order_id": order_id}, node_id="crear_checkout"
    )
    assert first["checkout_id"] == second["checkout_id"], "el retry repite la MISMA operación"
    assert first["amount"] == second["amount"] == pytest.approx(7.20, abs=0.01)

    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT COUNT(*) AS n FROM commerce_checkout_sessions "
                    "WHERE organization_id = :oid AND reference = :ref"
                ),
                {"oid": str(org_id), "ref": reference},
            )
        ).fetchone()
    finally:
        await session.close()
    assert int(row.n) == 1, "un solo checkout para la operación lógica"


@pytest.mark.asyncio
async def test_circuit_breaker_opens_and_fails_fast(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tras varios fallos seguidos el proveedor falla rápido (sin martillar)."""
    org = await ready_tenant(async_client, "Cert Circuit", catalog=CATALOG)
    org_id = UUID(str(org["organization_id"]))
    product = await commerce_store.get_product(org_id, sku="ARZ-INT-1KG")
    assert product is not None
    order = await commerce_store.create_order(
        org_id,
        items=[{"product_id": product["product_id"], "quantity": 1}],
        business_operation_id="circuit-op",
        status=C.ORDER_AWAITING_CONFIRMATION,
    )

    async def _boom(self, request: CheckoutRequest) -> CheckoutResult:  # noqa: ANN001
        raise PaymentProviderError("PROVIDER_UNREACHABLE", "sandbox caído")

    monkeypatch.setattr(SandboxPaymentAdapter, "create_checkout", _boom)
    for attempt in range(5):
        with pytest.raises(PaymentProviderError):
            await payment_service.create_checkout(
                org_id,
                {"order_id": order["order_id"]},
                node_id=f"node-{attempt}",
            )

    record = await commerce_store.get_payment_provider(org_id, "sandbox")
    assert record is not None
    circuit = (record.get("health") or {}).get("circuit") or {}
    assert circuit.get("opened_at"), circuit

    monkeypatch.undo()
    with pytest.raises(PaymentProviderError) as exc:
        await payment_service.create_checkout(
            org_id, {"order_id": order["order_id"]}, node_id="node-after"
        )
    assert exc.value.code == "PROVIDER_CIRCUIT_OPEN"

    # Un cobro sano vuelve a cerrar el circuito (nuevo proveedor configurado).
    await configure_sandbox_payments(org["organization_id"])
    healthy = await payment_service.create_checkout(
        org_id, {"order_id": order["order_id"]}, node_id="node-after"
    )
    assert healthy["status"] == "pending"
    record = await commerce_store.get_payment_provider(org_id, "sandbox")
    circuit = (record or {}).get("health", {}).get("circuit") or {}
    assert int(circuit.get("failures") or 0) == 0, circuit


@pytest.mark.asyncio
async def test_amount_is_server_side_and_ignored_from_input(async_client: AsyncClient) -> None:
    """El monto del cobro sale de la orden, nunca del input del workflow/LLM."""
    org, instance_id, order = await _order_ready(async_client, "Cert Amount")
    org_id = UUID(str(org["organization_id"]))
    assert order["total"] == pytest.approx(11.40, abs=0.01)
    checkout = await payment_service.create_checkout(
        org_id,
        {"order_id": order["order_id"], "amount": 0.01, "currency": "USD"},
        workflow_instance_id=instance_id,
        node_id="crear_checkout",
    )
    assert checkout["amount"] == pytest.approx(11.40, abs=0.01)
    assert checkout["currency"] == "PEN"
    stored = await commerce_store.find_checkout(org_id, reference=order["order_number"])
    assert stored is not None and Decimal(str(stored["amount"])) == Decimal("11.40")
    state = await instance(async_client, org, instance_id)
    assert state["status"] == "WAITING"
