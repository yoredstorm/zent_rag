# =============================================================================
# P20-17 — E2E de servicio (sin LLM ni proveedor externo).
# =============================================================================
from __future__ import annotations

from uuid import uuid4

from sqlalchemy import text

from src.infrastructure.postgres.session import get_async_session
from src.platform.commerce import cart, store
from src.platform.commerce.capabilities import execute_commerce_capability


async def _cleanup(organization_id) -> None:
    session = await get_async_session()
    try:
        await session.execute(
            text("DELETE FROM commerce_cart_sessions WHERE organization_id = :oid"),
            {"oid": str(organization_id)},
        )
        await session.execute(
            text("DELETE FROM commerce_orders WHERE organization_id = :oid"),
            {"oid": str(organization_id)},
        )
        await session.execute(
            text("DELETE FROM commerce_products WHERE organization_id = :oid"),
            {"oid": str(organization_id)},
        )
        await session.commit()
    finally:
        await session.close()


async def test_retail_service_e2e_cart_order_paid() -> None:
    organization_id = uuid4()
    conversation_id = uuid4()
    try:
        product = await store.upsert_product(
            organization_id,
            sku=f"E2E-{uuid4().hex[:8]}",
            name="Arroz E2E",
            price="4.80",
            currency="PEN",
            unit="kg",
            stock="20",
        )
        await execute_commerce_capability(
            organization_id,
            "sales.cart.add",
            {
                "conversation_id": str(conversation_id),
                "product_id": product["product_id"],
                "quantity": 2,
            },
        )
        created = await execute_commerce_capability(
            organization_id,
            "sales.order.create",
            {"conversation_id": str(conversation_id)},
        )
        order = created["order"]
        assert order["status"] == "AWAITING_PAYMENT"
        assert order["total"] == 9.60

        paid = await execute_commerce_capability(
            organization_id,
            "sales.order.mark_paid",
            {
                "order_id": order["order_id"],
                "payment_reference": "E2E-MANUAL-1",
                "provider": "manual_mvp",
            },
        )
        assert paid["order"]["status"] == "PAID"
        assert paid["order"]["payment_provider"] == "manual_mvp"
        assert paid["order"]["payment_reference"] == "E2E-MANUAL-1"

        assert (
            await cart.get_cart(
                organization_id, conversation_id=conversation_id
            )
        )["count"] == 0
    finally:
        await _cleanup(organization_id)
