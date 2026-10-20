# =============================================================================
# Commerce — persistencia de negocio (catálogo, stock, órdenes, checkouts,
# eventos de proveedor). SQL crudo + Postgres, igual que el resto del repo.
# =============================================================================
# Autoridad de datos:
#   - precio y stock viven aquí (no en el prompt ni en el LLM);
#   - el total de una orden se calcula sumando líneas persistidas;
#   - el monto de un checkout se copia de la orden, nunca del input;
#   - toda operación financiera lleva idempotency_key estable.
# =============================================================================
from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session
from src.platform.commerce import contracts as C
from src.platform.commerce.textparse import parse_order_line, token_score

logger = get_logger(__name__)


class CommerceError(Exception):
    """Error de negocio accionable (código estable + mensaje humano)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _f(value: Any) -> float:
    if value is None:
        return 0.0
    return float(Decimal(str(value)))


def _dec(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception as exc:  # noqa: BLE001
        raise CommerceError("INVALID_QUANTITY", f"cantidad inválida: {value}") from exc


#: Símbolo por moneda para los mensajes al cliente (formato determinista: el
#: monto de un mensaje nunca lo redacta el LLM).
CURRENCY_SYMBOLS: dict[str, str] = {
    "PEN": "S/",
    "USD": "$",
    "EUR": "€",
    "MXN": "$",
    "COP": "$",
    "CLP": "$",
    "ARS": "$",
    "BRL": "R$",
}


def format_money(amount: Any, currency: str = "PEN") -> str:
    code = str(currency or "PEN").strip().upper()
    symbol = CURRENCY_SYMBOLS.get(code, f"{code} ")
    return f"{symbol}{Decimal(str(_f(amount))).quantize(Decimal('0.01'))}"


def format_product_list(products: list[dict[str, Any]]) -> str:
    if not products:
        return "No encontré productos para eso."
    lines = ["Tenemos:"]
    for product in products:
        suffix = "" if product.get("available", True) else " (sin stock)"
        lines.append(
            f"- {product.get('name')} — "
            f"{format_money(product.get('price'), str(product.get('currency') or 'PEN'))}{suffix}"
        )
    return "\n".join(lines)


def format_cart_summary(lines: list[dict[str, Any]], total: Any, currency: str = "PEN") -> str:
    if not lines:
        return "Tu pedido está vacío."
    out = ["Tu pedido:"]
    for line in lines:
        unit = str(line.get("unit") or "").lower()
        quantity = line.get("quantity")
        quantity_text = f"{quantity:g}{' ' + unit if unit else ''}" if quantity else ""
        out.append(
            f"- {line.get('name')} x {quantity_text}: "
            f"{format_money(line.get('line_total'), currency)}".replace(" x :", ":")
        )
    out.append(f"Total: {format_money(total, currency)}")
    return "\n".join(out)


def format_payment_instructions(checkout: dict[str, Any]) -> str:
    """Instrucciones de pago listas para enviar (monto formateado server-side)."""
    out = [
        f"Pago pendiente: {format_money(checkout.get('amount'), str(checkout.get('currency') or 'PEN'))}",
        f"Referencia: {checkout.get('reference')}",
    ]
    if checkout.get("qr_payload"):
        out.append(f"QR / link de pago: {checkout['qr_payload']}")
    elif checkout.get("checkout_url"):
        out.append(f"Link de pago: {checkout['checkout_url']}")
    if checkout.get("expires_at"):
        out.append(f"Expira: {checkout['expires_at']}")
    return "\n".join(out)


def stable_operation_key(
    *,
    organization_id: Any,
    workflow_instance_id: Any = None,
    node_id: str | None = None,
    business_operation_id: str = "",
) -> str:
    """Clave idempotente ESTABLE de una operación financiera.

    `organization_id + workflow_instance_id + node_id + business_operation_id`.
    El intento (attempt) NO forma parte de la identidad lógica: un retry repite
    la misma operación, por lo que nunca se crean dos checkouts por un timeout.
    """
    raw = "|".join(
        [
            str(organization_id or ""),
            str(workflow_instance_id or ""),
            str(node_id or ""),
            str(business_operation_id or ""),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:80]


# ---------------------------------------------------------------------------
# DDL (dev/test paridad con la migración 158)
# ---------------------------------------------------------------------------
_DDL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS commerce_products (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id UUID NOT NULL,
        workspace_id UUID,
        sku VARCHAR(64) NOT NULL,
        name VARCHAR(240) NOT NULL,
        description TEXT,
        aliases JSONB NOT NULL DEFAULT '[]',
        category VARCHAR(80),
        unit VARCHAR(16) NOT NULL DEFAULT 'UNIT',
        price NUMERIC(14,4) NOT NULL DEFAULT 0,
        currency CHAR(3) NOT NULL DEFAULT 'PEN',
        tax_rate NUMERIC(6,4) NOT NULL DEFAULT 0,
        active BOOLEAN NOT NULL DEFAULT TRUE,
        metadata JSONB NOT NULL DEFAULT '{}',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_commerce_products_sku "
    "ON commerce_products(organization_id, sku)",
    "CREATE INDEX IF NOT EXISTS idx_commerce_products_org "
    "ON commerce_products(organization_id, active)",
    """
    CREATE TABLE IF NOT EXISTS commerce_stock (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id UUID NOT NULL,
        product_id UUID NOT NULL REFERENCES commerce_products(id) ON DELETE CASCADE,
        warehouse VARCHAR(60) NOT NULL DEFAULT 'main',
        available NUMERIC(16,3) NOT NULL DEFAULT 0,
        reserved NUMERIC(16,3) NOT NULL DEFAULT 0,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_commerce_stock "
    "ON commerce_stock(organization_id, product_id, warehouse)",
    """
    CREATE TABLE IF NOT EXISTS commerce_orders (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id UUID NOT NULL,
        workspace_id UUID,
        order_number VARCHAR(40) NOT NULL,
        status VARCHAR(24) NOT NULL DEFAULT 'DRAFT',
        customer JSONB NOT NULL DEFAULT '{}',
        cart JSONB NOT NULL DEFAULT '{}',
        subtotal NUMERIC(16,2) NOT NULL DEFAULT 0,
        total NUMERIC(16,2) NOT NULL DEFAULT 0,
        currency CHAR(3) NOT NULL DEFAULT 'PEN',
        workflow_id UUID,
        workflow_instance_id UUID,
        conversation_id UUID,
        business_operation_id VARCHAR(160),
        payment_reference VARCHAR(160),
        payment_provider VARCHAR(40),
        payment_status VARCHAR(24),
        reservation_id UUID,
        metadata JSONB NOT NULL DEFAULT '{}',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        paid_at TIMESTAMPTZ,
        fulfilled_at TIMESTAMPTZ
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_commerce_orders_number "
    "ON commerce_orders(organization_id, order_number)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_commerce_orders_operation "
    "ON commerce_orders(organization_id, business_operation_id) "
    "WHERE business_operation_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS idx_commerce_orders_org "
    "ON commerce_orders(organization_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_commerce_orders_instance ON commerce_orders(workflow_instance_id)",
    "CREATE INDEX IF NOT EXISTS idx_commerce_orders_reference ON commerce_orders(payment_reference)",
    """
    CREATE TABLE IF NOT EXISTS commerce_order_items (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id UUID NOT NULL,
        order_id UUID NOT NULL REFERENCES commerce_orders(id) ON DELETE CASCADE,
        product_id UUID,
        sku VARCHAR(64),
        name VARCHAR(240),
        quantity NUMERIC(16,3) NOT NULL,
        unit VARCHAR(16) NOT NULL DEFAULT 'UNIT',
        unit_price NUMERIC(14,4) NOT NULL DEFAULT 0,
        line_total NUMERIC(16,2) NOT NULL DEFAULT 0,
        currency CHAR(3) NOT NULL DEFAULT 'PEN',
        metadata JSONB NOT NULL DEFAULT '{}',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_commerce_order_items_order ON commerce_order_items(order_id)",
    """
    CREATE TABLE IF NOT EXISTS commerce_reservations (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id UUID NOT NULL,
        order_id UUID,
        product_id UUID NOT NULL,
        warehouse VARCHAR(60) NOT NULL DEFAULT 'main',
        quantity NUMERIC(16,3) NOT NULL,
        status VARCHAR(16) NOT NULL DEFAULT 'held',
        workflow_instance_id UUID,
        expires_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_commerce_reservations_order ON commerce_reservations(order_id)",
    """
    CREATE TABLE IF NOT EXISTS commerce_checkout_sessions (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id UUID NOT NULL,
        order_id UUID NOT NULL,
        provider VARCHAR(40) NOT NULL,
        provider_reference VARCHAR(200),
        reference VARCHAR(160) NOT NULL,
        idempotency_key VARCHAR(120) NOT NULL,
        amount NUMERIC(16,2) NOT NULL,
        currency CHAR(3) NOT NULL DEFAULT 'PEN',
        status VARCHAR(24) NOT NULL DEFAULT 'pending',
        checkout_url TEXT,
        qr_payload TEXT,
        qr_image_url TEXT,
        expires_at TIMESTAMPTZ,
        workflow_instance_id UUID,
        node_id VARCHAR(80),
        raw JSONB NOT NULL DEFAULT '{}',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_commerce_checkout_idem "
    "ON commerce_checkout_sessions(organization_id, idempotency_key)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_commerce_checkout_reference "
    "ON commerce_checkout_sessions(organization_id, reference)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_commerce_checkout_provider_ref "
    "ON commerce_checkout_sessions(provider, provider_reference) "
    "WHERE provider_reference IS NOT NULL",
    """
    CREATE TABLE IF NOT EXISTS commerce_payment_providers (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id UUID NOT NULL,
        provider VARCHAR(40) NOT NULL,
        display_name VARCHAR(120),
        status VARCHAR(20) NOT NULL DEFAULT 'connected',
        mode VARCHAR(16) NOT NULL DEFAULT 'test',
        sandbox BOOLEAN NOT NULL DEFAULT FALSE,
        credential_ref UUID,
        config JSONB NOT NULL DEFAULT '{}',
        capabilities JSONB NOT NULL DEFAULT '[]',
        events JSONB NOT NULL DEFAULT '[]',
        health JSONB NOT NULL DEFAULT '{}',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_commerce_payment_providers "
    "ON commerce_payment_providers(organization_id, provider)",
    """
    CREATE TABLE IF NOT EXISTS commerce_provider_events (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        provider VARCHAR(40) NOT NULL,
        provider_event_id VARCHAR(200) NOT NULL,
        event_type VARCHAR(120) NOT NULL,
        organization_id UUID,
        received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        verified BOOLEAN NOT NULL DEFAULT FALSE,
        normalized_event JSONB NOT NULL DEFAULT '{}',
        correlation JSONB NOT NULL DEFAULT '{}',
        processing_status VARCHAR(24) NOT NULL DEFAULT 'received',
        processing_error TEXT,
        signature_mode VARCHAR(40),
        replay_guard_at TIMESTAMPTZ
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_commerce_provider_events "
    "ON commerce_provider_events(provider, provider_event_id)",
    "CREATE INDEX IF NOT EXISTS idx_commerce_provider_events_org "
    "ON commerce_provider_events(organization_id, received_at DESC)",
)


async def ensure_commerce_tables() -> None:
    """DDL idempotente (paridad dev/test con la migración 158)."""
    session = await get_async_session()
    try:
        for ddl in _DDL:
            await session.execute(text(ddl))
        await session.commit()
    except Exception as exc:  # noqa: BLE001
        await session.rollback()
        logger.warning("ensure_commerce_tables failed", error=str(exc)[:200])
    finally:
        await session.close()


# ---------------------------------------------------------------------------
# Catálogo
# ---------------------------------------------------------------------------
def _product_row(r: Any) -> dict[str, Any]:
    return {
        "product_id": str(r.id),
        "sku": str(r.sku),
        "name": str(r.name),
        "description": r.description,
        "unit": str(r.unit),
        "price": _f(r.price),
        "currency": str(r.currency).strip(),
        "category": r.category,
        "aliases": list(r.aliases or []),
        "active": bool(r.active),
        "tax_rate": _f(r.tax_rate),
    }


async def upsert_product(
    organization_id: UUID,
    *,
    sku: str,
    name: str,
    price: Any,
    currency: str = "PEN",
    unit: str = "UNIT",
    description: str | None = None,
    aliases: list[str] | None = None,
    category: str | None = None,
    stock: Any | None = None,
    workspace_id: UUID | None = None,
    warehouse: str = "main",
    tax_rate: Any = 0,
) -> dict[str, Any]:
    """Crea/actualiza un producto y (opcionalmente) su stock inicial."""
    await ensure_commerce_tables()
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO commerce_products (organization_id, workspace_id, sku, name, "
                    "description, aliases, category, unit, price, currency, tax_rate) "
                    "VALUES (:oid, :ws, :sku, :name, :descr, CAST(:aliases AS jsonb), :cat, :unit, "
                    ":price, :cur, :tax) "
                    "ON CONFLICT (organization_id, sku) DO UPDATE SET name = EXCLUDED.name, "
                    "description = EXCLUDED.description, aliases = EXCLUDED.aliases, "
                    "category = EXCLUDED.category, unit = EXCLUDED.unit, price = EXCLUDED.price, "
                    "currency = EXCLUDED.currency, tax_rate = EXCLUDED.tax_rate, "
                    "active = TRUE, updated_at = NOW() "
                    "RETURNING id, sku, name, description, unit, price, currency, category, "
                    "aliases, active, tax_rate"
                ),
                {
                    "oid": str(organization_id),
                    "ws": str(workspace_id) if workspace_id else None,
                    "sku": sku[:64],
                    "name": name[:240],
                    "descr": description,
                    "aliases": json.dumps(list(aliases or []), ensure_ascii=False),
                    "cat": category,
                    "unit": unit[:16],
                    "price": str(_dec(price)),
                    "cur": currency[:3].upper(),
                    "tax": str(_dec(tax_rate)),
                },
            )
        ).fetchone()
        if stock is not None:
            await session.execute(
                text(
                    "INSERT INTO commerce_stock (organization_id, product_id, warehouse, available) "
                    "VALUES (:oid, :pid, :wh, :qty) "
                    "ON CONFLICT (organization_id, product_id, warehouse) DO UPDATE SET "
                    "available = EXCLUDED.available, updated_at = NOW()"
                ),
                {
                    "oid": str(organization_id),
                    "pid": str(row.id),
                    "wh": warehouse[:60],
                    "qty": str(_dec(stock)),
                },
            )
        await session.commit()
    finally:
        await session.close()
    return _product_row(row)


async def get_product(
    organization_id: UUID, *, product_id: str | None = None, sku: str | None = None
) -> dict[str, Any] | None:
    await ensure_commerce_tables()
    session = await get_async_session()
    try:
        if product_id:
            row = (
                await session.execute(
                    text(
                        "SELECT id, sku, name, description, unit, price, currency, category, "
                        "aliases, active, tax_rate FROM commerce_products "
                        "WHERE organization_id = :oid AND id = :pid LIMIT 1"
                    ),
                    {"oid": str(organization_id), "pid": str(product_id)},
                )
            ).fetchone()
        elif sku:
            row = (
                await session.execute(
                    text(
                        "SELECT id, sku, name, description, unit, price, currency, category, "
                        "aliases, active, tax_rate FROM commerce_products "
                        "WHERE organization_id = :oid AND sku = :sku LIMIT 1"
                    ),
                    {"oid": str(organization_id), "sku": sku},
                )
            ).fetchone()
        else:
            return None
    finally:
        await session.close()
    return _product_row(row) if row else None


async def search_products(
    organization_id: UUID,
    query: str,
    *,
    limit: int = 5,
    category: str | None = None,
    warehouse: str = "main",
) -> dict[str, Any]:
    """Búsqueda determinista de catálogo + disponibilidad real.

    Devuelve el contrato normalizado del marketplace:
    `{products: [{product_id, sku, name, unit, price, currency, available}], ...}`
    """
    parsed = parse_order_line(query)
    tokens = parsed["tokens"]
    await ensure_commerce_tables()
    session = await get_async_session()
    try:
        clause = "AND p.category = :cat" if category else ""
        rows = (
            await session.execute(
                text(
                    "SELECT p.id, p.sku, p.name, p.description, p.unit, p.price, p.currency, "
                    "p.category, p.aliases, p.active, p.tax_rate, "
                    "COALESCE(s.available, 0) AS available, COALESCE(s.reserved, 0) AS reserved "
                    "FROM commerce_products p "
                    "LEFT JOIN commerce_stock s ON s.product_id = p.id AND s.warehouse = :wh "
                    "WHERE p.organization_id = :oid AND p.active = TRUE " + clause + " "
                    "ORDER BY p.name LIMIT 200"
                ),
                {"oid": str(organization_id), "wh": warehouse, "cat": category},
            )
        ).fetchall()
    finally:
        await session.close()

    ranked: list[tuple[float, dict[str, Any]]] = []
    for row in rows:
        product = _product_row(row)
        haystacks = [product["name"], product["sku"], *[str(a) for a in product["aliases"]]]
        score = max((token_score(hay, tokens) for hay in haystacks), default=0.0)
        if tokens and score <= 0:
            continue
        product["available"] = _f(row.available) > 0 and _f(row.reserved) < _f(row.available)
        product["stock_available"] = _f(row.available)
        ranked.append((score, product))
    ranked.sort(key=lambda item: (-item[0], item[1]["name"]))
    products = [p for _score, p in ranked[: max(1, min(int(limit or 5), 20))]]
    quantity = Decimal(str(parsed["quantity"])) if parsed.get("quantity") else Decimal("1")
    cart_lines: list[dict[str, Any]] = []
    for product in products:
        unit = str(parsed.get("unit") or product.get("unit") or "UNIT")
        line_total = (Decimal(str(product["price"])) * quantity).quantize(Decimal("0.01"))
        cart_lines.append(
            {
                "product_id": product["product_id"],
                "sku": product["sku"],
                "name": product["name"],
                "quantity": float(quantity),
                "unit": unit,
                "unit_price": float(product["price"]),
                "line_total": float(line_total),
                "currency": product["currency"],
            }
        )
    return {
        "products": products,
        "count": len(products),
        "summary": format_product_list(products),
        "cart_lines": cart_lines,
        "parsed": {
            "product_query": parsed["product_query"],
            "quantity": parsed["quantity"],
            "unit": parsed["unit"],
            "query": query,
        },
    }


async def quote_cart(
    organization_id: UUID,
    *,
    items: list[dict[str, Any]],
    currency: str | None = None,
) -> dict[str, Any]:
    """Cotiza un carrito con precios REALES del catálogo (nunca del LLM).

    No persiste nada: es el paso determinista para mostrar el total antes de
    crear la orden.
    """
    await ensure_commerce_tables()
    session = await get_async_session()
    lines: list[dict[str, Any]] = []
    subtotal = Decimal("0")
    resolved_currency = (currency or "PEN").upper()
    try:
        for item in items:
            product_id = await _resolve_product_id(session, organization_id, item)
            prow = (
                await session.execute(
                    text(
                        "SELECT id, sku, name, unit, price, currency FROM commerce_products "
                        "WHERE organization_id = :oid AND id = :pid AND active = TRUE LIMIT 1"
                    ),
                    {"oid": str(organization_id), "pid": str(product_id)},
                )
            ).fetchone()
            if prow is None:
                raise CommerceError("PRODUCT_NOT_FOUND", "producto no encontrado en el catálogo")
            quantity = _dec(item.get("quantity") or 1)
            if quantity <= 0:
                raise CommerceError("INVALID_QUANTITY", "la cantidad debe ser positiva")
            unit_price = _dec(prow.price)
            line_total = (unit_price * quantity).quantize(Decimal("0.01"))
            subtotal += line_total
            resolved_currency = str(prow.currency).strip() or resolved_currency
            lines.append(
                {
                    "product_id": str(prow.id),
                    "sku": str(prow.sku),
                    "name": str(prow.name),
                    "unit": str(prow.unit),
                    "quantity": float(quantity),
                    "unit_price": float(unit_price),
                    "line_total": float(line_total),
                    "currency": str(prow.currency).strip(),
                }
            )
    finally:
        await session.close()
    return {
        "items": lines,
        "count": len(lines),
        "subtotal": float(subtotal),
        "total": float(subtotal),
        "currency": resolved_currency,
        "summary": format_cart_summary(lines, subtotal, resolved_currency),
    }


async def product_price(organization_id: UUID, *, product_id: str) -> dict[str, Any]:
    product = await get_product(organization_id, product_id=product_id)
    if product is None:
        raise CommerceError("PRODUCT_NOT_FOUND", "producto no encontrado")
    return {
        "product_id": product["product_id"],
        "sku": product["sku"],
        "price": product["price"],
        "currency": product["currency"],
        "unit": product["unit"],
    }


# ---------------------------------------------------------------------------
# Inventario
# ---------------------------------------------------------------------------
async def stock_get(
    organization_id: UUID, *, product_id: str, warehouse: str = "main"
) -> dict[str, Any]:
    await ensure_commerce_tables()
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT p.id, p.sku, p.name, p.unit, p.price, p.currency, "
                    "COALESCE(s.available, 0) AS available, COALESCE(s.reserved, 0) AS reserved, "
                    "s.warehouse AS warehouse "
                    "FROM commerce_products p LEFT JOIN commerce_stock s "
                    "ON s.product_id = p.id AND s.warehouse = :wh "
                    "WHERE p.organization_id = :oid AND p.id = :pid LIMIT 1"
                ),
                {"oid": str(organization_id), "pid": str(product_id), "wh": warehouse},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        raise CommerceError("PRODUCT_NOT_FOUND", "producto no encontrado")
    available = _f(row.available)
    reserved = _f(row.reserved)
    return {
        "product_id": str(row.id),
        "sku": str(row.sku),
        "name": str(row.name),
        "unit": str(row.unit),
        "warehouse": str(row.warehouse or warehouse),
        "available": available,
        "reserved": reserved,
        "in_stock": available > reserved,
        "price": _f(row.price),
        "currency": str(row.currency).strip(),
    }


