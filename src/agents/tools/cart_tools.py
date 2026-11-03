# =============================================================================
# P20-10 — tools de carrito temporal para el vendedor conversacional.
# =============================================================================
# El carrito vive en `commerce_cart_*` con TTL por sesión. Estas tools:
#   - resuelven el producto y el precio en la fuente externa autorizada;
#   - nunca aceptan precio, total ni "ya pagué" del LLM;
#   - refrescan precios en cada lectura y fallan cerrado si la fuente no responde;
#   - usan `conversation_id` como identidad de sesión.
# =============================================================================
from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any, ClassVar
from uuid import UUID

from src.agents.tools.base import Tool, ToolContext, ToolResult
from src.agents.tools.catalog_tools import (
    _authorized_catalog_source,
    _run_catalog_query,
)
from src.platform.commerce import cart as cart_store

_CATALOG_VIEW = "bodega.product_catalog_v"


def _ttl(ctx: ToolContext) -> int:
    config = dict(ctx.agent_config or {})
    nested = config.get("cart") if isinstance(config.get("cart"), dict) else {}
    return cart_store.normalize_ttl_seconds(
        nested.get("ttl_seconds") or config.get("cart_ttl_seconds")
    )


def _conversation(ctx: ToolContext) -> str:
    if ctx.conversation_id is None:
        raise ValueError(
            "CONVERSATION_REQUIRED: el carrito necesita conversation_id"
        )
    return str(ctx.conversation_id)


def _session_kwargs(
    ctx: ToolContext,
    *,
    workspace_id: UUID | None = None,
) -> dict[str, Any]:
    """Sesión por conversación; el store filtra por user_id cuando existe."""
    conversation = _conversation(ctx)
    return {
        "cart_key": f"conversation:{conversation}",
        "conversation_id": conversation,
        "workspace_id": workspace_id,
        "user_id": ctx.user_id,
        "ttl_seconds": _ttl(ctx),
    }


def _source_workspace(source: dict[str, Any] | None) -> UUID | None:
    raw = (source or {}).get("workspace_id")
    if not raw:
        return None
    try:
        return UUID(str(raw))
    except (TypeError, ValueError):
        return None


async def _workspace_from_source(
    ctx: ToolContext,
) -> tuple[UUID | None, str | None]:
    source, session, error = await _authorized_catalog_source(
        ctx, "store.products.search"
    )
    if error or source is None or session is None:
        return None, error or "SOURCE_UNAVAILABLE"
    workspace_id = _source_workspace(source)
    await session.close()
    return workspace_id, None


def _dump(payload: dict[str, Any], *, status: str = "OK") -> ToolResult:
    cart_id = payload.get("cart_id")
    revision = payload.get("revision")
    ref = f"cart:{cart_id}" if cart_id else f"cart:{payload.get('cart_key') or 'session'}"
    evidence = [
        {
            "ref": f"{ref}:rev{revision}",
            "content": json.dumps(
                {
                    "source": "commerce_cart",
                    "cart_id": cart_id,
                    "status": payload.get("status"),
                    "revision": revision,
                    "currency": payload.get("currency"),
                    "items": payload.get("items") or [],
                    "total": payload.get("total"),
                    "summary": payload.get("summary"),
                    "expires_at": payload.get("expires_at"),
                },
                ensure_ascii=False,
                default=str,
            ),
            "source_type": "commerce_cart",
            "title": "Carrito de la conversación",
            "retrieval": "commerce_cart",
            "ref_id": cart_id or payload.get("cart_key"),
        }
    ]
    return ToolResult(
        output=json.dumps(
            {"status": status, "data": payload},
            ensure_ascii=False,
            default=str,
        ),
        meta={
            "status": status,
            "cart_id": cart_id,
            "source_ref": ref,
            "evidence": evidence,
        },
    )


def _money(value: Any) -> str:
    try:
        return str(Decimal(str(value)).quantize(Decimal("0.01")))
    except (InvalidOperation, TypeError, ValueError):
        return str(value)


