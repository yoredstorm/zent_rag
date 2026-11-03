# =============================================================================
# P20-10 — carrito temporal por sesión, TTL, CAS e idempotencia.
# =============================================================================
from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import text

from src.infrastructure.postgres.session import get_async_session
from src.platform.commerce import cart, store
from src.platform.commerce.capabilities import execute_commerce_capability
from src.platform.commerce.store import CommerceError
from src.platform.workflows.bindings import execute_binding, upsert_binding


async def _cleanup(organization_id) -> None:
    session = await get_async_session()
    try:
        await session.execute(
            text("DELETE FROM commerce_cart_sessions WHERE organization_id = :oid"),
            {"oid": str(organization_id)},
        )
        await session.execute(
            text("DELETE FROM commerce_products WHERE organization_id = :oid"),
            {"oid": str(organization_id)},
        )
        await session.execute(
            text(
                "DELETE FROM workflow_capability_bindings "
                "WHERE organization_id = :oid"
            ),
            {"oid": str(organization_id)},
        )
        await session.commit()
    finally:
        await session.close()


async def _product(organization_id, *, price: str = "4.80", stock: str = "100"):
    return await store.upsert_product(
        organization_id,
        sku=f"P20-{uuid4().hex[:8]}",
        name="Arroz Extra 1 kg",
        price=price,
        currency="PEN",
        unit="kg",
        stock=stock,
    )


def test_ttl_is_clamped_and_cart_key_is_session_scoped() -> None:
    assert cart.normalize_ttl_seconds(None) == cart.CART_TTL_DEFAULT_SECONDS
    assert cart.normalize_ttl_seconds(0) == cart.CART_TTL_MIN_SECONDS
    assert cart.normalize_ttl_seconds(999999999) == cart.CART_TTL_MAX_SECONDS
    assert cart.normalize_ttl_seconds("120") == 120
    assert (
        cart.resolve_cart_key(conversation_id="conv-1") == "conversation:conv-1"
    )
    with pytest.raises(CommerceError) as exc:
        cart.resolve_cart_key()
    assert exc.value.code == "CART_SESSION_REQUIRED"


async def test_cart_decimal_totals_and_mutations() -> None:
    organization_id = uuid4()
    conversation_id = uuid4()
    try:
        product = await _product(organization_id)
        added = await cart.add_item(
            organization_id,
            conversation_id=conversation_id,
            product_id=product["product_id"],
            quantity=2,
            ttl_seconds=60,
        )
        assert added["count"] == 1
        assert added["total"] == 9.60
        assert added["items"][0]["unit_price"] == 4.80
        assert added["items"][0]["line_total"] == 9.60

        fetched = await cart.get_cart(
            organization_id, conversation_id=conversation_id
        )
        assert fetched["total"] == 9.60
        assert fetched["revision"] == added["revision"]

        updated = await cart.set_quantity(
            organization_id,
            conversation_id=conversation_id,
            sku=product["sku"],
            quantity=3,
        )
        assert updated["items"][0]["quantity"] == 3.0
        assert updated["total"] == 14.40

        removed = await cart.remove_item(
            organization_id,
            conversation_id=conversation_id,
            sku=product["sku"],
        )
        assert removed["count"] == 0
        assert removed["total"] == 0.0
    finally:
        await _cleanup(organization_id)


async def test_cart_is_isolated_by_conversation_and_org() -> None:
    organization_id = uuid4()
    other_org = uuid4()
    conversation_id = uuid4()
    try:
        product = await _product(organization_id)
        await cart.add_item(
            organization_id,
            conversation_id=conversation_id,
            product_id=product["product_id"],
            quantity=1,
        )
        assert (
            await cart.get_cart(organization_id, conversation_id=uuid4())
        )["count"] == 0
        assert (
            await cart.get_cart(other_org, conversation_id=conversation_id)
        )["count"] == 0
    finally:
        await _cleanup(organization_id)
        await _cleanup(other_org)


async def test_cart_is_isolated_by_workspace() -> None:
    organization_id = uuid4()
    workspace_a = uuid4()
    workspace_b = uuid4()
    conversation_id = uuid4()
    try:
        product = await _product(organization_id)
        await cart.add_item(
            organization_id,
            conversation_id=conversation_id,
            workspace_id=workspace_a,
            product_id=product["product_id"],
            quantity=1,
        )
        assert (
            await cart.get_cart(
                organization_id,
                conversation_id=conversation_id,
                workspace_id=workspace_a,
            )
        )["count"] == 1
        assert (
            await cart.get_cart(
                organization_id,
                conversation_id=conversation_id,
                workspace_id=workspace_b,
            )
        )["count"] == 0
    finally:
        await _cleanup(organization_id)


async def test_cart_recalculates_price_from_catalog() -> None:
    organization_id = uuid4()
    conversation_id = uuid4()
    try:
        product = await _product(organization_id, price="4.80")
        await cart.add_item(
            organization_id,
            conversation_id=conversation_id,
            product_id=product["product_id"],
            quantity=2,
        )
        await store.upsert_product(
            organization_id,
            sku=product["sku"],
            name="Arroz Extra 1 kg",
            price="5.10",
            currency="PEN",
            unit="kg",
            stock="100",
        )
        refreshed = await cart.get_cart(
            organization_id, conversation_id=conversation_id
        )
        assert refreshed["items"][0]["unit_price"] == 5.10
        assert refreshed["total"] == 10.20
    finally:
        await _cleanup(organization_id)