async def stock_reserve(
    organization_id: UUID,
    *,
    items: list[dict[str, Any]],
    order_id: str | None = None,
    workflow_instance_id: str | None = None,
    ttl_seconds: int | None = 1800,
    warehouse: str = "main",
) -> dict[str, Any]:
    """Reserva stock (available → reserved). Atómico por fila con FOR UPDATE."""
    await ensure_commerce_tables()
    session = await get_async_session()
    created: list[dict[str, Any]] = []
    try:
        for item in items:
            product_id = await _resolve_product_id(session, organization_id, item)
            quantity = _dec(item.get("quantity") or 1)
            if quantity <= 0:
                raise CommerceError("INVALID_QUANTITY", "la cantidad debe ser positiva")
            row = (
                await session.execute(
                    text(
                        "SELECT available, reserved FROM commerce_stock "
                        "WHERE organization_id = :oid AND product_id = :pid AND warehouse = :wh "
                        "FOR UPDATE"
                    ),
                    {"oid": str(organization_id), "pid": str(product_id), "wh": warehouse},
                )
            ).fetchone()
            if row is None:
                raise CommerceError("NO_STOCK_ROW", "el producto no tiene stock configurado")
            available = _dec(row.available)
            reserved = _dec(row.reserved)
            if available - reserved < quantity:
                raise CommerceError(
                    "INSUFFICIENT_STOCK",
                    f"stock insuficiente: disponible {float(available - reserved)}",
                )
            await session.execute(
                text(
                    "UPDATE commerce_stock SET reserved = reserved + :qty, updated_at = NOW() "
                    "WHERE organization_id = :oid AND product_id = :pid AND warehouse = :wh"
                ),
                {"qty": str(quantity), "oid": str(organization_id), "pid": str(product_id), "wh": warehouse},
            )
            expires = _now() + timedelta(seconds=int(ttl_seconds)) if ttl_seconds else None
            res_row = (
                await session.execute(
                    text(
                        "INSERT INTO commerce_reservations (organization_id, order_id, product_id, "
                        "warehouse, quantity, status, workflow_instance_id, expires_at) "
                        "VALUES (:oid, :order_id, :pid, :wh, :qty, 'held', :iid, :exp) "
                        "RETURNING id"
                    ),
                    {
                        "oid": str(organization_id),
                        "order_id": str(order_id) if order_id else None,
                        "pid": str(product_id),
                        "wh": warehouse,
                        "qty": str(quantity),
                        "iid": str(workflow_instance_id) if workflow_instance_id else None,
                        "exp": expires,
                    },
                )
            ).fetchone()
            created.append(
                {
                    "reservation_id": str(res_row.id),
                    "product_id": str(product_id),
                    "quantity": float(quantity),
                    "warehouse": warehouse,
                }
            )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
    return {
        "reservation_id": created[0]["reservation_id"] if created else None,
        "status": C.RESERVATION_HELD,
        "items": created,
    }