def _product_override(row: Any) -> dict[str, Any]:
    def field(name: str) -> Any:
        return row.get(name) if isinstance(row, dict) else getattr(row, name)

    return {
        "sku": str(field("sku")),
        "name": str(field("name")),
        "unit": str(field("unit") or "UNIT"),
        "unit_price": _money(field("price")),
        "currency": str(field("currency") or "PEN").strip().upper(),
        "available": True,
        "price_source": f"external:{_CATALOG_VIEW}",
    }


async def _product_row(session: Any, sku: str) -> dict[str, Any] | None:
    rows = await _run_catalog_query(
        session,
        "SELECT sku, name, unit, price, currency, available "
        "FROM bodega.product_catalog_v WHERE sku = :sku LIMIT 1",
        {"sku": sku},
    )
    return rows[0] if rows else None


async def _price_overrides(
    session: Any,
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    skus = [str(item.get("sku") or "") for item in items if item.get("sku")]
    if not skus:
        return {}
    placeholders = ", ".join(f":s{index}" for index in range(len(skus)))
    rows = await _run_catalog_query(
        session,
        "SELECT sku, name, unit, price, currency, available "  # noqa: S608
        f"FROM {_CATALOG_VIEW} WHERE sku IN ({placeholders})",
        {f"s{index}": sku for index, sku in enumerate(skus)},
    )
    found = {str(row["sku"]): row for row in rows}
    overrides: dict[str, Any] = {}
    for sku in skus:
        row = found.get(sku)
        if row is None:
            overrides[sku] = {
                "available": False,
                "reason": "SKU no existe en la fuente autorizada",
            }
            continue
        overrides[sku] = _product_override(row)
    return overrides


async def _refresh(
    ctx: ToolContext,
    session: Any,
    payload: dict[str, Any],
    *,
    workspace_id: UUID | None,
) -> dict[str, Any]:
    items = payload.get("items") or []
    if not items:
        return payload
    overrides = await _price_overrides(session, items)
    return await cart_store.get_cart(
        ctx.tenant_id,
        **_session_kwargs(ctx, workspace_id=workspace_id),
        price_overrides=overrides,
        create=False,
    )


async def _resolve_product(
    ctx: ToolContext,
    sku: str,
    quantity: int,
) -> tuple[dict[str, Any] | None, Any | None, Any | None, str | None]:
    """Devuelve source, sesión externa, fila de producto o error."""
    source, session, error = await _authorized_catalog_source(
        ctx, "store.products.search"
    )
    if error or source is None or session is None:
        return None, None, None, error or "SOURCE_UNAVAILABLE"
    try:
        row = await _product_row(session, sku)
    except Exception as exc:  # noqa: BLE001
        await session.close()
        return None, None, None, f"PRICE_SOURCE_UNAVAILABLE: {str(exc)[:180]}"
    if row is None:
        await session.close()
        return None, None, None, f"PRODUCT_NOT_FOUND: {sku}"
    available = int(row.get("available") or 0)
    if available < quantity:
        await session.close()
        return (
            None,
            None,
            None,
            f"INSUFFICIENT_STOCK: disponible {available}, pediste {quantity}",
        )
    return source, session, row, None


class CartGetTool(Tool):
    name: ClassVar[str] = "cart_get"
    description: ClassVar[str] = (
        "Devuelve el carrito temporal de esta conversación con precios y total "
        "reales de la base. Úsala antes de confirmar un pedido. No inventes "
        "precios ni totales."
    )
    input_schema: ClassVar[dict] = {"type": "object", "properties": {}}
    permission: ClassVar[str] = "tool:query_database"
    timeout_seconds: ClassVar[float] = 30.0

    async def execute(self, ctx: ToolContext, arguments: dict) -> ToolResult:
        source, session, error = await _authorized_catalog_source(
            ctx, "store.products.search"
        )
        if error or source is None or session is None:
            return ToolResult(error=error or "SOURCE_UNAVAILABLE")
        workspace_id = _source_workspace(source)
        try:
            payload = await cart_store.get_cart(
                ctx.tenant_id,
                **_session_kwargs(ctx, workspace_id=workspace_id),
                create=False,
            )
        except ValueError as exc:
            await session.close()
            return ToolResult(error=str(exc))
        except Exception as exc:  # noqa: BLE001
            await session.close()
            return ToolResult(error=f"CART_READ_FAILED: {str(exc)[:180]}")
        if not payload.get("items"):
            await session.close()
            return _dump(payload, status="EMPTY")
        try:
            refreshed = await _refresh(
                ctx, session, payload, workspace_id=workspace_id
            )
            return _dump(refreshed)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                error=f"PRICE_SOURCE_UNAVAILABLE: {str(exc)[:180]}"
            )
        finally:
            await session.close()


