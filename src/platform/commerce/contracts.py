# =============================================================================
# Commerce — contratos de capacidades y eventos (independientes del proveedor)
# =============================================================================
# Estos contratos son la frontera estable:
#   - el workflow declara `payments.checkout.create`, nunca "Stripe";
#   - el tenant resuelve la capacidad con un provider (Stripe, IZIPAY, sandbox);
#   - el esquema de entrada/salida es el mismo para todos los providers.
#
# Todo monto es server-side: `amount`/`currency` NUNCA se aceptan del LLM ni del
# input del workflow en operaciones financieras; se leen de la orden persistida.
# =============================================================================
from __future__ import annotations

from typing import Any

# --- Provider kinds del binder ----------------------------------------------
COMMERCE_PROVIDER_KIND = "commerce"
PAYMENT_PROVIDER_KIND = "payment_provider"

# --- Capacidades de catálogo -------------------------------------------------
CAP_CATALOG_SEARCH = "catalog.products.search"
CAP_CATALOG_GET = "catalog.product.get"
CAP_CATALOG_PRICE = "catalog.product.price"

# --- Capacidades de inventario ----------------------------------------------
CAP_STOCK_GET = "inventory.stock.get"
CAP_STOCK_RESERVE = "inventory.reserve"
CAP_STOCK_RELEASE = "inventory.release"
CAP_STOCK_COMMIT = "inventory.commit"

# --- Capacidades de ventas ---------------------------------------------------
CAP_ORDER_CREATE = "sales.order.create"
CAP_CART_QUOTE = "sales.cart.quote"
CAP_ORDER_GET = "sales.order.get"
CAP_ORDER_CONFIRM = "sales.order.confirm"
CAP_ORDER_MARK_PAID = "sales.order.mark_paid"
CAP_ORDER_FULFILL = "sales.order.fulfill"
CAP_ORDER_CANCEL = "sales.order.cancel"

# --- Capacidades de pago (contrato del proveedor, no del proveedor) ---------
CAP_PAYMENT_CHECKOUT_CREATE = "payments.checkout.create"
CAP_PAYMENT_QR_CREATE = "payments.qr.create"
CAP_PAYMENT_STATUS_GET = "payments.status.get"
CAP_PAYMENT_CANCEL = "payments.cancel"
CAP_PAYMENT_REFUND = "payments.refund"

COMMERCE_CAPABILITIES: tuple[str, ...] = (
    CAP_CATALOG_SEARCH,
    CAP_CATALOG_GET,
    CAP_CATALOG_PRICE,
    CAP_STOCK_GET,
    CAP_STOCK_RESERVE,
    CAP_STOCK_RELEASE,
    CAP_STOCK_COMMIT,
    CAP_ORDER_CREATE,
    CAP_CART_QUOTE,
    CAP_ORDER_GET,
    CAP_ORDER_CONFIRM,
    CAP_ORDER_MARK_PAID,
    CAP_ORDER_FULFILL,
    CAP_ORDER_CANCEL,
)

PAYMENT_CAPABILITIES: tuple[str, ...] = (
    CAP_PAYMENT_CHECKOUT_CREATE,
    CAP_PAYMENT_QR_CREATE,
    CAP_PAYMENT_STATUS_GET,
    CAP_PAYMENT_CANCEL,
    CAP_PAYMENT_REFUND,
)

# --- Eventos de negocio normalizados ----------------------------------------
EVENT_PAYMENT_PENDING = "payment.pending"
EVENT_PAYMENT_SUCCEEDED = "payment.succeeded"
EVENT_PAYMENT_FAILED = "payment.failed"
EVENT_PAYMENT_EXPIRED = "payment.expired"
EVENT_PAYMENT_REFUNDED = "payment.refunded"
EVENT_PAYMENT_CANCELLED = "payment.cancelled"

PAYMENT_EVENTS: tuple[str, ...] = (
    EVENT_PAYMENT_PENDING,
    EVENT_PAYMENT_SUCCEEDED,
    EVENT_PAYMENT_FAILED,
    EVENT_PAYMENT_EXPIRED,
    EVENT_PAYMENT_REFUNDED,
)