async def stock_release(
    organization_id: UUID, *, reservation_id: str | None = None, order_id: str | None = None
) -> dict[str, Any]:
    return await _settle_reservations(
        organization_id, reservation_id=reservation_id, order_id=order_id, mode="release"
    )


async def stock_commit(
    organization_id: UUID, *, reservation_id: str | None = None, order_id: str | None = None
) -> dict[str, Any]:
    return await _settle_reservations(
        organization_id, reservation_id=reservation_id, order_id=order_id, mode="commit"
    )


async def has_held_reservation(organization_id: UUID, *, order_id: str) -> bool:
    """¿La orden tiene todavía una reserva viva? (idempotencia de la reserva)."""
    await ensure_commerce_tables()
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT 1 AS ok FROM commerce_reservations "
                    "WHERE organization_id = :oid AND order_id = :order_id AND status = 'held' "
                    "LIMIT 1"
                ),
                {"oid": str(organization_id), "order_id": str(order_id)},
            )
        ).fetchone()
    finally:
        await session.close()
    return row is not None


async def _settle_reservations(
    organization_id: UUID,
    *,
    reservation_id: str | None,
    order_id: str | None,
    mode: str,
) -> dict[str, Any]:
    """Libera o consume reservas `held`. Idempotente: repetir no vuelve a mover stock."""
    await ensure_commerce_tables()
    session = await get_async_session()
    settled: list[dict[str, Any]] = []
    try:
        filters = ["organization_id = :oid", "status = 'held'"]
        params: dict[str, Any] = {"oid": str(organization_id)}
        if reservation_id:
            filters.append("id = :rid")
            params["rid"] = str(reservation_id)
        elif order_id:
            filters.append("order_id = :order_id")
            params["order_id"] = str(order_id)
        else:
            raise CommerceError("NEEDS_REFERENCE", "indica reservation_id u order_id")
        rows = (
            await session.execute(
                text(
                    "SELECT id, product_id, warehouse, quantity FROM commerce_reservations "
                    "WHERE " + " AND ".join(filters) + " FOR UPDATE"
                ),
                params,
            )
        ).fetchall()
        for row in rows:
            product_id = str(row.product_id)
            warehouse = str(row.warehouse)
            quantity = _dec(row.quantity)
            if mode == "release":
                await session.execute(
                    text(
                        "UPDATE commerce_stock SET reserved = GREATEST(reserved - :qty, 0), "
                        "updated_at = NOW() WHERE organization_id = :oid AND product_id = :pid "
                        "AND warehouse = :wh"
                    ),
                    {"qty": str(quantity), "oid": str(organization_id), "pid": product_id, "wh": warehouse},
                )
                new_status = C.RESERVATION_RELEASED
            else:
                await session.execute(
                    text(
                        "UPDATE commerce_stock SET reserved = GREATEST(reserved - :qty, 0), "
                        "available = GREATEST(available - :qty, 0), updated_at = NOW() "
                        "WHERE organization_id = :oid AND product_id = :pid AND warehouse = :wh"
                    ),
                    {"qty": str(quantity), "oid": str(organization_id), "pid": product_id, "wh": warehouse},
                )
                new_status = C.RESERVATION_COMMITTED
            await session.execute(
                text(
                    "UPDATE commerce_reservations SET status = :st, updated_at = NOW() WHERE id = :rid"
                ),
                {"st": new_status, "rid": str(row.id)},
            )
            settled.append(
                {
                    "reservation_id": str(row.id),
                    "product_id": product_id,
                    "quantity": float(quantity),
                    "status": new_status,
                }
            )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
    return {
        "reservation_id": reservation_id,
        "order_id": order_id,
        "status": "committed" if mode == "commit" else "released",
        "items": settled,
        "moved": bool(settled),
    }


