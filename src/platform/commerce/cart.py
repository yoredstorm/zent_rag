# =============================================================================
# Commerce — carrito temporal por sesión (P20-10).
# =============================================================================
# El carrito NO es un motor paralelo: es la misma tabla de negocio del tenant y
# las mismas capacidades `sales.cart.*`. Reglas:
#   - la identidad es `organization_id + workspace_id + cart_key`;
#   - `cart_key` sale de la conversación o de la instancia de workflow, nunca
#     del texto libre del cliente;
#   - expira por TTL configurable (workflow o agente) y se purga de forma
#     perezosa al acceder más un barrido periódico;
#   - las cantidades son NUMERIC; los precios se recalculan desde la fuente
#     autorizada, nunca se aceptan del LLM;
#   - toda mutación es CAS por `revision` e idempotente por `idempotency_key`.
# =============================================================================
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session
from src.platform.commerce.store import (
    CommerceError,
    format_cart_summary,
)

logger = get_logger(__name__)

CART_STATUS_ACTIVE = "active"
CART_STATUS_EXPIRED = "expired"
CART_STATUS_CHECKED_OUT = "checked_out"

CART_TTL_DEFAULT_SECONDS = 3600
CART_TTL_MIN_SECONDS = 1
CART_TTL_MAX_SECONDS = 7 * 24 * 3600
CART_MAX_ITEMS = 20