class CartAddTool(Tool):
    name: ClassVar[str] = "cart_add"
    description: ClassVar[str] = (
        "Agrega o incrementa un SKU en el carrito temporal de esta conversación. "
        "El precio y el stock se leen de la base autorizada; no los envíes tú. "
        "Falla si no hay stock suficiente."
    )
    input_schema: ClassVar[dict] = {
        "type": "object",
        "required": ["sku", "quantity"],
        "properties": {
            "sku": {"type": "string", "minLength": 1, "maxLength": 80},
            "quantity": {"type": "integer", "minimum": 1, "maximum": 10000},
        },
    }
    permission: ClassVar[str] = "tool:query_database"
    timeout_seconds: ClassVar[float] = 30.0

    async def execute(self, ctx: ToolContext, arguments: dict) -> ToolResult:
        sku = str(arguments.get("sku") or "").strip()
        try:
            quantity = int(arguments.get("quantity"))
        except (TypeError, ValueError):
            return ToolResult(error="INVALID_ARGUMENT: quantity entero requerido")
        if not sku or quantity < 1 or quantity > 10000:
            return ToolResult(error="INVALID_ARGUMENT: sku/cantidad inválidos")
        source, session, row, error = await _resolve_product(ctx, sku, quantity)
        if error or source is None or session is None or row is None:
            return ToolResult(error=error or "SOURCE_UNAVAILABLE")
        try:
            existing = await cart_store.get_cart(
                ctx.tenant_id,
                **_session_kwargs(
                    ctx, workspace_id=_source_workspace(source)
                ),
                create=False,
            )
            current = next(
                (
                    int(Decimal(str(item.get("quantity") or 0)))
                    for item in existing.get("items") or []
                    if str(item.get("sku")) == sku
                ),
                0,
            )
            available = int(row.get("available") or 0)
            if current + quantity > available:
                return ToolResult(
                    error=(
                        "INSUFFICIENT_STOCK: disponible "
                        f"{available}, ya tienes {current} y agregas {quantity}"
                    )
                )
            payload = await cart_store.add_item(
                ctx.tenant_id,
                **_session_kwargs(
                    ctx, workspace_id=_source_workspace(source)
                ),
                sku=sku,
                name=str(row.get("name") or sku),
                unit=str(row.get("unit") or "UNIT"),
                unit_price=row.get("price"),
                currency=str(row.get("currency") or "PEN"),
                source_id=source["source_id"],
                price_source=f"external:{source['resource_ref']}",
                quantity=quantity,
            )
            return _dump(payload)
        except ValueError as exc:
            return ToolResult(error=str(exc))
        except Exception as exc:  # noqa: BLE001
            return ToolResult(error=f"CART_WRITE_FAILED: {str(exc)[:180]}")
        finally:
            await session.close()