async def _resolve_product_id(session: Any, organization_id: UUID, item: dict[str, Any]) -> str:
    if item.get("product_id"):
        return str(item["product_id"])
    if item.get("sku"):
        row = (
            await session.execute(
                text(
                    "SELECT id FROM commerce_products WHERE organization_id = :oid AND sku = :sku LIMIT 1"
                ),
                {"oid": str(organization_id), "sku": str(item["sku"])},
            )
        ).fetchone()
        if row is None:
            raise CommerceError("PRODUCT_NOT_FOUND", f"sku desconocido: {item['sku']}")
        return str(row.id)
    raise CommerceError("NEEDS_PRODUCT", "cada línea requiere product_id o sku")


# ---------------------------------------------------------------------------
# Órdenes
# ---------------------------------------------------------------------------
async def create_order(
    organization_id: UUID,
    *,
    items: list[dict[str, Any]],
    currency: str = "PEN",
    customer: dict[str, Any] | None = None,
    cart: dict[str, Any] | None = None,
    business_operation_id: str | None = None,
    workflow_id: str | None = None,
    workflow_instance_id: str | None = None,
    conversation_id: str | None = None,
    workspace_id: UUID | None = None,
    status: str = C.ORDER_DRAFT,
    metadata: dict[str, Any] | None = None,
    order_number: str | None = None,
) -> dict[str, Any]:
    """Crea la orden de venta desde líneas de carrito. Precio SIEMPRE del catálogo.

    Idempotente por `business_operation_id`: dos intentos de la misma operación
    lógica devuelven la MISMA orden (nunca dos ventas por un retry).
    """
    await ensure_commerce_tables()
    if not items:
        raise CommerceError("EMPTY_CART", "la orden requiere al menos un ítem")
    if business_operation_id:
        existing = await find_order_by_operation(organization_id, business_operation_id)
        if existing:
            return existing
    session = await get_async_session()
    try:
        number = order_number or await _next_order_number(session, organization_id)
        lines: list[dict[str, Any]] = []
        subtotal = Decimal("0")
        for item in items:
            product_id = await _resolve_product_id(session, organization_id, item)
            prow = (
                await session.execute(
                    text(
                        "SELECT id, sku, name, unit, price, currency FROM commerce_products "
                        "WHERE organization_id = :oid AND id = :pid LIMIT 1"
                    ),
                    {"oid": str(organization_id), "pid": product_id},
                )
            ).fetchone()
            if prow is None:
                raise CommerceError("PRODUCT_NOT_FOUND", "producto no encontrado")
            quantity = _dec(item.get("quantity") or 1)
            if quantity <= 0:
                raise CommerceError("INVALID_QUANTITY", "la cantidad debe ser positiva")
            unit_price = _dec(prow.price)
            line_total = (unit_price * quantity).quantize(Decimal("0.01"))
            subtotal += line_total
            lines.append(
                {
                    "product_id": str(prow.id),
                    "sku": str(prow.sku),
                    "name": str(prow.name),
                    "unit": str(prow.unit),
                    "quantity": float(quantity),
                    "unit_price": float(unit_price),
                    "line_total": float(line_total),
                    "currency": str(prow.currency).strip() or currency,
                }
            )
        total = subtotal
        row = (
            await session.execute(
                text(
                    "INSERT INTO commerce_orders (organization_id, workspace_id, order_number, status, "
                    "customer, cart, subtotal, total, currency, workflow_id, workflow_instance_id, "
                    "conversation_id, business_operation_id, metadata) VALUES (:oid, :ws, :number, :status, "
                    "CAST(:customer AS jsonb), CAST(:cart AS jsonb), :subtotal, :total, :cur, :wf, :iid, "
                    ":conv, :boi, CAST(:meta AS jsonb)) "
                    "ON CONFLICT (organization_id, business_operation_id) WHERE business_operation_id "
                    "IS NOT NULL DO NOTHING "
                    "RETURNING id, order_number, status, subtotal, total, currency, created_at"
                ),
                {
                    "oid": str(organization_id),
                    "ws": str(workspace_id) if workspace_id else None,
                    "number": number,
                    "status": status,
                    "customer": json.dumps(customer or {}, ensure_ascii=False, default=str),
                    "cart": json.dumps(cart or {"items": lines}, ensure_ascii=False, default=str),
                    "subtotal": str(subtotal),
                    "total": str(total),
                    "cur": currency[:3].upper(),
                    "wf": str(workflow_id) if workflow_id else None,
                    "iid": str(workflow_instance_id) if workflow_instance_id else None,
                    "conv": str(conversation_id) if conversation_id else None,
                    "boi": (business_operation_id or None),
                    "meta": json.dumps(metadata or {}, ensure_ascii=False, default=str),
                },
            )
        ).fetchone()
        if row is None:
            # Carrera: otra transacción creó la misma operación lógica.
            await session.rollback()
            existing = await find_order_by_operation(organization_id, business_operation_id or "")
            if existing:
                return existing
            raise CommerceError("ORDER_CONFLICT", "no se pudo crear la orden")
        for line in lines:
            await session.execute(
                text(
                    "INSERT INTO commerce_order_items (organization_id, order_id, product_id, sku, "
                    "name, quantity, unit, unit_price, line_total, currency) VALUES (:oid, :order_id, "
                    ":pid, :sku, :name, :qty, :unit, :price, :line_total, :cur)"
                ),
                {
                    "oid": str(organization_id),
                    "order_id": str(row.id),
                    "pid": line["product_id"],
                    "sku": line["sku"],
                    "name": line["name"],
                    "qty": str(_dec(line["quantity"])),
                    "unit": line["unit"],
                    "price": str(_dec(line["unit_price"])),
                    "line_total": str(_dec(line["line_total"])),
                    "cur": line["currency"],
                },
            )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
    return await get_order(organization_id, order_id=str(row.id))