_DDL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS commerce_cart_sessions (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id UUID NOT NULL,
        workspace_id UUID,
        cart_key VARCHAR(200) NOT NULL,
        conversation_id UUID,
        workflow_instance_id UUID,
        user_id UUID,
        status VARCHAR(16) NOT NULL DEFAULT 'active',
        currency CHAR(3) NOT NULL DEFAULT 'PEN',
        revision INTEGER NOT NULL DEFAULT 1,
        ttl_seconds INTEGER NOT NULL DEFAULT 3600,
        expires_at TIMESTAMPTZ NOT NULL,
        metadata JSONB NOT NULL DEFAULT '{}',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_commerce_cart_sessions_key "
    "ON commerce_cart_sessions (organization_id, "
    "COALESCE(workspace_id, '00000000-0000-0000-0000-000000000000'::uuid), "
    "cart_key)",
    "CREATE INDEX IF NOT EXISTS idx_commerce_cart_sessions_expiry "
    "ON commerce_cart_sessions(expires_at)",
    "CREATE INDEX IF NOT EXISTS idx_commerce_cart_sessions_conversation "
    "ON commerce_cart_sessions(organization_id, conversation_id)",
    """
    CREATE TABLE IF NOT EXISTS commerce_cart_items (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id UUID NOT NULL,
        cart_id UUID NOT NULL REFERENCES commerce_cart_sessions(id) ON DELETE CASCADE,
        product_id UUID,
        source_id UUID,
        sku VARCHAR(80) NOT NULL,
        name VARCHAR(240) NOT NULL,
        unit VARCHAR(24) NOT NULL DEFAULT 'UNIT',
        quantity NUMERIC(16,3) NOT NULL,
        unit_price NUMERIC(14,4) NOT NULL DEFAULT 0,
        currency CHAR(3) NOT NULL DEFAULT 'PEN',
        price_source VARCHAR(80) NOT NULL DEFAULT 'commerce',
        metadata JSONB NOT NULL DEFAULT '{}',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_commerce_cart_items_line "
    "ON commerce_cart_items (cart_id, "
    "COALESCE(source_id, '00000000-0000-0000-0000-000000000000'::uuid), sku)",
    "CREATE INDEX IF NOT EXISTS idx_commerce_cart_items_cart "
    "ON commerce_cart_items(cart_id)",
    """
    CREATE TABLE IF NOT EXISTS commerce_cart_operations (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        cart_id UUID NOT NULL REFERENCES commerce_cart_sessions(id) ON DELETE CASCADE,
        organization_id UUID NOT NULL,
        idempotency_key VARCHAR(160) NOT NULL,
        operation VARCHAR(24) NOT NULL,
        result JSONB NOT NULL DEFAULT '{}',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_commerce_cart_operations "
    "ON commerce_cart_operations(cart_id, idempotency_key)",
)

_ENSURED = False


async def ensure_cart_tables() -> None:
    """DDL idempotente (paridad con la migración 180)."""
    global _ENSURED
    if _ENSURED:
        return
    session = await get_async_session()
    try:
        for ddl in _DDL:
            await session.execute(text(ddl))
        await session.commit()
        _ENSURED = True
    except Exception as exc:  # noqa: BLE001
        await session.rollback()
        logger.warning("ensure_cart_tables failed", error=str(exc)[:200])
    finally:
        await session.close()


def normalize_ttl_seconds(value: Any, *, default: int = CART_TTL_DEFAULT_SECONDS) -> int:
    """TTL configurable, acotado para evitar carritos eternos o de un segundo."""
    try:
        ttl = int(value)
    except (TypeError, ValueError):
        ttl = default
    return max(CART_TTL_MIN_SECONDS, min(ttl, CART_TTL_MAX_SECONDS))


def resolve_cart_key(
    *,
    cart_key: str | None = None,
    conversation_id: Any = None,
    workflow_instance_id: Any = None,
) -> str:
    """Identidad de sesión: explícita, conversación o instancia de workflow."""
    raw = str(cart_key or "").strip()
    if not raw:
        if conversation_id:
            raw = f"conversation:{conversation_id}"
        elif workflow_instance_id:
            raw = f"workflow:{workflow_instance_id}"
    if not raw:
        raise CommerceError(
            "CART_SESSION_REQUIRED",
            "falta cart_key, conversation_id o workflow_instance_id",
        )
    return raw[:200]


def _quantity(value: Any) -> Decimal:
    try:
        quantity = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise CommerceError("INVALID_QUANTITY", "cantidad inválida") from exc
    if quantity <= 0:
        raise CommerceError("INVALID_QUANTITY", "la cantidad debe ser positiva")
    if quantity > Decimal("10000"):
        raise CommerceError("INVALID_QUANTITY", "la cantidad excede el máximo")
    return quantity


def _money(value: Any) -> Decimal:
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise CommerceError("INVALID_PRICE", "precio inválido") from exc


def _iso(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


def _workspace_sql() -> str:
    return (
        "AND ((CAST(:ws AS uuid) IS NULL AND workspace_id IS NULL) "
        "OR workspace_id = CAST(:ws AS uuid)) "
    )


async def _purge_expired(session: Any, organization_id: UUID | None) -> None:
    if organization_id is None:
        await session.execute(
            text("DELETE FROM commerce_cart_sessions WHERE expires_at <= NOW()")
        )
        return
    await session.execute(
        text(
            "DELETE FROM commerce_cart_sessions "
            "WHERE organization_id = :oid AND expires_at <= NOW()"
        ),
        {"oid": str(organization_id)},
    )


async def purge_expired_carts(organization_id: UUID | None = None) -> int:
    """Borra carritos vencidos (barrido perezoso o periódico)."""
    session = await get_async_session()
    try:
        result = await session.execute(
            text(
                "DELETE FROM commerce_cart_sessions WHERE expires_at <= NOW()"
                if organization_id is None
                else "DELETE FROM commerce_cart_sessions "
                "WHERE organization_id = :oid AND expires_at <= NOW()"
            ),
            {} if organization_id is None else {"oid": str(organization_id)},
        )
        await session.commit()
        return int(result.rowcount or 0)
    finally:
        await session.close()


async def _select_session(
    session: Any,
    organization_id: UUID,
    *,
    cart_key: str,
    workspace_id: UUID | None,
    user_id: Any = None,
    for_update: bool = False,
) -> Any | None:
    sql = (
        "SELECT id, organization_id, workspace_id, cart_key, conversation_id, "
        "workflow_instance_id, user_id, status, currency, revision, ttl_seconds, "
        "expires_at, metadata, created_at, updated_at "
        "FROM commerce_cart_sessions "
        "WHERE organization_id = :oid AND cart_key = :key "
        "AND status = 'active' AND expires_at > NOW() "
        + _workspace_sql()
        + "AND (CAST(:uid AS uuid) IS NULL OR user_id IS NULL "
        "OR user_id = CAST(:uid AS uuid)) "
    )
    if for_update:
        sql += "FOR UPDATE"
    return (
        await session.execute(
            text(sql),
            {
                "oid": str(organization_id),
                "key": cart_key,
                "ws": workspace_id,
                "uid": user_id,
            },
        )
    ).fetchone()


async def _get_or_create_locked(
    session: Any,
    organization_id: UUID,
    *,
    cart_key: str,
    workspace_id: UUID | None,
    conversation_id: Any = None,
    workflow_instance_id: Any = None,
    user_id: Any = None,
    ttl_seconds: int,
    currency: str,
) -> Any:
    row = await _select_session(
        session,
        organization_id,
        cart_key=cart_key,
        workspace_id=workspace_id,
        user_id=user_id,
        for_update=True,
    )
    if row is not None:
        return row
    inserted = (
        await session.execute(
            text(
                "INSERT INTO commerce_cart_sessions "
                "(organization_id, workspace_id, cart_key, conversation_id, "
                "workflow_instance_id, user_id, currency, ttl_seconds, expires_at) "
                "VALUES (:oid, :ws, :key, :cid, :wid, :uid, :currency, "
                ":ttl_seconds, NOW() + make_interval(secs => :ttl_interval)) "
                "ON CONFLICT DO NOTHING RETURNING id"
            ),
            {
                "oid": str(organization_id),
                "ws": workspace_id,
                "key": cart_key,
                "cid": conversation_id,
                "wid": workflow_instance_id,
                "uid": user_id,
                "currency": (currency or "PEN").upper()[:3],
                "ttl_seconds": ttl_seconds,
                "ttl_interval": float(ttl_seconds),
            },
        )
    ).fetchone()
    if inserted is not None:
        return (
            await session.execute(
                text(
                    "SELECT id, organization_id, workspace_id, cart_key, "
                    "conversation_id, workflow_instance_id, user_id, status, "
                    "currency, revision, ttl_seconds, expires_at, metadata, "
                    "created_at, updated_at FROM commerce_cart_sessions "
                    "WHERE id = :id"
                ),
                {"id": inserted.id},
            )
        ).fetchone()
    row = await _select_session(
        session,
        organization_id,
        cart_key=cart_key,
        workspace_id=workspace_id,
        user_id=user_id,
        for_update=True,
    )
    if row is None:
        raise CommerceError(
            "CART_SESSION_CONFLICT",
            "no se pudo crear ni recuperar el carrito; reintenta",
        )
    return row


async def _load_items(session: Any, cart_id: Any) -> list[Any]:
    return (
        await session.execute(
            text(
                "SELECT id, cart_id, product_id, source_id, sku, name, unit, "
                "quantity, unit_price, currency, price_source, metadata, "
                "created_at, updated_at FROM commerce_cart_items "
                "WHERE cart_id = :cid ORDER BY created_at, id"
            ),
            {"cid": cart_id},
        )
    ).fetchall()


def _key_variants(source_id: Any, sku: str) -> tuple[str, str]:
    source = str(source_id or "")
    return (f"{source}:{sku}", str(sku))


def _override_for(
    overrides: dict[str, Any] | None,
    *,
    source_id: Any,
    sku: str,
) -> dict[str, Any] | None:
    if not overrides:
        return None
    for key in _key_variants(source_id, sku):
        if key in overrides:
            value = overrides[key]
            return value if isinstance(value, dict) else None
    return None


def _line_payload(
    *,
    product_id: Any,
    source_id: Any,
    sku: str,
    name: str,
    unit: str,
    quantity: Any,
    unit_price: Any,
    currency: str,
    price_source: str,
) -> dict[str, Any]:
    qty = Decimal(str(quantity))
    price = Decimal(str(unit_price))
    line_total = (price * qty).quantize(Decimal("0.01"))
    return {
        "product_id": str(product_id) if product_id else None,
        "source_id": str(source_id) if source_id else None,
        "sku": sku,
        "name": name,
        "unit": unit,
        "quantity": float(qty),
        "unit_price": float(price.quantize(Decimal("0.0001"))),
        "line_total": float(line_total),
        "currency": currency,
        "price_source": price_source,
    }


async def _render_cart(
    session: Any,
    organization_id: UUID,
    cart_row: Any,
    *,
    price_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    items = await _load_items(session, cart_row.id)
    lines: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    subtotal = Decimal("0")
    currency = str(cart_row.currency or "PEN").strip().upper() or "PEN"

    for item in items:
        override = _override_for(
            price_overrides, source_id=item.source_id, sku=str(item.sku)
        )
        unit_price = Decimal(str(item.unit_price))
        name = str(item.name)
        unit = str(item.unit)
        item_currency = str(item.currency or currency).strip().upper()
        price_source = str(item.price_source or "commerce")

        if override is not None:
            if override.get("available") is False:
                issues.append(
                    {
                        "sku": str(item.sku),
                        "code": "PRODUCT_UNAVAILABLE",
                        "message": str(override.get("reason") or "sin disponibilidad"),
                    }
                )
                continue
            unit_price = _money(override.get("unit_price"))
            item_currency = str(override.get("currency") or item_currency).upper()[:3]
            name = str(override.get("name") or name)
            unit = str(override.get("unit") or unit)
            price_source = str(override.get("price_source") or price_source)
        elif item.product_id:
            product = (
                await session.execute(
                    text(
                        "SELECT id, name, unit, price, currency, active "
                        "FROM commerce_products WHERE organization_id = :oid "
                        "AND id = :pid LIMIT 1"
                    ),
                    {"oid": str(organization_id), "pid": item.product_id},
                )
            ).fetchone()
            if product is None or not product.active:
                issues.append(
                    {
                        "sku": str(item.sku),
                        "code": "PRODUCT_UNAVAILABLE",
                        "message": "producto inactivo o eliminado del catálogo",
                    }
                )
                continue
            unit_price = _money(product.price)
            item_currency = str(product.currency or item_currency).upper()[:3]
            name = str(product.name)
            unit = str(product.unit or unit)
        # Las líneas externas usan el último precio resuelto por el backend.
        # El tool del agente refresca contra la fuente en cada lectura; si la
        # fuente no responde, el tool falla cerrado y no muestra el total.


        if item_currency != currency:
            issues.append(
                {
                    "sku": str(item.sku),
                    "code": "CURRENCY_MISMATCH",
                    "message": f"moneda {item_currency} distinta de {currency}",
                }
            )
            continue

        line = _line_payload(
            product_id=item.product_id,
            source_id=item.source_id,
            sku=str(item.sku),
            name=name,
            unit=unit,
            quantity=item.quantity,
            unit_price=unit_price,
            currency=item_currency,
            price_source=price_source,
        )
        subtotal += _money(line["line_total"])
        lines.append(line)

    return {
        "cart_id": str(cart_row.id),
        "cart_key": str(cart_row.cart_key),
        "status": str(cart_row.status),
        "revision": int(cart_row.revision),
        "currency": currency,
        "items": lines,
        "issues": issues,
        "count": len(lines),
        "unavailable_count": len(issues),
        "subtotal": float(subtotal.quantize(Decimal("0.01"))),
        "total": float(subtotal.quantize(Decimal("0.01"))),
        "summary": format_cart_summary(lines, subtotal, currency),
        "expires_at": _iso(cart_row.expires_at),
        "ttl_seconds": int(cart_row.ttl_seconds),
        "conversation_id": (
            str(cart_row.conversation_id) if cart_row.conversation_id else None
        ),
        "workflow_instance_id": (
            str(cart_row.workflow_instance_id)
            if cart_row.workflow_instance_id
            else None
        ),
    }


def empty_cart_payload(*, currency: str = "PEN") -> dict[str, Any]:
    return {
        "cart_id": None,
        "cart_key": None,
        "status": "empty",
        "revision": 0,
        "currency": (currency or "PEN").upper()[:3],
        "items": [],
        "issues": [],
        "count": 0,
        "unavailable_count": 0,
        "subtotal": 0.0,
        "total": 0.0,
        "summary": "Tu pedido está vacío.",
        "expires_at": None,
        "ttl_seconds": 0,
        "conversation_id": None,
        "workflow_instance_id": None,
    }


async def get_cart(
    organization_id: UUID,
    *,
    cart_key: str | None = None,
    conversation_id: Any = None,
    workflow_instance_id: Any = None,
    workspace_id: UUID | None = None,
    ttl_seconds: Any = None,
    user_id: Any = None,
    currency: str = "PEN",
    create: bool = False,
    price_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Lee (o crea, si `create=True`) el carrito de la sesión."""
    await ensure_cart_tables()
    key = resolve_cart_key(
        cart_key=cart_key,
        conversation_id=conversation_id,
        workflow_instance_id=workflow_instance_id,
    )
    ttl = normalize_ttl_seconds(ttl_seconds)
    session = await get_async_session()
    try:
        await _purge_expired(session, organization_id)
        cart_row = await _select_session(
            session,
            organization_id,
            cart_key=key,
            workspace_id=workspace_id,
            user_id=user_id,
        )
        if cart_row is None:
            if not create:
                await session.commit()
                payload = empty_cart_payload(currency=currency)
                payload["cart_key"] = key
                payload["conversation_id"] = (
                    str(conversation_id) if conversation_id else None
                )
                payload["workflow_instance_id"] = (
                    str(workflow_instance_id) if workflow_instance_id else None
                )
                return payload
            cart_row = await _get_or_create_locked(
                session,
                organization_id,
                cart_key=key,
                workspace_id=workspace_id,
                conversation_id=conversation_id,
                workflow_instance_id=workflow_instance_id,
                user_id=user_id,
                ttl_seconds=ttl,
                currency=currency,
            )
        payload = await _render_cart(
            session,
            organization_id,
            cart_row,
            price_overrides=price_overrides,
        )
        await session.commit()
        return payload
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def _find_operation(session: Any, cart_id: Any, key: str | None) -> Any | None:
    if not key:
        return None
    return (
        await session.execute(
            text(
                "SELECT result FROM commerce_cart_operations "
                "WHERE cart_id = :cid AND idempotency_key = :key LIMIT 1"
            ),
            {"cid": cart_id, "key": str(key)[:160]},
        )
    ).fetchone()


async def _record_operation(
    session: Any,
    organization_id: UUID,
    cart_id: Any,
    key: str | None,
    operation: str,
    result: dict[str, Any],
) -> None:
    if not key:
        return
    import json as _json

    await session.execute(
        text(
            "INSERT INTO commerce_cart_operations "
            "(cart_id, organization_id, idempotency_key, operation, result) "
            "VALUES (:cid, :oid, :key, :op, CAST(:result AS jsonb)) "
            "ON CONFLICT (cart_id, idempotency_key) DO NOTHING"
        ),
        {
            "cid": cart_id,
            "oid": str(organization_id),
            "key": str(key)[:160],
            "op": operation,
            "result": _json.dumps(result, ensure_ascii=False, default=str),
        },
    )


async def _touch(
    session: Any,
    cart_row: Any,
    *,
    ttl_seconds: int,
) -> tuple[int, Any]:
    row = (
        await session.execute(
            text(
                "UPDATE commerce_cart_sessions SET revision = revision + 1, "
                "expires_at = NOW() + make_interval(secs => :ttl_interval), "
                "ttl_seconds = :ttl_seconds, updated_at = NOW() WHERE id = :id "
                "RETURNING revision, expires_at"
            ),
            {"id": cart_row.id, "ttl_seconds": ttl_seconds, "ttl_interval": float(ttl_seconds)},
        )
    ).fetchone()
    if row is None:
        raise CommerceError("CART_SESSION_NOT_FOUND", "carrito no encontrado")
    return int(row.revision), row.expires_at


def _check_revision(cart_row: Any, expected_revision: Any) -> None:
    if expected_revision in (None, ""):
        return
    try:
        expected = int(expected_revision)
    except (TypeError, ValueError) as exc:
        raise CommerceError("CART_REVISION_INVALID", "revisión inválida") from exc
    if int(cart_row.revision) != expected:
        raise CommerceError(
            "CART_REVISION_CONFLICT",
            f"revisión esperada {expected} pero actual {int(cart_row.revision)}",
        )


async def _resolve_line(
    session: Any,
    organization_id: UUID,
    *,
    product_id: Any = None,
    sku: str | None = None,
    name: str | None = None,
    unit: str | None = None,
    unit_price: Any = None,
    currency: str | None = None,
    source_id: Any = None,
    price_source: str = "commerce",
) -> dict[str, Any]:
    """Resuelve una línea sin aceptar precios del LLM.

    Un `product_id`/SKU del catálogo interno manda: el precio se lee de la BD.
    Una línea externa solo se acepta si el llamador declara `price_source`
    externo, `source_id` y un precio ya resuelto por el backend autorizado.
    """
    if product_id or (sku and not price_source.startswith("external:")):
        if product_id:
            try:
                UUID(str(product_id))
            except (TypeError, ValueError) as exc:
                raise CommerceError(
                    "PRODUCT_ID_INVALID", "product_id inválido"
                ) from exc
        product = (
            await session.execute(
                text(
                    "SELECT id, sku, name, unit, price, currency, active "
                    "FROM commerce_products WHERE organization_id = :oid "
                    "AND (id = :pid OR sku = :sku) LIMIT 1"
                ),
                {
                    "oid": str(organization_id),
                    "pid": product_id,
                    "sku": sku,
                },
            )
        ).fetchone()
        if product is not None:
            if not product.active:
                raise CommerceError(
                    "PRODUCT_UNAVAILABLE", "producto inactivo en el catálogo"
                )
            return {
                "product_id": product.id,
                "source_id": None,
                "sku": str(product.sku),
                "name": str(product.name),
                "unit": str(product.unit or "UNIT"),
                "unit_price": _money(product.price),
                "currency": str(product.currency or currency or "PEN").upper()[:3],
                "price_source": "commerce",
            }
        if not price_source.startswith("external:"):
            raise CommerceError(
                "PRODUCT_NOT_FOUND",
                f"producto no encontrado en el catálogo: {sku or product_id}",
            )

    if unit_price is None:
        raise CommerceError(
            "PRICE_REQUIRED",
            "una línea externa requiere precio resuelto por el backend",
        )
    if not price_source.startswith("external:"):
        raise CommerceError(
            "PRICE_SOURCE_UNTRUSTED",
            "el precio solo se acepta del catálogo o de una fuente externa autorizada",
        )
    if not source_id:
        raise CommerceError(
            "SOURCE_REQUIRED", "una línea externa requiere source_id"
        )
    try:
        UUID(str(source_id))
    except (TypeError, ValueError) as exc:
        raise CommerceError("SOURCE_ID_INVALID", "source_id inválido") from exc
    if not sku:
        raise CommerceError("SKU_REQUIRED", "una línea externa requiere SKU")
    return {
        "product_id": None,
        "source_id": source_id,
        "sku": str(sku)[:80],
        "name": str(name or sku)[:240],
        "unit": str(unit or "UNIT")[:24],
        "unit_price": _money(unit_price),
        "currency": str(currency or "PEN").upper()[:3],
        "price_source": str(price_source)[:80],
    }


async def _mutation_result(
    session: Any,
    organization_id: UUID,
    cart_row: Any,
    *,
    ttl_seconds: int,
    price_overrides: dict[str, Any] | None,
    idempotency_key: str | None,
    operation: str,
) -> dict[str, Any]:
    revision, expires_at = await _touch(session, cart_row, ttl_seconds=ttl_seconds)
    cart_row = SimpleNamespace(
        id=cart_row.id,
        organization_id=cart_row.organization_id,
        cart_key=cart_row.cart_key,
        conversation_id=cart_row.conversation_id,
        workflow_instance_id=cart_row.workflow_instance_id,
        status=cart_row.status,
        currency=cart_row.currency,
        revision=revision,
        ttl_seconds=ttl_seconds,
        expires_at=expires_at,
    )
    payload = await _render_cart(
        session,
        organization_id,
        cart_row,
        price_overrides=price_overrides,
    )
    await _record_operation(
        session,
        organization_id,
        cart_row.id,
        idempotency_key,
        operation,
        payload,
    )
    return payload


async def add_item(
    organization_id: UUID,
    *,
    cart_key: str | None = None,
    conversation_id: Any = None,
    workflow_instance_id: Any = None,
    workspace_id: UUID | None = None,
    ttl_seconds: Any = None,
    user_id: Any = None,
    currency: str = "PEN",
    product_id: Any = None,
    sku: str | None = None,
    name: str | None = None,
    unit: str | None = None,
    unit_price: Any = None,
    source_id: Any = None,
    price_source: str = "commerce",
    quantity: Any = 1,
    expected_revision: Any = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Agrega (o incrementa) una línea. Ignora precios no confiables."""
    await ensure_cart_tables()
    key = resolve_cart_key(
        cart_key=cart_key,
        conversation_id=conversation_id,
        workflow_instance_id=workflow_instance_id,
    )
    ttl = normalize_ttl_seconds(ttl_seconds)
    qty = _quantity(quantity)
    session = await get_async_session()
    try:
        await _purge_expired(session, organization_id)
        line = await _resolve_line(
            session,
            organization_id,
            product_id=product_id,
            sku=sku,
            name=name,
            unit=unit,
            unit_price=unit_price,
            currency=currency,
            source_id=source_id,
            price_source=price_source,
        )
        cart_row = await _get_or_create_locked(
            session,
            organization_id,
            cart_key=key,
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            workflow_instance_id=workflow_instance_id,
            user_id=user_id,
            ttl_seconds=ttl,
            currency=line["currency"],
        )
        replay = await _find_operation(session, cart_row.id, idempotency_key)
        if replay is not None:
            result = dict(replay.result or {})
            result["idempotent_replay"] = True
            await session.commit()
            return result
        _check_revision(cart_row, expected_revision)

        cart_currency = str(cart_row.currency or "PEN").upper()[:3]
        if line["currency"] != cart_currency:
            raise CommerceError(
                "CART_CURRENCY_MISMATCH",
                f"el carrito está en {cart_currency}, la línea en {line['currency']}",
            )
        existing = (
            await session.execute(
                text(
                    "SELECT id, quantity FROM commerce_cart_items "
                    "WHERE cart_id = :cid AND sku = :sku "
                    "AND COALESCE(source_id, '00000000-0000-0000-0000-000000000000'::uuid) "
                    "= COALESCE(CAST(:sid AS uuid), "
                    "'00000000-0000-0000-0000-000000000000'::uuid) LIMIT 1"
                ),
                {"cid": cart_row.id, "sku": line["sku"], "sid": line["source_id"]},
            )
        ).fetchone()
        if existing is not None:
            merged = _quantity(Decimal(str(existing.quantity)) + qty)
            await session.execute(
                text(
                    "UPDATE commerce_cart_items SET quantity = :qty, "
                    "unit_price = :price, name = :name, unit = :unit, "
                    "currency = :currency, price_source = :source, "
                    "updated_at = NOW() WHERE id = :id"
                ),
                {
                    "id": existing.id,
                    "qty": merged,
                    "price": line["unit_price"],
                    "name": line["name"],
                    "unit": line["unit"],
                    "currency": line["currency"],
                    "source": line["price_source"],
                },
            )
        else:
            count = (
                await session.execute(
                    text(
                        "SELECT COUNT(*) AS n FROM commerce_cart_items "
                        "WHERE cart_id = :cid"
                    ),
                    {"cid": cart_row.id},
                )
            ).fetchone()
            if int(count.n or 0) >= CART_MAX_ITEMS:
                raise CommerceError(
                    "CART_ITEM_LIMIT",
                    f"el carrito admite hasta {CART_MAX_ITEMS} líneas",
                )
            await session.execute(
                text(
                    "INSERT INTO commerce_cart_items "
                    "(organization_id, cart_id, product_id, source_id, sku, name, "
                    "unit, quantity, unit_price, currency, price_source) "
                    "VALUES (:oid, :cid, :pid, :sid, :sku, :name, :unit, :qty, "
                    ":price, :currency, :source)"
                ),
                {
                    "oid": str(organization_id),
                    "cid": cart_row.id,
                    "pid": line["product_id"],
                    "sid": line["source_id"],
                    "sku": line["sku"],
                    "name": line["name"],
                    "unit": line["unit"],
                    "qty": qty,
                    "price": line["unit_price"],
                    "currency": line["currency"],
                    "source": line["price_source"],
                },
            )
        payload = await _mutation_result(
            session,
            organization_id,
            cart_row,
            ttl_seconds=ttl,
            price_overrides=(
                {
                    f"{line['source_id']}:{line['sku']}": {
                        "unit_price": line["unit_price"],
                        "currency": line["currency"],
                        "name": line["name"],
                        "unit": line["unit"],
                        "price_source": line["price_source"],
                    }
                }
                if line["source_id"]
                else None
            ),
            idempotency_key=idempotency_key,
            operation="add",
        )
        await session.commit()
        return payload
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def set_quantity(
    organization_id: UUID,
    *,
    cart_key: str | None = None,
    conversation_id: Any = None,
    workflow_instance_id: Any = None,
    workspace_id: UUID | None = None,
    ttl_seconds: Any = None,
    user_id: Any = None,
    sku: str,
    quantity: Any,
    source_id: Any = None,
    expected_revision: Any = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Fija la cantidad de una línea existente (no crea líneas)."""
    await ensure_cart_tables()
    key = resolve_cart_key(
        cart_key=cart_key,
        conversation_id=conversation_id,
        workflow_instance_id=workflow_instance_id,
    )
    ttl = normalize_ttl_seconds(ttl_seconds)
    qty = _quantity(quantity)
    session = await get_async_session()
    try:
        await _purge_expired(session, organization_id)
        cart_row = await _select_session(
            session,
            organization_id,
            cart_key=key,
            workspace_id=workspace_id,
            user_id=user_id,
            for_update=True,
        )
        if cart_row is None:
            raise CommerceError("CART_NOT_FOUND", "no hay carrito activo")
        replay = await _find_operation(session, cart_row.id, idempotency_key)
        if replay is not None:
            result = dict(replay.result or {})
            result["idempotent_replay"] = True
            await session.commit()
            return result
        _check_revision(cart_row, expected_revision)
        updated = await session.execute(
            text(
                "UPDATE commerce_cart_items SET quantity = :qty, updated_at = NOW() "
                "WHERE cart_id = :cid AND sku = :sku "
                "AND COALESCE(source_id, '00000000-0000-0000-0000-000000000000'::uuid) "
                "= COALESCE(CAST(:sid AS uuid), "
                "'00000000-0000-0000-0000-000000000000'::uuid)"
            ),
            {
                "cid": cart_row.id,
                "sku": str(sku)[:80],
                "sid": source_id,
                "qty": qty,
            },
        )
        if int(updated.rowcount or 0) == 0:
            raise CommerceError("CART_ITEM_NOT_FOUND", "línea no encontrada")
        payload = await _mutation_result(
            session,
            organization_id,
            cart_row,
            ttl_seconds=ttl,
            price_overrides=None,
            idempotency_key=idempotency_key,
            operation="set_quantity",
        )
        await session.commit()
        return payload
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def remove_item(
    organization_id: UUID,
    *,
    cart_key: str | None = None,
    conversation_id: Any = None,
    workflow_instance_id: Any = None,
    workspace_id: UUID | None = None,
    ttl_seconds: Any = None,
    user_id: Any = None,
    sku: str,
    source_id: Any = None,
    expected_revision: Any = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Quita una línea; si ya no existe, devuelve el carrito (idempotente)."""
    await ensure_cart_tables()
    key = resolve_cart_key(
        cart_key=cart_key,
        conversation_id=conversation_id,
        workflow_instance_id=workflow_instance_id,
    )
    ttl = normalize_ttl_seconds(ttl_seconds)
    session = await get_async_session()
    try:
        await _purge_expired(session, organization_id)
        cart_row = await _select_session(
            session,
            organization_id,
            cart_key=key,
            workspace_id=workspace_id,
            user_id=user_id,
            for_update=True,
        )
        if cart_row is None:
            raise CommerceError("CART_NOT_FOUND", "no hay carrito activo")
        replay = await _find_operation(session, cart_row.id, idempotency_key)
        if replay is not None:
            result = dict(replay.result or {})
            result["idempotent_replay"] = True
            await session.commit()
            return result
        _check_revision(cart_row, expected_revision)
        await session.execute(
            text(
                "DELETE FROM commerce_cart_items WHERE cart_id = :cid "
                "AND sku = :sku AND "
                "COALESCE(source_id, '00000000-0000-0000-0000-000000000000'::uuid) "
                "= COALESCE(CAST(:sid AS uuid), "
                "'00000000-0000-0000-0000-000000000000'::uuid)"
            ),
            {"cid": cart_row.id, "sku": str(sku)[:80], "sid": source_id},
        )
        payload = await _mutation_result(
            session,
            organization_id,
            cart_row,
            ttl_seconds=ttl,
            price_overrides=None,
            idempotency_key=idempotency_key,
            operation="remove",
        )
        await session.commit()
        return payload
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def clear_cart(
    organization_id: UUID,
    *,
    cart_key: str | None = None,
    conversation_id: Any = None,
    workflow_instance_id: Any = None,
    workspace_id: UUID | None = None,
    ttl_seconds: Any = None,
    user_id: Any = None,
    expected_revision: Any = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Vacía el carrito sin borrar la sesión."""
    await ensure_cart_tables()
    key = resolve_cart_key(
        cart_key=cart_key,
        conversation_id=conversation_id,
        workflow_instance_id=workflow_instance_id,
    )
    ttl = normalize_ttl_seconds(ttl_seconds)
    session = await get_async_session()
    try:
        await _purge_expired(session, organization_id)
        cart_row = await _select_session(
            session,
            organization_id,
            cart_key=key,
            workspace_id=workspace_id,
            user_id=user_id,
            for_update=True,
        )
        if cart_row is None:
            raise CommerceError("CART_NOT_FOUND", "no hay carrito activo")
        replay = await _find_operation(session, cart_row.id, idempotency_key)
        if replay is not None:
            result = dict(replay.result or {})
            result["idempotent_replay"] = True
            await session.commit()
            return result
        _check_revision(cart_row, expected_revision)
        await session.execute(
            text("DELETE FROM commerce_cart_items WHERE cart_id = :cid"),
            {"cid": cart_row.id},
        )
        payload = await _mutation_result(
            session,
            organization_id,
            cart_row,
            ttl_seconds=ttl,
            price_overrides=None,
            idempotency_key=idempotency_key,
            operation="clear",
        )
        await session.commit()
        return payload
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def create_order_from_cart(
    organization_id: UUID,
    *,
    cart_key: str | None = None,
    conversation_id: Any = None,
    workflow_instance_id: Any = None,
    workspace_id: UUID | None = None,
    user_id: Any = None,
    customer: dict[str, Any] | None = None,
    currency: str | None = None,
    business_operation_id: str | None = None,
    workflow_id: Any = None,
    status: str = "AWAITING_PAYMENT",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Cierra una sesión de carrito en una orden ZENT.

    El carrito se bloquea, se recalculan las líneas y se crea una orden
    idempotente. La sesión pasa a `checked_out` y deja de ser reutilizable.
    Las líneas externas usan el último precio resuelto por el backend; las
    internas se revalidan contra `commerce_products`.
    """
    from src.platform.commerce import store

    await ensure_cart_tables()
    key = resolve_cart_key(
        cart_key=cart_key,
        conversation_id=conversation_id,
        workflow_instance_id=workflow_instance_id,
    )
    session = await get_async_session()
    try:
        await _purge_expired(session, organization_id)
        cart_row = await _select_session(
            session,
            organization_id,
            cart_key=key,
            workspace_id=workspace_id,
            user_id=user_id,
            for_update=True,
        )
        if cart_row is None:
            # Reintento idempotente después del checkout: el carrito ya pasó a
            # `checked_out`, pero la conversación conserva su orden pendiente.
            if conversation_id:
                recent = await store.list_orders_by_conversation(
                    organization_id,
                    conversation_id=str(conversation_id),
                    limit=1,
                )
                if recent and recent[0]["status"] in (
                    "AWAITING_PAYMENT",
                    "AWAITING_CONFIRMATION",
                ):
                    return recent[0]
            raise CommerceError("CART_NOT_FOUND", "no hay carrito activo")
        items = await _load_items(session, cart_row.id)
        if not items:
            raise CommerceError("EMPTY_CART", "el carrito está vacío")

        resolved_currency = str(currency or cart_row.currency or "PEN").upper()[:3]
        lines: list[dict[str, Any]] = []
        for item in items:
            item_currency = str(item.currency or resolved_currency).upper()[:3]
            if item_currency != resolved_currency:
                raise CommerceError(
                    "CURRENCY_MISMATCH",
                    f"el carrito está en {item_currency}, la orden en {resolved_currency}",
                )
            name = str(item.name)
            unit = str(item.unit)
            price = Decimal(str(item.unit_price))
            if item.product_id:
                product = (
                    await session.execute(
                        text(
                            "SELECT id, name, unit, price, currency, active "
                            "FROM commerce_products WHERE organization_id = :oid "
                            "AND id = :pid LIMIT 1"
                        ),
                        {"oid": str(organization_id), "pid": item.product_id},
                    )
                ).fetchone()
                if product is None or not product.active:
                    raise CommerceError(
                        "PRODUCT_UNAVAILABLE",
                        f"producto no disponible: {item.sku}",
                    )
                name = str(product.name)
                unit = str(product.unit or unit)
                price = Decimal(str(product.price))
                item_currency = str(product.currency or item_currency).upper()[:3]
            elif not str(item.price_source or "").startswith("external:"):
                raise CommerceError(
                    "PRICE_SOURCE_UNTRUSTED",
                    f"línea externa sin fuente autorizada: {item.sku}",
                )
            lines.append(
                {
                    "product_id": str(item.product_id) if item.product_id else None,
                    "sku": str(item.sku),
                    "name": name,
                    "unit": unit,
                    "quantity": float(Decimal(str(item.quantity))),
                    "unit_price": float(price.quantize(Decimal("0.0001"))),
                    "currency": item_currency,
                    "price_source": str(item.price_source or "commerce"),
                }
            )

        order = await store.create_order_from_snapshot(
            organization_id,
            lines=lines,
            currency=resolved_currency,
            customer=customer or {},
            cart={
                "cart_id": str(cart_row.id),
                "cart_key": str(cart_row.cart_key),
                "revision": int(cart_row.revision),
                "items": lines,
                "summary": format_cart_summary(
                    [
                        {
                            **line,
                            "line_total": float(
                                (
                                    Decimal(str(line["unit_price"]))
                                    * Decimal(str(line["quantity"]))
                                ).quantize(Decimal("0.01"))
                            ),
                        }
                        for line in lines
                    ],
                    sum(
                        Decimal(str(line["unit_price"]))
                        * Decimal(str(line["quantity"]))
                        for line in lines
                    ),
                    resolved_currency,
                ),
            },
            business_operation_id=(
                business_operation_id or f"cart-checkout:{cart_row.id}"
            ),
            workflow_id=str(workflow_id) if workflow_id else None,
            workflow_instance_id=(
                str(workflow_instance_id) if workflow_instance_id else None
            ),
            conversation_id=(
                str(conversation_id)
                if conversation_id
                else (
                    str(cart_row.conversation_id)
                    if cart_row.conversation_id
                    else None
                )
            ),
            workspace_id=workspace_id,
            status=status,
            metadata={
                **(metadata or {}),
                "source": "commerce_cart",
                "cart_id": str(cart_row.id),
                "cart_revision": int(cart_row.revision),
            },
        )
        await session.execute(
            text(
                "UPDATE commerce_cart_sessions SET status = :status, "
                "revision = revision + 1, updated_at = NOW() WHERE id = :id"
            ),
            {"status": CART_STATUS_CHECKED_OUT, "id": cart_row.id},
        )
        await session.commit()
        return order
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def cart_kpis(organization_id: UUID) -> dict[str, Any]:
    """Métricas de carrito para observabilidad del MVP."""
    await ensure_cart_tables()
    session = await get_async_session()
    try:
        status_rows = (
            await session.execute(
                text(
                    "SELECT status, COUNT(*) AS n FROM commerce_cart_sessions "
                    "WHERE organization_id = :oid GROUP BY status"
                ),
                {"oid": str(organization_id)},
            )
        ).fetchall()
        items_row = (
            await session.execute(
                text(
                    "SELECT COUNT(*) AS n FROM commerce_cart_items i "
                    "JOIN commerce_cart_sessions s ON s.id = i.cart_id "
                    "WHERE s.organization_id = :oid AND s.status = 'active'"
                ),
                {"oid": str(organization_id)},
            )
        ).fetchone()
        expiring_row = (
            await session.execute(
                text(
                    "SELECT COUNT(*) AS n FROM commerce_cart_sessions "
                    "WHERE organization_id = :oid AND status = 'active' "
                    "AND expires_at <= NOW() + INTERVAL '5 minutes'"
                ),
                {"oid": str(organization_id)},
            )
        ).fetchone()
    finally:
        await session.close()
    by_status = {str(r.status): int(r.n) for r in status_rows}
    return {
        "carts": {
            "active": by_status.get(CART_STATUS_ACTIVE, 0),
            "checked_out": by_status.get(CART_STATUS_CHECKED_OUT, 0),
            "expired": by_status.get(CART_STATUS_EXPIRED, 0),
            "items_active": int(items_row.n or 0) if items_row else 0,
            "expiring_soon": int(expiring_row.n or 0) if expiring_row else 0,
            "by_status": by_status,
        }
    }


__all__ = [
    "CART_MAX_ITEMS",
    "CART_STATUS_ACTIVE",
    "CART_STATUS_CHECKED_OUT",
    "CART_STATUS_EXPIRED",
    "CART_TTL_DEFAULT_SECONDS",
    "CART_TTL_MAX_SECONDS",
    "CART_TTL_MIN_SECONDS",
    "add_item",
    "cart_kpis",
    "clear_cart",
    "create_order_from_cart",
    "empty_cart_payload",
    "ensure_cart_tables",
    "get_cart",
    "normalize_ttl_seconds",
    "purge_expired_carts",
    "remove_item",
    "resolve_cart_key",
    "set_quantity",
]