# --- Estado de la orden (máquina de estados de negocio) ---------------------
ORDER_DRAFT = "DRAFT"
ORDER_AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"
ORDER_AWAITING_PAYMENT = "AWAITING_PAYMENT"
ORDER_PAID = "PAID"
ORDER_FULFILLED = "FULFILLED"
ORDER_CANCELLED = "CANCELLED"
ORDER_EXPIRED = "EXPIRED"

#: Estados posibles de una venta (nombre sin términos verticales en capas
#: genéricas; el catálogo de negocio los documenta como estados de la orden).
SALE_STATUSES: tuple[str, ...] = (
    ORDER_DRAFT,
    ORDER_AWAITING_CONFIRMATION,
    ORDER_AWAITING_PAYMENT,
    ORDER_PAID,
    ORDER_FULFILLED,
    ORDER_CANCELLED,
    ORDER_EXPIRED,
)

ORDER_TRANSITIONS: dict[str, set[str]] = {
    ORDER_DRAFT: {ORDER_AWAITING_CONFIRMATION, ORDER_CANCELLED, ORDER_EXPIRED},
    ORDER_AWAITING_CONFIRMATION: {ORDER_AWAITING_PAYMENT, ORDER_CANCELLED, ORDER_EXPIRED},
    ORDER_AWAITING_PAYMENT: {ORDER_PAID, ORDER_CANCELLED, ORDER_EXPIRED},
    ORDER_PAID: {ORDER_FULFILLED, ORDER_CANCELLED},
    ORDER_FULFILLED: set(),
    ORDER_CANCELLED: set(),
    ORDER_EXPIRED: set(),
}


def can_transition_order(current: str, target: str) -> bool:
    """Transición válida o no-op (idempotencia: mismo estado no es error)."""
    if current == target:
        return True
    return target in ORDER_TRANSITIONS.get(current, set())


# --- Estado de la reserva de inventario -------------------------------------
RESERVATION_HELD = "held"
RESERVATION_COMMITTED = "committed"
RESERVATION_RELEASED = "released"
RESERVATION_EXPIRED = "expired"

# --- Política de reserva (configurable por workflow) ------------------------
RESERVATION_POLICY_CHECKOUT = "checkout"  # reserva al crear checkout (default)
RESERVATION_POLICY_NONE = "none"  # sin reserva; commit al pagar
RESERVATION_POLICY_PAYMENT = "payment"  # reserva solo cuando el pago sucede

RESERVATION_POLICIES: tuple[str, ...] = (
    RESERVATION_POLICY_CHECKOUT,
    RESERVATION_POLICY_NONE,
    RESERVATION_POLICY_PAYMENT,
)

# --- Proveedores de pago soportados -----------------------------------------
PAYMENT_PROVIDERS: tuple[str, ...] = ("izipay", "stripe", "sandbox")
DEFAULT_PAYMENT_PROVIDER = "sandbox"

PROVIDER_SECRET_KEYS: dict[str, tuple[str, ...]] = {
    # IZIPAY (Lykke / monext): comercio + llave de API + llave HMAC de webhook.
    "izipay": ("merchant_code", "api_key", "hash_key"),
    "stripe": ("secret_key", "webhook_secret"),
    # Sandbox determinista: sin secretos reales, secreto local de firma.
    "sandbox": ("webhook_secret",),
}

# --- Esquemas normalizados ---------------------------------------------------
_SEARCH_INPUT: dict[str, Any] = {
    "type": "object",
    "required": ["query"],
    "properties": {
        "query": {"type": "string"},
        "limit": {"type": "integer"},
        "category": {"type": "string"},
    },
}

_SEARCH_OUTPUT: dict[str, Any] = {
    "type": "object",
    "properties": {
        "products": {"type": "array"},
        "cart_lines": {"type": "array"},
        "count": {"type": "integer"},
        "summary": {"type": "string"},
        "parsed": {"type": "object"},
    },
}

_STOCK_GET_INPUT: dict[str, Any] = {
    "type": "object",
    "properties": {
        "product_id": {"type": "string"},
        "sku": {"type": "string"},
        "warehouse": {"type": "string"},
    },
}