async def _next_order_number(session: Any, organization_id: UUID) -> str:
    row = (
        await session.execute(
            text("SELECT COUNT(*) AS n FROM commerce_orders WHERE organization_id = :oid"),
            {"oid": str(organization_id)},
        )
    ).fetchone()
    seq = int(row.n or 0) + 1
    stamp = _now().strftime("%y%m%d")
    return f"Z-{stamp}-{seq:05d}-{secrets.token_hex(2).upper()}"


async def get_order(
    organization_id: UUID,
    *,
    order_id: str | None = None,
    order_number: str | None = None,
    business_operation_id: str | None = None,
) -> dict[str, Any] | None:
    await ensure_commerce_tables()
    session = await get_async_session()
    try:
        if order_id:
            where, param = "id = :key", {"key": str(order_id)}
        elif order_number:
            where, param = "order_number = :key", {"key": order_number}
        elif business_operation_id:
            where, param = "business_operation_id = :key", {"key": business_operation_id}
        else:
            return None
        row = (
            await session.execute(
                text(
                    "SELECT id, order_number, status, customer, cart, subtotal, total, currency, "
                    "workflow_id, workflow_instance_id, conversation_id, business_operation_id, "
                    "payment_reference, payment_provider, payment_status, reservation_id, metadata, "
                    "created_at, paid_at, fulfilled_at FROM commerce_orders "
                    f"WHERE organization_id = :oid AND {where} LIMIT 1"
                ),
                {"oid": str(organization_id), **param},
            )
        ).fetchone()
        if row is None:
            return None
        items = (
            await session.execute(
                text(
                    "SELECT product_id, sku, name, quantity, unit, unit_price, line_total, currency "
                    "FROM commerce_order_items WHERE organization_id = :oid AND order_id = :order_id "
                    "ORDER BY created_at"
                ),
                {"oid": str(organization_id), "order_id": str(row.id)},
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "order_id": str(row.id),
        "order_number": str(row.order_number),
        "status": str(row.status),
        "subtotal": _f(row.subtotal),
        "total": _f(row.total),
        "currency": str(row.currency).strip(),
        "customer": dict(row.customer or {}),
        "cart": dict(row.cart or {}),
        "items": [
            {
                "product_id": str(i.product_id) if i.product_id else None,
                "sku": i.sku,
                "name": i.name,
                "quantity": _f(i.quantity),
                "unit": i.unit,
                "unit_price": _f(i.unit_price),
                "line_total": _f(i.line_total),
                "currency": str(i.currency).strip(),
            }
            for i in items
        ],
        "workflow_id": str(row.workflow_id) if row.workflow_id else None,
        "workflow_instance_id": str(row.workflow_instance_id) if row.workflow_instance_id else None,
        "conversation_id": str(row.conversation_id) if row.conversation_id else None,
        "business_operation_id": row.business_operation_id,
        "payment_reference": row.payment_reference,
        "payment_provider": row.payment_provider,
        "payment_status": row.payment_status,
        "reservation_id": str(row.reservation_id) if row.reservation_id else None,
        "metadata": dict(row.metadata or {}),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "paid_at": row.paid_at.isoformat() if row.paid_at else None,
        "fulfilled_at": row.fulfilled_at.isoformat() if row.fulfilled_at else None,
    }


async def find_order_by_operation(
    organization_id: UUID, business_operation_id: str
) -> dict[str, Any] | None:
    if not business_operation_id:
        return None
    return await get_order(organization_id, business_operation_id=business_operation_id)


async def transition_order(
    organization_id: UUID,
    *,
    order_id: str,
    target_status: str,
    payment_reference: str | None = None,
    payment_provider: str | None = None,
    payment_status: str | None = None,
    reservation_id: str | None = None,
) -> dict[str, Any]:
    """Transición de estado de negocio. Idempotente y monotónica."""
    order = await get_order(organization_id, order_id=order_id)
    if order is None:
        raise CommerceError("ORDER_NOT_FOUND", "orden no encontrada")
    current = order["status"]
    if not C.can_transition_order(current, target_status):
        raise CommerceError(
            "INVALID_ORDER_TRANSITION", f"transición no permitida {current} → {target_status}"
        )
    if current == target_status and all(
        v is None for v in (payment_reference, payment_provider, payment_status, reservation_id)
    ):
        return order
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE commerce_orders SET status = :st, "
                "payment_reference = COALESCE(:pref, payment_reference), "
                "payment_provider = COALESCE(:pprov, payment_provider), "
                "payment_status = COALESCE(:pst, payment_status), "
                "reservation_id = COALESCE(CAST(:rid AS uuid), reservation_id), "
                "paid_at = CASE WHEN :mark_paid THEN COALESCE(paid_at, NOW()) ELSE paid_at END, "
                "fulfilled_at = CASE WHEN :mark_fulfilled THEN COALESCE(fulfilled_at, NOW()) "
                "ELSE fulfilled_at END, "
                "updated_at = NOW() WHERE organization_id = :oid AND id = :order_id"
            ),
            {
                "st": target_status,
                "pref": payment_reference,
                "pprov": payment_provider,
                "pst": payment_status,
                "rid": reservation_id,
                "mark_paid": target_status == C.ORDER_PAID,
                "mark_fulfilled": target_status == C.ORDER_FULFILLED,
                "oid": str(organization_id),
                "order_id": str(order_id),
            },
        )
        await session.commit()
    finally:
        await session.close()
    return await get_order(organization_id, order_id=order_id) or order