async def test_cart_expires_and_is_purged() -> None:
    organization_id = uuid4()
    conversation_id = uuid4()
    try:
        product = await _product(organization_id)
        await cart.add_item(
            organization_id,
            conversation_id=conversation_id,
            product_id=product["product_id"],
            quantity=1,
            ttl_seconds=1,
        )
        await asyncio.sleep(1.2)
        expired = await cart.get_cart(
            organization_id, conversation_id=conversation_id
        )
        assert expired["status"] == "empty"
        assert expired["count"] == 0

        session = await get_async_session()
        try:
            rows = (
                await session.execute(
                    text(
                        "SELECT COUNT(*) AS n FROM commerce_cart_sessions "
                        "WHERE organization_id = :oid"
                    ),
                    {"oid": str(organization_id)},
                )
            ).fetchone()
        finally:
            await session.close()
        assert int(rows.n) == 0
    finally:
        await _cleanup(organization_id)


async def test_cart_revision_conflict_fails_closed() -> None:
    organization_id = uuid4()
    conversation_id = uuid4()
    try:
        product = await _product(organization_id)
        await cart.add_item(
            organization_id,
            conversation_id=conversation_id,
            product_id=product["product_id"],
            quantity=1,
        )
        with pytest.raises(CommerceError) as exc:
            await cart.add_item(
                organization_id,
                conversation_id=conversation_id,
                product_id=product["product_id"],
                quantity=1,
                expected_revision=1,
            )
        assert exc.value.code == "CART_REVISION_CONFLICT"
    finally:
        await _cleanup(organization_id)


async def test_cart_idempotency_key_does_not_duplicate() -> None:
    organization_id = uuid4()
    conversation_id = uuid4()
    try:
        product = await _product(organization_id)
        first = await cart.add_item(
            organization_id,
            conversation_id=conversation_id,
            product_id=product["product_id"],
            quantity=2,
            idempotency_key="add-once",
        )
        second = await cart.add_item(
            organization_id,
            conversation_id=conversation_id,
            product_id=product["product_id"],
            quantity=2,
            idempotency_key="add-once",
        )
        assert first["items"][0]["quantity"] == 2.0
        assert second["items"][0]["quantity"] == 2.0
        assert second["idempotent_replay"] is True
    finally:
        await _cleanup(organization_id)


async def test_external_line_requires_authorized_source() -> None:
    organization_id = uuid4()
    try:
        with pytest.raises(CommerceError) as exc:
            await cart.add_item(
                organization_id,
                conversation_id=uuid4(),
                sku="BD-ARROZ-01",
                name="Arroz",
                unit_price="4.80",
                price_source="commerce",
                quantity=1,
            )
        assert exc.value.code == "PRODUCT_NOT_FOUND"

        with pytest.raises(CommerceError) as exc2:
            await cart.add_item(
                organization_id,
                conversation_id=uuid4(),
                sku="BD-ARROZ-01",
                name="Arroz",
                unit_price="4.80",
                price_source="external:bodega",
                quantity=1,
            )
        assert exc2.value.code == "SOURCE_REQUIRED"

        added = await cart.add_item(
            organization_id,
            conversation_id=uuid4(),
            sku="BD-ARROZ-01",
            name="Arroz",
            unit="kg",
            unit_price="4.80",
            currency="PEN",
            source_id=uuid4(),
            price_source="external:bodega.product_catalog_v",
            quantity=1,
        )
        assert added["total"] == 4.80
        assert added["items"][0]["price_source"].startswith("external:")
    finally:
        await _cleanup(organization_id)


async def test_cart_capability_round_trip() -> None:
    organization_id = uuid4()
    conversation_id = uuid4()
    try:
        product = await _product(organization_id, price="2.50")
        added = await execute_commerce_capability(
            organization_id,
            "sales.cart.add",
            {
                "conversation_id": str(conversation_id),
                "product_id": product["product_id"],
                "quantity": 2,
                "ttl_seconds": 120,
            },
        )
        assert added["total"] == 5.0
        fetched = await execute_commerce_capability(
            organization_id,
            "sales.cart.get",
            {"conversation_id": str(conversation_id)},
        )
        assert fetched["count"] == 1
        assert fetched["items"][0]["sku"] == product["sku"]
    finally:
        await _cleanup(organization_id)


async def test_cart_ttl_can_come_from_workflow_binding() -> None:
    organization_id = uuid4()
    conversation_id = uuid4()
    try:
        product = await _product(organization_id)
        added = await execute_commerce_capability(
            organization_id,
            "sales.cart.add",
            {
                "conversation_id": str(conversation_id),
                "product_id": product["product_id"],
                "quantity": 1,
            },
            binding={"config": {"cart_ttl_seconds": 45}},
        )
        assert added["ttl_seconds"] == 45
    finally:
        await _cleanup(organization_id)


async def test_cart_add_executes_through_workflow_binding() -> None:
    organization_id = uuid4()
    conversation_id = uuid4()
    try:
        product = await _product(organization_id, price="3.00")
        await upsert_binding(
            organization_id,
            "sales.cart.add",
            "commerce",
            config={"cart_ttl_seconds": 90},
        )
        result = await execute_binding(
            organization_id,
            "sales.cart.add",
            {
                "conversation_id": str(conversation_id),
                "product_id": product["product_id"],
                "quantity": 2,
            },
        )
        payload = result["output"]
        assert result["provider_kind"] == "commerce"
        assert payload["total"] == 6.0
        assert payload["ttl_seconds"] == 90
    finally:
        await _cleanup(organization_id)