class CartSetQuantityTool(Tool):
    name: ClassVar[str] = "cart_set_quantity"
    description: ClassVar[str] = (
        "Fija la cantidad de un SKU que ya está en el carrito temporal. "
        "Verifica stock real; no acepta precios del modelo."
    )
    input_schema: ClassVar[dict] = {
        "type": "object",
        "required": ["sku", "quantity"],
        "properties": {
            "sku": {"type": "string", "minLength": 1, "maxLength": 80},
            "quantity": {"type": "integer", "minimum": 1, "maximum": 10000},
        },
    }
    permission: ClassVar[str] = "tool:query_database"
    timeout_seconds: ClassVar[float] = 30.0

    async def execute(self, ctx: ToolContext, arguments: dict) -> ToolResult:
        sku = str(arguments.get("sku") or "").strip()
        try:
            quantity = int(arguments.get("quantity"))
        except (TypeError, ValueError):
            return ToolResult(error="INVALID_ARGUMENT: quantity entero requerido")
        if not sku or quantity < 1 or quantity > 10000:
            return ToolResult(error="INVALID_ARGUMENT: sku/cantidad inválidos")
        source, session, row, error = await _resolve_product(ctx, sku, quantity)
        if error or source is None or session is None or row is None:
            return ToolResult(error=error or "SOURCE_UNAVAILABLE")
        try:
            payload = await cart_store.set_quantity(
                ctx.tenant_id,
                **_session_kwargs(
                    ctx, workspace_id=_source_workspace(source)
                ),
                sku=sku,
                quantity=quantity,
                source_id=source["source_id"],
            )
            try:
                return _dump(
                    await _refresh(
                        ctx,
                        session,
                        payload,
                        workspace_id=_source_workspace(source),
                    )
                )
            except Exception:  # noqa: BLE001 - la mutación ya se confirmó
                return _dump(
                    {**payload, "price_refresh_warning": "no se pudo refrescar"}
                )
        except ValueError as exc:
            return ToolResult(error=str(exc))
        except Exception as exc:  # noqa: BLE001
            return ToolResult(error=f"CART_WRITE_FAILED: {str(exc)[:180]}")
        finally:
            await session.close()


class CartRemoveTool(Tool):
    name: ClassVar[str] = "cart_remove"
    description: ClassVar[str] = (
        "Quita un SKU del carrito temporal de esta conversación. Es idempotente."
    )
    input_schema: ClassVar[dict] = {
        "type": "object",
        "required": ["sku"],
        "properties": {
            "sku": {"type": "string", "minLength": 1, "maxLength": 80},
        },
    }
    permission: ClassVar[str] = "tool:query_database"
    timeout_seconds: ClassVar[float] = 30.0

    async def execute(self, ctx: ToolContext, arguments: dict) -> ToolResult:
        sku = str(arguments.get("sku") or "").strip()
        if not sku:
            return ToolResult(error="INVALID_ARGUMENT: sku requerido")
        workspace_id, error = await _workspace_from_source(ctx)
        if error:
            return ToolResult(error=error)
        try:
            current = await cart_store.get_cart(
                ctx.tenant_id,
                **_session_kwargs(ctx, workspace_id=workspace_id),
                create=False,
            )
            if not current.get("items"):
                return _dump(current, status="EMPTY")
            source_id = next(
                (
                    item.get("source_id")
                    for item in current.get("items") or []
                    if str(item.get("sku")) == sku
                ),
                None,
            )
            payload = await cart_store.remove_item(
                ctx.tenant_id,
                **_session_kwargs(ctx, workspace_id=workspace_id),
                sku=sku,
                source_id=source_id,
            )
            return _dump(payload, status="OK" if payload.get("items") else "EMPTY")
        except ValueError as exc:
            return ToolResult(error=str(exc))
        except Exception as exc:  # noqa: BLE001
            return ToolResult(error=f"CART_WRITE_FAILED: {str(exc)[:180]}")


class CartClearTool(Tool):
    name: ClassVar[str] = "cart_clear"
    description: ClassVar[str] = (
        "Vacía el carrito temporal de esta conversación sin cerrar la sesión."
    )
    input_schema: ClassVar[dict] = {"type": "object", "properties": {}}
    permission: ClassVar[str] = "tool:query_database"
    timeout_seconds: ClassVar[float] = 30.0

    async def execute(self, ctx: ToolContext, arguments: dict) -> ToolResult:
        workspace_id, error = await _workspace_from_source(ctx)
        if error:
            return ToolResult(error=error)
        try:
            payload = await cart_store.clear_cart(
                ctx.tenant_id,
                **_session_kwargs(ctx, workspace_id=workspace_id),
            )
            return _dump(payload, status="EMPTY")
        except ValueError as exc:
            return ToolResult(error=str(exc))
        except Exception as exc:  # noqa: BLE001
            return ToolResult(error=f"CART_WRITE_FAILED: {str(exc)[:180]}")


__all__ = [
    "CartAddTool",
    "CartClearTool",
    "CartGetTool",
    "CartRemoveTool",
    "CartSetQuantityTool",
]