# ---------------------------------------------------------------------------
# Checkouts (idempotencia financiera extremo a extremo)
# ---------------------------------------------------------------------------
def _checkout_row(r: Any) -> dict[str, Any]:
    return {
        "checkout_id": str(r.id),
        "organization_id": str(r.organization_id) if r.organization_id else None,
        "order_id": str(r.order_id),
        "provider": str(r.provider),
        "reference": str(r.reference),
        "provider_reference": r.provider_reference,
        "amount": _f(r.amount),
        "currency": str(r.currency).strip(),
        "status": str(r.status),
        "checkout_url": r.checkout_url,
        "qr_payload": r.qr_payload,
        "qr_image_url": r.qr_image_url,
        "expires_at": r.expires_at.isoformat() if r.expires_at else None,
        "idempotency_key": str(r.idempotency_key),
        "workflow_instance_id": str(r.workflow_instance_id) if r.workflow_instance_id else None,
        "node_id": r.node_id,
    }


_CHECKOUT_COLS = (
    "id, organization_id, order_id, provider, reference, provider_reference, amount, currency, "
    "status, checkout_url, qr_payload, qr_image_url, expires_at, idempotency_key, "
    "workflow_instance_id, node_id"
)


async def find_checkout(
    organization_id: UUID,
    *,
    idempotency_key: str | None = None,
    reference: str | None = None,
    checkout_id: str | None = None,
    provider_reference: str | None = None,
    provider: str | None = None,
) -> dict[str, Any] | None:
    await ensure_commerce_tables()
    if not any((idempotency_key, reference, checkout_id, provider_reference)):
        return None
    session = await get_async_session()
    try:
        if idempotency_key:
            where, param = "organization_id = :oid AND idempotency_key = :key", idempotency_key
        elif checkout_id:
            where, param = "organization_id = :oid AND id = :key", str(checkout_id)
        else:
            where, param = "organization_id = :oid AND reference = :key", reference
        row = (
            await session.execute(
                text(
                    f"SELECT {_CHECKOUT_COLS} FROM commerce_checkout_sessions WHERE {where} LIMIT 1"
                ),
                {"oid": str(organization_id), "key": param},
            )
        ).fetchone()
        if row is None and provider_reference and provider:
            row = (
                await session.execute(
                    text(
                        f"SELECT {_CHECKOUT_COLS} FROM commerce_checkout_sessions "
                        "WHERE organization_id = :oid AND provider = :prov "
                        "AND provider_reference = :pref LIMIT 1"
                    ),
                    {
                        "oid": str(organization_id),
                        "prov": provider,
                        "pref": str(provider_reference),
                    },
                )
            ).fetchone()
    finally:
        await session.close()
    return _checkout_row(row) if row else None


async def find_checkout_any_tenant(
    *, provider: str, provider_reference: str
) -> dict[str, Any] | None:
    """Resolución de tenant para un webhook entrante (nunca confía en el payload)."""
    await ensure_commerce_tables()
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    f"SELECT {_CHECKOUT_COLS} FROM commerce_checkout_sessions "
                    "WHERE provider = :prov AND provider_reference = :pref LIMIT 1"
                ),
                {"prov": provider, "pref": str(provider_reference)},
            )
        ).fetchone()
    finally:
        await session.close()
    return _checkout_row(row) if row else None


async def find_checkout_by_reference_any_tenant(reference: str) -> dict[str, Any] | None:
    """Reconoce el webhook por nuestra referencia de negocio (order_number)."""
    if not reference:
        return None
    await ensure_commerce_tables()
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    f"SELECT {_CHECKOUT_COLS} FROM commerce_checkout_sessions "
                    "WHERE reference = :ref ORDER BY created_at DESC LIMIT 1"
                ),
                {"ref": str(reference)[:160]},
            )
        ).fetchone()
    finally:
        await session.close()
    return _checkout_row(row) if row else None