_STOCK_MUTATE_INPUT: dict[str, Any] = {
    "type": "object",
    "properties": {
        "order_id": {"type": "string"},
        "reservation_id": {"type": "string"},
        "items": {"type": "array"},
        "ttl_seconds": {"type": "integer"},
    },
}

_ORDER_CREATE_INPUT: dict[str, Any] = {
    "type": "object",
    "required": ["items"],
    "properties": {
        "items": {"type": "array"},
        "customer": {"type": "object"},
        "cart": {"type": "object"},
        "currency": {"type": "string"},
        "business_operation_id": {"type": "string"},
        "workflow_instance_id": {"type": "string"},
        "conversation_id": {"type": "string"},
        "reservation_policy": {"type": "string"},
    },
}

_ORDER_REF_INPUT: dict[str, Any] = {
    "type": "object",
    "properties": {
        "order_id": {"type": "string"},
        "order_number": {"type": "string"},
        "payment_reference": {"type": "string"},
        "provider": {"type": "string"},
        "amount": {"type": "number"},
        "currency": {"type": "string"},
        "payment_status": {"type": "string"},
    },
}

_CHECKOUT_CREATE_INPUT: dict[str, Any] = {
    "type": "object",
    "required": ["order_id"],
    "properties": {
        "order_id": {"type": "string"},
        "order_number": {"type": "string"},
        "provider": {"type": "string"},
        "ttl_seconds": {"type": "integer"},
        "customer": {"type": "object"},
        # `amount`/`currency` se aceptan en el contrato por compatibilidad de
        # forma, pero SIEMPRE se ignoran: el monto sale de la orden persistida.
        "amount": {"type": "number"},
        "currency": {"type": "string"},
    },
}

_CHECKOUT_OUTPUT: dict[str, Any] = {
    "type": "object",
    "properties": {
        "checkout_id": {"type": "string"},
        "order_id": {"type": "string"},
        "order_number": {"type": "string"},
        "provider": {"type": "string"},
        "status": {"type": "string"},
        "amount": {"type": "number"},
        "currency": {"type": "string"},
        "reference": {"type": "string"},
        "qr_payload": {"type": "string"},
        "checkout_url": {"type": "string"},
    },
}

_ORDER_OUTPUT: dict[str, Any] = {
    "type": "object",
    "properties": {
        "order_id": {"type": "string"},
        "order_number": {"type": "string"},
        "status": {"type": "string"},
        "subtotal": {"type": "number"},
        "total": {"type": "number"},
        "currency": {"type": "string"},
        "items": {"type": "array"},
        "customer": {"type": "object"},
        "cart": {"type": "object"},
    },
}

_STOCK_OUTPUT: dict[str, Any] = {
    "type": "object",
    "properties": {
        "order_id": {"type": "string"},
        "reservation_id": {"type": "string"},
        "reserved": {"type": "number"},
        "released": {"type": "number"},
        "committed": {"type": "number"},
        "available": {"type": "number"},
    },
}

