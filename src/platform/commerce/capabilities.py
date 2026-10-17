# =============================================================================
# Commerce — ejecutores de capacidad (provider kinds `commerce` y
# `payment_provider` del binder de workflows)
# =============================================================================
# Aquí no hay copia de la lógica de negocio: solo el mapeo
# capacidad → función determinista. Todo dato sale de `store` y de los
# adapters de pago; el LLM no participa en ninguna de estas rutas.
# =============================================================================
from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from src.platform.commerce import contracts as C
from src.platform.commerce import store
from src.platform.commerce.payments import service as payments
from src.platform.commerce.payments.base import PaymentProviderError

COMMERCE_PROVIDER_KIND = C.COMMERCE_PROVIDER_KIND
PAYMENT_PROVIDER_KIND = C.PAYMENT_PROVIDER_KIND


def _dec_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:  # noqa: BLE001
        return None


def _list_arg(value: Any) -> list[dict[str, Any]]:
    """Lista de ítems tolerando JSON-string (las refs del grafo serializan)."""
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, str) and value.strip().startswith("["):
        import json as _json

        try:
            parsed = _json.loads(value)
            if isinstance(parsed, list):
                return [item for item in parsed if isinstance(item, dict)]
        except ValueError:
            return []
    return []


def _uuid_or_none(value: Any) -> UUID | None:
    try:
        return UUID(str(value)) if value else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Capacidades de negocio (catálogo, inventario, ventas)