async def upsert_checkout_session(
    organization_id: UUID,
    *,
    order_id: str,
    provider: str,
    reference: str,
    idempotency_key: str,
    amount: Any,
    currency: str,
    status: str = "pending",
    provider_reference: str | None = None,
    checkout_url: str | None = None,
    qr_payload: str | None = None,
    qr_image_url: str | None = None,
    expires_at: datetime | None = None,
    workflow_instance_id: str | None = None,
    node_id: str | None = None,
    raw: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Crea el checkout o devuelve el existente de la MISMA operación lógica."""
    await ensure_commerce_tables()
    existing = await find_checkout(organization_id, idempotency_key=idempotency_key)
    if existing:
        return existing
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO commerce_checkout_sessions (organization_id, order_id, provider, "
                    "reference, idempotency_key, amount, currency, status, provider_reference, "
                    "checkout_url, qr_payload, qr_image_url, expires_at, workflow_instance_id, node_id, raw) "
                    "VALUES (:oid, :order_id, :prov, :ref, :idem, :amount, :cur, :st, :pref, :url, "
                    ":qr, :qrimg, :exp, :iid, :node, CAST(:raw AS jsonb)) "
                    "ON CONFLICT (organization_id, idempotency_key) DO NOTHING "
                    f"RETURNING {_CHECKOUT_COLS}"
                ),
                {
                    "oid": str(organization_id),
                    "order_id": str(order_id),
                    "prov": provider[:40],
                    "ref": reference[:160],
                    "idem": idempotency_key[:120],
                    "amount": str(_dec(amount)),
                    "cur": currency[:3].upper(),
                    "st": status,
                    "pref": provider_reference,
                    "url": checkout_url,
                    "qr": qr_payload,
                    "qrimg": qr_image_url,
                    "exp": expires_at,
                    "iid": str(workflow_instance_id) if workflow_instance_id else None,
                    "node": (node_id[:80] if node_id else None),
                    "raw": json.dumps(raw or {}, ensure_ascii=False, default=str),
                },
            )
        ).fetchone()
        if row is None:
            await session.rollback()
            duplicate = await find_checkout(organization_id, idempotency_key=idempotency_key)
            if duplicate:
                return duplicate
            raise CommerceError("CHECKOUT_CONFLICT", "no se pudo crear el checkout")
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
    return _checkout_row(row)


async def update_checkout_status(
    *,
    organization_id: UUID,
    checkout_id: str,
    status: str,
    provider_reference: str | None = None,
    qr_payload: str | None = None,
    qr_image_url: str | None = None,
) -> dict[str, Any] | None:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "UPDATE commerce_checkout_sessions SET status = :st, "
                    "provider_reference = COALESCE(:pref, provider_reference), "
                    "qr_payload = COALESCE(:qr, qr_payload), "
                    "qr_image_url = COALESCE(:qrimg, qr_image_url), updated_at = NOW() "
                    "WHERE organization_id = :oid AND id = :cid "
                    f"RETURNING {_CHECKOUT_COLS}"
                ),
                {
                    "st": status,
                    "pref": provider_reference,
                    "qr": qr_payload,
                    "qrimg": qr_image_url,
                    "oid": str(organization_id),
                    "cid": str(checkout_id),
                },
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    return _checkout_row(row) if row else None


# ---------------------------------------------------------------------------
# Proveedores de pago del tenant
# ---------------------------------------------------------------------------
async def upsert_payment_provider(
    organization_id: UUID,
    *,
    provider: str,
    display_name: str | None = None,
    mode: str = "test",
    sandbox: bool = False,
    credential_ref: str | None = None,
    config: dict[str, Any] | None = None,
    capabilities: list[str] | None = None,
    events: list[str] | None = None,
    status: str = "connected",
    health: dict[str, Any] | None = None,
) -> dict[str, Any]:
    await ensure_commerce_tables()
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO commerce_payment_providers (organization_id, provider, display_name, "
                    "status, mode, sandbox, credential_ref, config, capabilities, events, health) "
                    "VALUES (:oid, :prov, :name, :st, :mode, :sandbox, CAST(:cred AS uuid), "
                    "CAST(:cfg AS jsonb), CAST(:caps AS jsonb), CAST(:evts AS jsonb), CAST(:health AS jsonb)) "
                    "ON CONFLICT (organization_id, provider) DO UPDATE SET display_name = EXCLUDED.display_name, "
                    "status = EXCLUDED.status, mode = EXCLUDED.mode, sandbox = EXCLUDED.sandbox, "
                    "credential_ref = EXCLUDED.credential_ref, config = EXCLUDED.config, "
                    "capabilities = EXCLUDED.capabilities, events = EXCLUDED.events, "
                    "health = EXCLUDED.health, updated_at = NOW() "
                    "RETURNING id, provider, display_name, status, mode, sandbox, credential_ref, config, "
                    "capabilities, events, health, updated_at"
                ),
                {
                    "oid": str(organization_id),
                    "prov": provider[:40],
                    "name": display_name or provider,
                    "st": status,
                    "mode": mode,
                    "sandbox": bool(sandbox),
                    "cred": credential_ref,
                    "cfg": json.dumps(config or {}, ensure_ascii=False, default=str),
                    "caps": json.dumps(list(capabilities or C.PAYMENT_CAPABILITIES), ensure_ascii=False),
                    "evts": json.dumps(list(events or C.PAYMENT_EVENTS), ensure_ascii=False),
                    "health": json.dumps(health or {}, ensure_ascii=False, default=str),
                },
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    return {
        "id": str(row.id),
        "provider": str(row.provider),
        "display_name": row.display_name,
        "status": str(row.status),
        "mode": str(row.mode),
        "sandbox": bool(row.sandbox),
        "credential_ref": str(row.credential_ref) if row.credential_ref else None,
        "config": dict(row.config or {}),
        "capabilities": list(row.capabilities or []),
        "events": list(row.events or []),
        "health": dict(row.health or {}),
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def get_payment_provider(organization_id: UUID, provider: str) -> dict[str, Any] | None:
    await ensure_commerce_tables()
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT id, provider, display_name, status, mode, sandbox, credential_ref, config, "
                    "capabilities, events, health FROM commerce_payment_providers "
                    "WHERE organization_id = :oid AND provider = :prov AND status = 'connected' LIMIT 1"
                ),
                {"oid": str(organization_id), "prov": provider},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        return None
    return {
        "id": str(row.id),
        "provider": str(row.provider),
        "display_name": row.display_name,
        "status": str(row.status),
        "mode": str(row.mode),
        "sandbox": bool(row.sandbox),
        "credential_ref": str(row.credential_ref) if row.credential_ref else None,
        "config": dict(row.config or {}),
        "capabilities": list(row.capabilities or []),
        "events": list(row.events or []),
        "health": dict(row.health or {}),
    }


async def list_payment_providers(organization_id: UUID) -> list[dict[str, Any]]:
    await ensure_commerce_tables()
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT provider, display_name, status, mode, sandbox, capabilities, events, health "
                    "FROM commerce_payment_providers WHERE organization_id = :oid ORDER BY provider"
                ),
                {"oid": str(organization_id)},
            )
        ).fetchall()
    finally:
        await session.close()
    return [
        {
            "provider": str(r.provider),
            "display_name": r.display_name,
            "status": str(r.status),
            "mode": str(r.mode),
            "sandbox": bool(r.sandbox),
            "capabilities": list(r.capabilities or []),
            "events": list(r.events or []),
            "health": dict(r.health or {}),
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Eventos de proveedor (webhook → dedupe → BusinessEvent)
# ---------------------------------------------------------------------------
async def record_provider_event(
    *,
    provider: str,
    provider_event_id: str,
    event_type: str,
    organization_id: str | None,
    verified: bool,
    normalized_event: dict[str, Any],
    correlation: dict[str, Any],
    processing_status: str,
    processing_error: str | None = None,
    signature_mode: str | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """Inserta el evento de proveedor. Devuelve (outcome, fila_existente).

    Dedupe real por constraint (provider, provider_event_id): el mismo webhook
    jamás produce dos efectos de negocio.
    """
    await ensure_commerce_tables()
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO commerce_provider_events (provider, provider_event_id, event_type, "
                    "organization_id, verified, normalized_event, correlation, processing_status, "
                    "processing_error, signature_mode) "
                    "VALUES (:prov, :eid, :etype, :oid, :verified, CAST(:norm AS jsonb), "
                    "CAST(:corr AS jsonb), :pst, :perr, :mode) "
                    "ON CONFLICT (provider, provider_event_id) DO NOTHING RETURNING id"
                ),
                {
                    "prov": provider[:40],
                    "eid": provider_event_id[:200],
                    "etype": event_type[:120],
                    "oid": organization_id,
                    "verified": bool(verified),
                    "norm": json.dumps(normalized_event, ensure_ascii=False, default=str),
                    "corr": json.dumps(correlation, ensure_ascii=False, default=str),
                    "pst": processing_status,
                    "perr": (processing_error or None),
                    "mode": signature_mode,
                },
            )
        ).fetchone()
        if row is None:
            await session.rollback()
            existing = (
                await session.execute(
                    text(
                        "SELECT id, processing_status, organization_id, event_type "
                        "FROM commerce_provider_events "
                        "WHERE provider = :prov AND provider_event_id = :eid LIMIT 1"
                    ),
                    {"prov": provider[:40], "eid": provider_event_id[:200]},
                )
            ).fetchone()
            return "duplicate", (
                {
                    "id": str(existing.id),
                    "processing_status": str(existing.processing_status),
                    "organization_id": (
                        str(existing.organization_id) if existing.organization_id else None
                    ),
                    "event_type": str(existing.event_type),
                }
                if existing
                else None
            )
        await session.commit()
        return "recorded", {"id": str(row.id), "processing_status": processing_status}
    finally:
        await session.close()


async def mark_provider_event(
    provider_event_id: str, *, status: str, error: str | None = None
) -> None:
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE commerce_provider_events SET processing_status = :st, processing_error = :err "
                "WHERE provider_event_id = :eid"
            ),
            {"st": status, "err": (error or None), "eid": provider_event_id[:200]},
        )
        await session.commit()
    finally:
        await session.close()


async def list_provider_events(
    organization_id: UUID, *, limit: int = 50
) -> list[dict[str, Any]]:
    await ensure_commerce_tables()
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT provider, provider_event_id, event_type, received_at, verified, "
                    "normalized_event, correlation, processing_status, processing_error, signature_mode "
                    "FROM commerce_provider_events WHERE organization_id = :oid "
                    "ORDER BY received_at DESC LIMIT :lim"
                ),
                {"oid": str(organization_id), "lim": max(1, min(int(limit), 200))},
            )
        ).fetchall()
    finally:
        await session.close()
    return [
        {
            "provider": str(r.provider),
            "provider_event_id": str(r.provider_event_id),
            "event_type": str(r.event_type),
            "received_at": r.received_at.isoformat() if r.received_at else None,
            "verified": bool(r.verified),
            "normalized_event": dict(r.normalized_event or {}),
            "correlation": dict(r.correlation or {}),
            "processing_status": str(r.processing_status),
            "processing_error": r.processing_error,
            "signature_mode": r.signature_mode,
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# KPIs del embudo (tenant scoped; complemento, no sustituto de analytics)
# ---------------------------------------------------------------------------
async def workflow_kpis(organization_id: UUID, *, workflow_id: str | None = None) -> dict[str, Any]:
    await ensure_commerce_tables()
    session = await get_async_session()
    try:
        wf_filter = "AND workflow_id = CAST(:wf AS uuid)" if workflow_id else ""
        rows = (
            await session.execute(
                text(
                    "SELECT status, COUNT(*) AS n FROM workflow_instances "
                    "WHERE organization_id = :oid " + wf_filter + " GROUP BY status"
                ),
                {"oid": str(organization_id), "wf": workflow_id},
            )
        ).fetchall()
        orders = (
            await session.execute(
                text(
                    "SELECT status, COUNT(*) AS n, COALESCE(SUM(total), 0) AS amount, currency "
                    "FROM commerce_orders WHERE organization_id = :oid GROUP BY status, currency"
                ),
                {"oid": str(organization_id)},
            )
        ).fetchall()
        avg_row = (
            await session.execute(
                text(
                    "SELECT AVG(EXTRACT(EPOCH FROM (completed_at - started_at))) AS avg_seconds "
                    "FROM workflow_instances WHERE organization_id = :oid AND status = 'COMPLETED' "
                    "AND completed_at IS NOT NULL AND started_at IS NOT NULL " + wf_filter
                ),
                {"oid": str(organization_id), "wf": workflow_id},
            )
        ).fetchone()
    finally:
        await session.close()
    by_status = {str(r.status): int(r.n) for r in rows}
    by_order = {str(r.status): int(r.n) for r in orders}
    revenue: dict[str, float] = {}
    for r in orders:
        if str(r.status) in (C.ORDER_PAID, C.ORDER_FULFILLED):
            revenue[str(r.currency).strip()] = revenue.get(str(r.currency).strip(), 0.0) + _f(r.amount)
    return {
        "instances": {
            "active": sum(by_status.get(s, 0) for s in ("NEW", "RUNNING", "WAITING", "SUSPENDED")),
            "waiting_customers": by_status.get("WAITING", 0),
            "completed": by_status.get("COMPLETED", 0),
            "failed": by_status.get("FAILED", 0),
            "expired": by_status.get("EXPIRED", 0),
            "cancelled": by_status.get("CANCELLED", 0),
            "by_status": by_status,
        },
        "orders": {
            "draft": by_order.get(C.ORDER_DRAFT, 0),
            "awaiting_confirmation": by_order.get(C.ORDER_AWAITING_CONFIRMATION, 0),
            "awaiting_payment": by_order.get(C.ORDER_AWAITING_PAYMENT, 0),
            "paid": by_order.get(C.ORDER_PAID, 0),
            "fulfilled": by_order.get(C.ORDER_FULFILLED, 0),
            "cancelled": by_order.get(C.ORDER_CANCELLED, 0),
            "expired": by_order.get(C.ORDER_EXPIRED, 0),
            "abandoned": by_order.get(C.ORDER_AWAITING_PAYMENT, 0) + by_order.get(C.ORDER_EXPIRED, 0),
            "by_status": by_order,
        },
        "sales": {"revenue_paid": revenue},
        "average_completion_seconds": (
            round(_f(avg_row.avg_seconds), 2) if avg_row and avg_row.avg_seconds is not None else None
        ),
    }


async def list_orders(
    organization_id: UUID, *, status: str | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    await ensure_commerce_tables()
    session = await get_async_session()
    try:
        where = "WHERE organization_id = :oid" + (" AND status = :st" if status else "")
        rows = (
            await session.execute(
                text(
                    "SELECT id FROM commerce_orders " + where + " ORDER BY created_at DESC LIMIT :lim"
                ),
                {"oid": str(organization_id), "st": status, "lim": max(1, min(int(limit), 200))},
            )
        ).fetchall()
    finally:
        await session.close()
    out: list[dict[str, Any]] = []
    for row in rows:
        order = await get_order(organization_id, order_id=str(row.id))
        if order:
            out.append(order)
    return out