#: Contrato declarado por capacidad. `input`/`output` viajan en el binding del
#: tenant (contract_input_schema / contract_output_schema) para que un import
#: pueda avisar "el proveedor no cumple la forma".
CAPABILITY_CONTRACTS: dict[str, dict[str, Any]] = {
    CAP_CATALOG_SEARCH: {"input": _SEARCH_INPUT, "output": _SEARCH_OUTPUT, "read_only": True},
    CAP_CATALOG_GET: {
        "input": {
            "type": "object",
            "properties": {
                "product_id": {"type": "string"},
                "sku": {"type": "string"},
                "query": {"type": "string"},
            },
        },
        "output": {"type": "object", "properties": {"product": {"type": "object"}}},
        "read_only": True,
    },
    CAP_CATALOG_PRICE: {
        "input": {
            "type": "object",
            "properties": {"product_id": {"type": "string"}, "sku": {"type": "string"}},
        },
        "output": {
            "type": "object",
            "properties": {
                "product_id": {"type": "string"},
                "price": {"type": "number"},
                "currency": {"type": "string"},
                "unit": {"type": "string"},
            },
        },
        "read_only": True,
    },
    CAP_STOCK_GET: {
        "input": _STOCK_GET_INPUT,
        "output": {
            "type": "object",
            "properties": {
                "product_id": {"type": "string"},
                "available": {"type": "number"},
                "reserved": {"type": "number"},
                "in_stock": {"type": "boolean"},
            },
        },
        "read_only": True,
    },
    CAP_STOCK_RESERVE: {"input": _STOCK_MUTATE_INPUT, "output": _STOCK_OUTPUT, "read_only": False},
    CAP_STOCK_RELEASE: {"input": _STOCK_MUTATE_INPUT, "output": _STOCK_OUTPUT, "read_only": False},
    CAP_STOCK_COMMIT: {"input": _STOCK_MUTATE_INPUT, "output": _STOCK_OUTPUT, "read_only": False},
    CAP_ORDER_CREATE: {"input": _ORDER_CREATE_INPUT, "output": _ORDER_OUTPUT, "read_only": False},
    CAP_CART_QUOTE: {
        "input": {
            "type": "object",
            "required": ["items"],
            "properties": {"items": {"type": "array"}, "currency": {"type": "string"}},
        },
        "output": {
            "type": "object",
            "properties": {
                "items": {"type": "array"},
                "count": {"type": "integer"},
                "subtotal": {"type": "number"},
                "total": {"type": "number"},
                "currency": {"type": "string"},
            },
        },
        "read_only": True,
    },
    CAP_ORDER_GET: {"input": _ORDER_REF_INPUT, "output": _ORDER_OUTPUT, "read_only": True},
    CAP_ORDER_CONFIRM: {"input": _ORDER_REF_INPUT, "output": _ORDER_OUTPUT, "read_only": False},
    CAP_ORDER_MARK_PAID: {"input": _ORDER_REF_INPUT, "output": _ORDER_OUTPUT, "read_only": False},
    CAP_ORDER_FULFILL: {"input": _ORDER_REF_INPUT, "output": _ORDER_OUTPUT, "read_only": False},
    CAP_ORDER_CANCEL: {"input": _ORDER_REF_INPUT, "output": _ORDER_OUTPUT, "read_only": False},
    CAP_PAYMENT_CHECKOUT_CREATE: {
        "input": _CHECKOUT_CREATE_INPUT,
        "output": _CHECKOUT_OUTPUT,
        "read_only": False,
        "financial": True,
        "idempotency": "required",
    },
    CAP_PAYMENT_QR_CREATE: {
        "input": {
            "type": "object",
            "properties": {"checkout_id": {"type": "string"}, "reference": {"type": "string"}},
        },
        "output": {
            "type": "object",
            "properties": {
                "qr_payload": {"type": "string"},
                "qr_image_url": {"type": "string"},
            },
        },
        "read_only": False,
        "financial": True,
    },
    CAP_PAYMENT_STATUS_GET: {
        "input": {
            "type": "object",
            "properties": {
                "reference": {"type": "string"},
                "order_number": {"type": "string"},
                "checkout_id": {"type": "string"},
            },
        },
        "output": {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "provider": {"type": "string"},
                "amount": {"type": "number"},
                "currency": {"type": "string"},
            },
        },
        "read_only": True,
        "financial": True,
    },
    CAP_PAYMENT_CANCEL: {
        "input": {
            "type": "object",
            "properties": {"checkout_id": {"type": "string"}, "reference": {"type": "string"}},
        },
        "output": {"type": "object", "properties": {"cancelled": {"type": "boolean"}}},
        "read_only": False,
        "financial": True,
        "idempotency": "required",
    },
    CAP_PAYMENT_REFUND: {
        "input": {
            "type": "object",
            "properties": {
                "reference": {"type": "string"},
                "amount": {"type": "number"},
                "reason": {"type": "string"},
            },
        },
        "output": {"type": "object", "properties": {"refunded": {"type": "boolean"}}},
        "read_only": False,
        "financial": True,
        "idempotency": "required",
    },
}


def contract_for(capability_ref: str) -> dict[str, Any]:
    return CAPABILITY_CONTRACTS.get(capability_ref, {})