# ---------------------------------------------------------------------------
async def execute_commerce_capability(
    organization_id: UUID,
    capability_ref: str,
    inputs: dict[str, Any],
    *,
    workspace_id: UUID | None = None,
    instance_id: Any = None,
    node_id: str | None = None,
    workflow_id: Any = None,
    run_id: Any = None,
    binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Ejecuta una capacidad `commerce` del catálogo/inventario/ventas."""
    payload = dict(inputs or {})
    config = dict((binding or {}).get("config") or {})
    warehouse = str(payload.get("warehouse") or config.get("warehouse") or "main")

    if capability_ref == C.CAP_CATALOG_SEARCH:
        return await store.search_products(
            organization_id,
            str(payload.get("query") or ""),
            limit=int(payload.get("limit") or config.get("limit") or 5),
            category=payload.get("category") or config.get("category"),
            warehouse=warehouse,
        )
    if capability_ref == C.CAP_CATALOG_GET:
        quantity = payload.get("quantity")
        unit = payload.get("unit")
        product = None
        found: dict[str, Any] = {}
        if payload.get("product_id") or payload.get("sku"):
            product = await store.get_product(
                organization_id,
                product_id=payload.get("product_id"),
                sku=payload.get("sku"),
            )
            found = {"quantity": quantity, "unit": unit, "product_query": product.get("name") if product else ""}
        elif payload.get("query"):
            found = await store.search_products(
                organization_id, str(payload["query"]), limit=1, warehouse=warehouse
            )
            product = (found.get("products") or [None])[0]
        if product is None:
            return {"product": None, "found": False, "cart_line": None}
        qty = _dec_or_none(quantity if quantity is not None else found.get("quantity")) or Decimal("1")
        resolved_unit = str(unit or found.get("unit") or product.get("unit") or "UNIT")
        line_total = (Decimal(str(product["price"])) * qty).quantize(Decimal("0.01"))
        cart_line = {
            "product_id": product["product_id"],
            "sku": product["sku"],
            "name": product["name"],
            "quantity": float(qty),
            "unit": resolved_unit,
            "unit_price": float(product["price"]),
            "line_total": float(line_total),
            "currency": product["currency"],
        }
        return {"product": product, "found": True, "cart_line": cart_line, "count": 1}
    if capability_ref == C.CAP_CATALOG_PRICE:
        product_id = payload.get("product_id")
        if not product_id and payload.get("sku"):
            product = await store.get_product(organization_id, sku=str(payload["sku"]))
            if product is None:
                raise store.CommerceError("PRODUCT_NOT_FOUND", "producto no encontrado")
            product_id = product["product_id"]
        if not product_id:
            raise store.CommerceError("NEEDS_PRODUCT", "indica product_id o sku")
        return await store.product_price(organization_id, product_id=str(product_id))
    if capability_ref == C.CAP_STOCK_GET:
        product_id = payload.get("product_id")
        if not product_id and payload.get("sku"):
            product = await store.get_product(organization_id, sku=str(payload["sku"]))
            if product is None:
                raise store.CommerceError("PRODUCT_NOT_FOUND", "producto no encontrado")
            product_id = product["product_id"]
        if not product_id:
            raise store.CommerceError("NEEDS_PRODUCT", "indica product_id o sku")
        return await store.stock_get(
            organization_id, product_id=str(product_id), warehouse=warehouse
        )
    if capability_ref == C.CAP_STOCK_RESERVE:
        return await store.stock_reserve(
            organization_id,
            items=_list_arg(payload.get("items")),
            order_id=payload.get("order_id"),
            workflow_instance_id=str(instance_id) if instance_id else payload.get("workflow_instance_id"),
            ttl_seconds=int(payload.get("ttl_seconds") or 1800),
            warehouse=warehouse,
        )
    if capability_ref == C.CAP_STOCK_RELEASE:
        return await store.stock_release(
            organization_id,
            reservation_id=payload.get("reservation_id"),
            order_id=payload.get("order_id"),
        )
    if capability_ref == C.CAP_STOCK_COMMIT:
        return await store.stock_commit(
            organization_id,
            reservation_id=payload.get("reservation_id"),
            order_id=payload.get("order_id"),
        )
    if capability_ref == C.CAP_ORDER_CREATE:
        business_operation_id = str(
            payload.get("business_operation_id")
            or (f"order:{instance_id}" if instance_id else "")
        )
        order = await store.create_order(
            organization_id,
            items=_list_arg(payload.get("items")),
            currency=str(payload.get("currency") or config.get("currency") or "PEN"),
            customer=payload.get("customer") or {},
            cart=payload.get("cart") or {},
            business_operation_id=business_operation_id or None,
            workflow_id=str(workflow_id) if workflow_id else None,
            workflow_instance_id=str(
                payload.get("workflow_instance_id") or instance_id or ""
            )
            or None,
            conversation_id=payload.get("conversation_id"),
            workspace_id=workspace_id,
            status=C.ORDER_AWAITING_CONFIRMATION,
            metadata={
                "reservation_policy": payload.get("reservation_policy")
                or config.get("reservation_policy")
                or C.RESERVATION_POLICY_CHECKOUT,
                "node_id": node_id,
            },
        )
        return {"order": order, **{k: order[k] for k in ("order_id", "order_number", "status", "total", "currency")}}
    if capability_ref == C.CAP_CART_QUOTE:
        return await store.quote_cart(
            organization_id,
            items=_list_arg(payload.get("items")),
            currency=payload.get("currency") or config.get("currency"),
        )
    if capability_ref == C.CAP_ORDER_GET:
        order = await _order_from_inputs(organization_id, payload)
        if order is None:
            raise store.CommerceError("ORDER_NOT_FOUND", "orden no encontrada")
        return {"order": order, **{k: order[k] for k in ("order_id", "order_number", "status", "total", "currency")}}
    if capability_ref == C.CAP_ORDER_CONFIRM:
        return await _transition(organization_id, payload, C.ORDER_AWAITING_PAYMENT)
    if capability_ref == C.CAP_ORDER_MARK_PAID:
        order = await _order_from_inputs(organization_id, payload)
        if order is None:
            raise store.CommerceError("ORDER_NOT_FOUND", "orden no encontrada")
        order = await store.transition_order(
            organization_id,
            order_id=order["order_id"],
            target_status=C.ORDER_PAID,
            payment_reference=payload.get("payment_reference") or order.get("payment_reference"),
            payment_provider=payload.get("provider") or order.get("payment_provider"),
            payment_status="succeeded",
        )
        return {"order": order, **{k: order[k] for k in ("order_id", "order_number", "status", "total", "currency")}}
    if capability_ref == C.CAP_ORDER_FULFILL:
        return await _transition(organization_id, payload, C.ORDER_FULFILLED)
    if capability_ref == C.CAP_ORDER_CANCEL:
        return await _transition(organization_id, payload, C.ORDER_CANCELLED)
    raise store.CommerceError(
        "CAPABILITY_UNKNOWN", f"capacidad commerce no soportada: {capability_ref}"
    )


async def _order_from_inputs(organization_id: UUID, payload: dict[str, Any]) -> dict[str, Any] | None:
    if payload.get("order_id"):
        return await store.get_order(organization_id, order_id=str(payload["order_id"]))
    if payload.get("order_number"):
        return await store.get_order(organization_id, order_number=str(payload["order_number"]))
    if payload.get("payment_reference"):
        return await store.get_order(organization_id, order_number=str(payload["payment_reference"]))
    return None


async def _transition(
    organization_id: UUID, payload: dict[str, Any], target: str
) -> dict[str, Any]:
    order = await _order_from_inputs(organization_id, payload)
    if order is None:
        raise store.CommerceError("ORDER_NOT_FOUND", "orden no encontrada")
    order = await store.transition_order(organization_id, order_id=order["order_id"], target_status=target)
    return {"order": order, **{k: order[k] for k in ("order_id", "order_number", "status", "total", "currency")}}


# ---------------------------------------------------------------------------
# Capacidades de pago (contrato independiente del proveedor)
# ---------------------------------------------------------------------------
async def execute_payment_capability(
    organization_id: UUID,
    capability_ref: str,
    inputs: dict[str, Any],
    *,
    workspace_id: UUID | None = None,
    instance_id: Any = None,
    node_id: str | None = None,
    workflow_id: Any = None,
    run_id: Any = None,
    binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Ejecuta una capacidad `payments.*` con el provider elegido por el tenant."""
    payload = dict(inputs or {})
    if capability_ref == C.CAP_PAYMENT_CHECKOUT_CREATE:
        return await payments.create_checkout(
            organization_id,
            payload,
            workflow_instance_id=str(instance_id) if instance_id else None,
            node_id=node_id,
            workspace_id=workspace_id,
        )
    if capability_ref == C.CAP_PAYMENT_QR_CREATE:
        return await payments.create_qr(organization_id, payload)
    if capability_ref == C.CAP_PAYMENT_STATUS_GET:
        return await payments.payment_status(organization_id, payload)
    if capability_ref == C.CAP_PAYMENT_CANCEL:
        return await payments.cancel_payment(organization_id, payload)
    if capability_ref == C.CAP_PAYMENT_REFUND:
        return await payments.refund_payment(organization_id, payload)
    raise PaymentProviderError(
        "CAPABILITY_UNKNOWN", f"capacidad de pago no soportada: {capability_ref}"
    )


def amount_as_decimal(value: Any) -> Decimal:
    return Decimal(str(value or 0))


__all__ = [
    "COMMERCE_PROVIDER_KIND",
    "PAYMENT_PROVIDER_KIND",
    "execute_commerce_capability",
    "execute_payment_capability",
]
