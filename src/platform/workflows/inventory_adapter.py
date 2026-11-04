# =============================================================================
# P19.1-07 - Adaptador de inventario (SQL fijo, fuera del core de bindings).
#
# El core despacha inventory.reserve/commit/release; este adaptador es el unico
# que conoce las tablas bodega.* y las invariantes transaccionales.
# =============================================================================
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from src.platform.workflows.bindings import BindingError, _query_failure


async def execute_inventory_action(
    organization_id: UUID,
    binding: dict[str, Any],
    payload: dict[str, Any],
    *,
    workspace_id: UUID | None,
) -> dict[str, Any]:
    """Inventario gobernado: reserva temporal, commit o release."""
    from urllib.parse import quote_plus

    from src.infrastructure.postgres.relational_db import PostgresConnectorRepository
    from src.infrastructure.secrets.secret_store_resolver import get_secret_store

    config = binding.get("config") or {}
    action = str(config.get("action") or "")
    if action == "search_products":
        return await search_products(
            organization_id, binding, payload, workspace_id=workspace_id
        )
    if action == "reserve_stock_batch":
        return await reserve_stock_batch(
            organization_id, binding, payload, workspace_id=workspace_id
        )
    if action == "create_order":
        return await create_order_projection(
            organization_id, binding, payload, workspace_id=workspace_id
        )
    if action == "commit_order_stock":
        return await settle_order_stock(
            organization_id,
            binding,
            payload,
            workspace_id=workspace_id,
            commit=True,
        )
    if action == "release_order_stock":
        return await settle_order_stock(
            organization_id,
            binding,
            payload,
            workspace_id=workspace_id,
            commit=False,
        )
    if action not in ("reserve_stock", "commit_stock", "release_stock"):
        raise BindingError("PROVIDER_NOT_SUPPORTED", "acción de inventario no soportada")
    if config.get("write") is not True:
        raise BindingError("PERMISSION_DENIED", "el conector no está habilitado para escritura")
    try:
        connector_id = UUID(str(config.get("connector_id") or ""))
    except (TypeError, ValueError) as exc:
        raise BindingError("NEEDS_CONFIGURATION", "inventory requiere connector_id") from exc
    order_number = str(payload.get("order_number") or "").strip()
    sku = str(payload.get("sku") or "").strip()
    if not re.match(r"^[A-Za-z0-9_-]{3,40}$", sku) or not re.match(
        r"^[A-Za-z0-9_-]{3,40}$", order_number
    ):
        raise BindingError("INVALID_PARAMS", "order_number o sku inválido")
    try:
        quantity = int(payload.get("quantity") or 0)
    except (TypeError, ValueError) as exc:
        raise BindingError("INVALID_PARAMS", "quantity inválida") from exc
    if quantity < 1 or quantity > int(config.get("max_quantity") or 100):
        raise BindingError("INVALID_PARAMS", "quantity fuera de rango")
    try:
        ttl_seconds = min(max(int(payload.get("ttl_seconds") or 900), 30), 3600)
    except (TypeError, ValueError):
        ttl_seconds = 900

    connector = await PostgresConnectorRepository().get_connector(
        organization_id, connector_id
    )
    if connector is None or str(connector.status or "").lower() != "active":
        raise BindingError("RESOURCE_NOT_EXPOSED", "conector de escritura no disponible")
    if connector.workspace_id and workspace_id and str(connector.workspace_id) != str(workspace_id):
        raise BindingError("PERMISSION_DENIED", "el conector pertenece a otro workspace")
    cfg = connector.config_json if isinstance(connector.config_json, dict) else {}
    if str(connector.type or "").lower() not in ("postgres", "postgresql"):
        raise BindingError("PROVIDER_NOT_SUPPORTED", "solo PostgreSQL")
    host = str(cfg.get("host") or "").strip()
    database = str(cfg.get("database") or "").strip()
    user = str(cfg.get("user") or "").strip()
    if not host or not database or not user:
        raise BindingError("NEEDS_CONFIGURATION", "conector de escritura incompleto")
    secret = await get_secret_store().get(organization_id, connector_id)
    password = secret.get("password") if isinstance(secret, dict) else None
    if not password:
        raise BindingError("NEEDS_CREDENTIALS", "sin credencial de escritura")
    dsn = (
        f"postgresql+asyncpg://{quote_plus(user)}:{quote_plus(str(password))}"
        f"@{host}:{int(cfg.get('port') or 5432)}/{quote_plus(database)}"
    )
    engine = create_async_engine(dsn, pool_size=1, max_overflow=0, pool_pre_ping=True)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "WITH expired AS ("
                    " UPDATE bodega.stock_reservations SET status = 'expired', released_at = NOW() "
                    " WHERE status = 'active' AND expires_at <= NOW() "
                    " RETURNING sku, quantity"
                    "), agg AS (SELECT sku, SUM(quantity) AS qty FROM expired GROUP BY sku) "
                    "UPDATE bodega.stock s SET reserved = GREATEST(s.reserved - agg.qty, 0) "
                    "FROM agg WHERE s.sku = agg.sku"
                )
            )
            order = (
                await conn.execute(
                    text(
                        "SELECT status FROM bodega.orders "
                        "WHERE order_number = :on FOR UPDATE"
                    ),
                    {"on": order_number},
                )
            ).fetchone()
            if order is None:
                raise BindingError("NOT_FOUND", "pedido no encontrado")
            if action == "reserve_stock" and str(order.status) in ("confirmed", "cancelled"):
                raise BindingError("CONFLICT", "el pedido ya está cerrado")
            stock = (
                await conn.execute(
                    text(
                        "SELECT on_hand, reserved FROM bodega.stock "
                        "WHERE sku = :sku FOR UPDATE"
                    ),
                    {"sku": sku},
                )
            ).fetchone()
            if stock is None:
                raise BindingError("RESOURCE_NOT_EXPOSED", "SKU no expuesto")
            reservation_key = f"reserve:{order_number}:{sku}"

            if action == "reserve_stock":
                existing = (
                    await conn.execute(
                        text(
                            "SELECT id, status, quantity, expires_at FROM bodega.stock_reservations "
                            "WHERE idempotency_key = :key"
                        ),
                        {"key": reservation_key},
                    )
                ).fetchone()
                if existing is not None:
                    if existing.status == "committed":
                        return {
                            "status": "COMMITTED",
                            "order_number": order_number,
                            "sku": sku,
                            "quantity": quantity,
                            "expires_at": existing.expires_at.isoformat() if existing.expires_at else None,
                            "reservation_id": str(existing.id),
                        }
                    if existing.status == "active":
                        return {
                            "status": "ALREADY_RESERVED",
                            "order_number": order_number,
                            "sku": sku,
                            "quantity": int(existing.quantity),
                            "requested_quantity": quantity,
                            "expires_at": existing.expires_at.isoformat() if existing.expires_at else None,
                            "reservation_id": str(existing.id),
                        }
                    available = int(stock.on_hand) - int(stock.reserved)
                    if available < quantity:
                        raise BindingError("CONFLICT", "stock insuficiente para reservar")
                    renewed = (
                        await conn.execute(
                            text(
                                "UPDATE bodega.stock_reservations SET status = 'active', "
                                "quantity = :qty, expires_at = NOW() + (:ttl || ' seconds')::interval, "
                                "committed_at = NULL, released_at = NULL, created_at = NOW() "
                                "WHERE id = :rid RETURNING expires_at"
                            ),
                            {"qty": quantity, "ttl": str(ttl_seconds), "rid": existing.id},
                        )
                    ).fetchone()
                    await conn.execute(
                        text(
                            "UPDATE bodega.stock SET reserved = reserved + :qty, "
                            "version = version + 1 WHERE sku = :sku"
                        ),
                        {"qty": quantity, "sku": sku},
                    )
                    return {
                        "status": "RESERVED",
                        "order_number": order_number,
                        "sku": sku,
                        "quantity": quantity,
                        "expires_at": renewed.expires_at.isoformat(),
                        "reservation_id": str(existing.id),
                        "available": available,
                    }
                available = int(stock.on_hand) - int(stock.reserved)
                if available < quantity:
                    raise BindingError("CONFLICT", "stock insuficiente para reservar")
                reservation = (
                    await conn.execute(
                        text(
                            "INSERT INTO bodega.stock_reservations "
                            "(order_number, sku, quantity, status, idempotency_key, expires_at) "
                            "VALUES (:on, :sku, :qty, 'active', :key, NOW() + (:ttl || ' seconds')::interval) "
                            "RETURNING id, expires_at"
                        ),
                        {
                            "on": order_number,
                            "sku": sku,
                            "qty": quantity,
                            "key": reservation_key,
                            "ttl": str(ttl_seconds),
                        },
                    )
                ).fetchone()
                await conn.execute(
                    text(
                        "UPDATE bodega.stock SET reserved = reserved + :qty, "
                        "version = version + 1 WHERE sku = :sku"
                    ),
                    {"qty": quantity, "sku": sku},
                )
                return {
                    "status": "RESERVED",
                    "order_number": order_number,
                    "sku": sku,
                    "quantity": quantity,
                    "expires_at": reservation.expires_at.isoformat(),
                    "reservation_id": str(reservation.id),
                    "available": available,
                }

            if action == "release_stock":
                reservation = (
                    await conn.execute(
                        text(
                            "SELECT id, status, quantity FROM bodega.stock_reservations "
                            "WHERE order_number = :on AND sku = :sku AND status = 'active' "
                            "FOR UPDATE"
                        ),
                        {"on": order_number, "sku": sku},
                    )
                ).fetchone()
                if reservation is None:
                    return {"status": "NO_ACTIVE_RESERVATION", "order_number": order_number, "sku": sku}
                await conn.execute(
                    text(
                        "UPDATE bodega.stock_reservations SET status = 'released', released_at = NOW() "
                        "WHERE id = :rid"
                    ),
                    {"rid": reservation.id},
                )
                await conn.execute(
                    text(
                        "UPDATE bodega.stock SET reserved = GREATEST(reserved - :qty, 0), "
                        "version = version + 1 WHERE sku = :sku"
                    ),
                    {"qty": int(reservation.quantity), "sku": sku},
                )
                return {
                    "status": "RELEASED",
                    "order_number": order_number,
                    "sku": sku,
                    "quantity": int(reservation.quantity),
                }

            existing = (
                await conn.execute(
                    text(
                        "SELECT id, after_on_hand FROM bodega.stock_movements "
                        "WHERE idempotency_key = :key"
                    ),
                    {"key": f"commit:{order_number}:{sku}"},
                )
            ).fetchone()
            if existing is not None:
                return {
                    "status": "ALREADY_APPLIED",
                    "order_number": order_number,
                    "sku": sku,
                    "quantity": quantity,
                    "on_hand": int(existing.after_on_hand),
                    "movement_id": str(existing.id),
                }
            reservation = (
                await conn.execute(
                    text(
                        "SELECT id, status, quantity, expires_at FROM bodega.stock_reservations "
                        "WHERE order_number = :on AND sku = :sku AND status = 'active' "
                        "FOR UPDATE"
                    ),
                    {"on": order_number, "sku": sku},
                )
            ).fetchone()
            if reservation is None:
                previous = (
                    await conn.execute(
                        text(
                            "SELECT status FROM bodega.stock_reservations "
                            "WHERE order_number = :on AND sku = :sku "
                            "ORDER BY created_at DESC LIMIT 1"
                        ),
                        {"on": order_number, "sku": sku},
                    )
                ).fetchone()
                if previous is not None and previous.status in ("expired", "released"):
                    return {
                        "status": "RESERVATION_EXPIRED",
                        "order_number": order_number,
                        "sku": sku,
                        "quantity": quantity,
                    }
                raise BindingError("CONFLICT", "no hay reserva activa para el pedido")
            if reservation.expires_at <= datetime.now(timezone.utc):
                await conn.execute(
                    text(
                        "UPDATE bodega.stock_reservations SET status = 'expired', released_at = NOW() "
                        "WHERE id = :rid"
                    ),
                    {"rid": reservation.id},
                )
                await conn.execute(
                    text(
                        "UPDATE bodega.stock SET reserved = GREATEST(reserved - :qty, 0) "
                        "WHERE sku = :sku"
                    ),
                    {"qty": int(reservation.quantity), "sku": sku},
                )
                return {
                    "status": "RESERVATION_EXPIRED",
                    "order_number": order_number,
                    "sku": sku,
                    "quantity": quantity,
                }
            before = int(stock.on_hand)
            if before < quantity:
                raise BindingError("CONFLICT", "stock insuficiente")
            after = before - quantity
            movement = (
                await conn.execute(
                    text(
                        "INSERT INTO bodega.stock_movements "
                        "(order_number, sku, quantity, movement_type, idempotency_key, "
                        "before_on_hand, after_on_hand) "
                        "VALUES (:on, :sku, :qty, 'commit', :key, :before, :after) "
                        "RETURNING id"
                    ),
                    {
                        "on": order_number,
                        "sku": sku,
                        "qty": quantity,
                        "key": f"commit:{order_number}:{sku}",
                        "before": before,
                        "after": after,
                    },
                )
            ).fetchone()
            await conn.execute(
                text(
                    "UPDATE bodega.stock SET on_hand = :after, "
                    "reserved = GREATEST(reserved - :qty, 0), version = version + 1 "
                    "WHERE sku = :sku"
                ),
                {"after": after, "qty": quantity, "sku": sku},
            )
            await conn.execute(
                text(
                    "UPDATE bodega.stock_reservations SET status = 'committed', committed_at = NOW() "
                    "WHERE id = :rid"
                ),
                {"rid": reservation.id},
            )
            await conn.execute(
                text(
                    "UPDATE bodega.orders SET status = 'confirmed', "
                    "payment_status = 'approved_manual', updated_at = NOW() "
                    "WHERE order_number = :on"
                ),
                {"on": order_number},
            )
        return {
            "status": "COMMITTED",
            "order_number": order_number,
            "sku": sku,
            "quantity": quantity,
            "on_hand_before": before,
            "on_hand": after,
            "movement_id": str(movement.id) if movement else None,
        }
    except BindingError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _query_failure(exc) from exc
    finally:
        await engine.dispose()


async def expire_inventory_reservations(
    organization_id: UUID,
    binding: dict[str, Any],
    *,
    workspace_id: UUID | None,
    batch_size: int = 500,
) -> dict[str, Any]:
    """Barrido periodico idempotente; no depende de una peticion de usuario."""
    from urllib.parse import quote_plus

    from src.infrastructure.postgres.relational_db import PostgresConnectorRepository
    from src.infrastructure.secrets.secret_store_resolver import get_secret_store

    config = binding.get("config") or {}
    if config.get("write") is not True:
        raise BindingError("PERMISSION_DENIED", "el conector no esta habilitado para escritura")
    try:
        connector_id = UUID(str(config.get("connector_id") or ""))
    except (TypeError, ValueError) as exc:
        raise BindingError("NEEDS_CONFIGURATION", "inventory requiere connector_id") from exc
    connector = await PostgresConnectorRepository().get_connector(organization_id, connector_id)
    if connector is None or str(connector.status or "").lower() != "active":
        raise BindingError("RESOURCE_NOT_EXPOSED", "conector de escritura no disponible")
    if connector.workspace_id and workspace_id and str(connector.workspace_id) != str(workspace_id):
        raise BindingError("PERMISSION_DENIED", "el conector pertenece a otro workspace")
    cfg = connector.config_json if isinstance(connector.config_json, dict) else {}
    host = str(cfg.get("host") or "").strip()
    database = str(cfg.get("database") or "").strip()
    user = str(cfg.get("user") or "").strip()
    if not host or not database or not user:
        raise BindingError("NEEDS_CONFIGURATION", "conector de escritura incompleto")
    secret = await get_secret_store().get(organization_id, connector_id)
    password = secret.get("password") if isinstance(secret, dict) else None
    if not password:
        raise BindingError("NEEDS_CREDENTIALS", "sin credencial de escritura")
    dsn = (
        f"postgresql+asyncpg://{quote_plus(user)}:{quote_plus(str(password))}"
        f"@{host}:{int(cfg.get('port') or 5432)}/{quote_plus(database)}"
    )
    engine = create_async_engine(dsn, pool_size=1, max_overflow=0, pool_pre_ping=True)
    try:
        async with engine.begin() as conn:
            locked = (
                await conn.execute(
                    text("SELECT pg_try_advisory_xact_lock(hashtext('zent:inventory:expire'))")
                )
            ).scalar()
            if not locked:
                return {"status": "SKIPPED", "reason": "another_worker"}
            expired = (
                await conn.execute(
                    text(
                        "WITH victim AS ("
                        " SELECT id, sku, quantity FROM bodega.stock_reservations"
                        " WHERE status = 'active' AND expires_at <= NOW()"
                        " ORDER BY expires_at FOR UPDATE SKIP LOCKED LIMIT :limit"
                        "), upd AS ("
                        " UPDATE bodega.stock_reservations r SET status = 'expired', released_at = NOW()"
                        " FROM victim v WHERE r.id = v.id RETURNING v.sku, v.quantity"
                        "), agg AS (SELECT sku, SUM(quantity) AS qty FROM upd GROUP BY sku)"
                        " UPDATE bodega.stock s SET reserved = GREATEST(s.reserved - agg.qty, 0),"
                        " version = version + 1 FROM agg WHERE s.sku = agg.sku"
                        " RETURNING agg.qty"
                    ),
                    {"limit": max(1, min(int(batch_size), 2000))},
                )
            ).fetchall()
        return {"status": "OK", "expired_reservations": len(expired)}
    except BindingError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _query_failure(exc) from exc
    finally:
        await engine.dispose()


async def reserve_stock_batch(
    organization_id: UUID,
    binding: dict[str, Any],
    payload: dict[str, Any],
    *,
    workspace_id: UUID | None,
) -> dict[str, Any]:
    """Reserva multi-item atomica: todo o nada, en una sola transaccion."""
    from urllib.parse import quote_plus

    from src.infrastructure.postgres.relational_db import PostgresConnectorRepository
    from src.infrastructure.secrets.secret_store_resolver import get_secret_store

    config = binding.get("config") or {}
    if config.get("write") is not True:
        raise BindingError("PERMISSION_DENIED", "el conector no esta habilitado para escritura")
    try:
        connector_id = UUID(str(config.get("connector_id") or ""))
    except (TypeError, ValueError) as exc:
        raise BindingError("NEEDS_CONFIGURATION", "inventory requiere connector_id") from exc
    order_number = str(payload.get("order_number") or "").strip()
    if not re.match(r"^[A-Za-z0-9_-]{3,40}$", order_number):
        raise BindingError("INVALID_PARAMS", "order_number invalido")
    raw_items = payload.get("items")
    if isinstance(raw_items, str):
        import json as _json

        try:
            raw_items = _json.loads(raw_items)
        except ValueError as exc:
            raise BindingError("INVALID_PARAMS", "items no es JSON valido") from exc
    if not isinstance(raw_items, list) or not raw_items or len(raw_items) > 20:
        raise BindingError("INVALID_PARAMS", "items requiere 1..20 lineas")
    items: list[tuple[str, int]] = []
    seen: set[str] = set()
    max_quantity = int(config.get("max_quantity") or 100)
    for raw in raw_items:
        if not isinstance(raw, dict):
            raise BindingError("INVALID_PARAMS", "item invalido")
        sku = str(raw.get("sku") or "").strip()
        if not re.match(r"^[A-Za-z0-9_-]{3,40}$", sku):
            raise BindingError("INVALID_PARAMS", "sku invalido")
        if sku in seen:
            raise BindingError("INVALID_PARAMS", "sku duplicado en items")
        seen.add(sku)
        try:
            quantity = int(raw.get("quantity") or 0)
        except (TypeError, ValueError) as exc:
            raise BindingError("INVALID_PARAMS", "quantity invalida") from exc
        if quantity < 1 or quantity > max_quantity:
            raise BindingError("INVALID_PARAMS", "quantity fuera de rango")
        items.append((sku, quantity))
    try:
        ttl_seconds = min(max(int(payload.get("ttl_seconds") or 900), 30), 3600)
    except (TypeError, ValueError):
        ttl_seconds = 900

    connector = await PostgresConnectorRepository().get_connector(organization_id, connector_id)
    if connector is None or str(connector.status or "").lower() != "active":
        raise BindingError("RESOURCE_NOT_EXPOSED", "conector de escritura no disponible")
    if connector.workspace_id and workspace_id and str(connector.workspace_id) != str(workspace_id):
        raise BindingError("PERMISSION_DENIED", "el conector pertenece a otro workspace")
    cfg = connector.config_json if isinstance(connector.config_json, dict) else {}
    host = str(cfg.get("host") or "").strip()
    database = str(cfg.get("database") or "").strip()
    user = str(cfg.get("user") or "").strip()
    if not host or not database or not user:
        raise BindingError("NEEDS_CONFIGURATION", "conector de escritura incompleto")
    secret = await get_secret_store().get(organization_id, connector_id)
    password = secret.get("password") if isinstance(secret, dict) else None
    if not password:
        raise BindingError("NEEDS_CREDENTIALS", "sin credencial de escritura")
    dsn = (
        f"postgresql+asyncpg://{quote_plus(user)}:{quote_plus(str(password))}"
        f"@{host}:{int(cfg.get('port') or 5432)}/{quote_plus(database)}"
    )
    engine = create_async_engine(dsn, pool_size=1, max_overflow=0, pool_pre_ping=True)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "WITH expired AS ("
                    " UPDATE bodega.stock_reservations SET status = 'expired', released_at = NOW()"
                    " WHERE status = 'active' AND expires_at <= NOW() RETURNING sku, quantity"
                    "), agg AS (SELECT sku, SUM(quantity) AS qty FROM expired GROUP BY sku)"
                    " UPDATE bodega.stock s SET reserved = GREATEST(s.reserved - agg.qty, 0)"
                    " FROM agg WHERE s.sku = agg.sku"
                )
            )
            order = (
                await conn.execute(
                    text("SELECT status FROM bodega.orders WHERE order_number = :on FOR UPDATE"),
                    {"on": order_number},
                )
            ).fetchone()
            if order is None:
                raise BindingError("NOT_FOUND", "pedido no encontrado")
            if str(order.status) in ("confirmed", "cancelled"):
                raise BindingError("CONFLICT", "el pedido ya esta cerrado")

            existing_rows = (
                await conn.execute(
                    text(
                        "SELECT sku, id, status, quantity, expires_at"
                        " FROM bodega.stock_reservations"
                        " WHERE order_number = :on AND sku = ANY(:skus) AND status = 'active'"
                        " FOR UPDATE"
                    ),
                    {"on": order_number, "skus": [sku for sku, _ in items]},
                )
            ).fetchall()
            existing = {str(row.sku): row for row in existing_rows}
            if existing:
                return {
                    "status": "ALREADY_RESERVED",
                    "order_number": order_number,
                    "items": [
                        {
                            "sku": sku,
                            "quantity": int(existing[sku].quantity),
                            "reservation_id": str(existing[sku].id),
                        }
                        for sku, _ in items
                        if sku in existing
                    ],
                }

            stocks = (
                await conn.execute(
                    text(
                        "SELECT sku, on_hand, reserved FROM bodega.stock"
                        " WHERE sku = ANY(:skus) ORDER BY sku FOR UPDATE"
                    ),
                    {"skus": [sku for sku, _ in items]},
                )
            ).fetchall()
            by_sku = {str(row.sku): row for row in stocks}
            for sku, quantity in items:
                stock = by_sku.get(sku)
                if stock is None:
                    raise BindingError("RESOURCE_NOT_EXPOSED", f"SKU no expuesto: {sku}")
                available = int(stock.on_hand) - int(stock.reserved)
                if available < quantity:
                    raise BindingError("CONFLICT", f"stock insuficiente para {sku}")

            reservations = []
            for sku, quantity in items:
                row = (
                    await conn.execute(
                        text(
                            "INSERT INTO bodega.stock_reservations"
                            " (order_number, sku, quantity, status, idempotency_key, expires_at)"
                            " VALUES (:on, :sku, :qty, 'active', :key,"
                            " NOW() + (:ttl || ' seconds')::interval)"
                            " RETURNING id, expires_at"
                        ),
                        {
                            "on": order_number,
                            "sku": sku,
                            "qty": quantity,
                            "key": f"reserve:{order_number}:{sku}",
                            "ttl": str(ttl_seconds),
                        },
                    )
                ).fetchone()
                await conn.execute(
                    text(
                        "UPDATE bodega.stock SET reserved = reserved + :qty,"
                        " version = version + 1 WHERE sku = :sku"
                    ),
                    {"qty": quantity, "sku": sku},
                )
                reservations.append(
                    {
                        "sku": sku,
                        "quantity": quantity,
                        "reservation_id": str(row.id),
                        "expires_at": row.expires_at.isoformat(),
                    }
                )
        return {"status": "RESERVED", "order_number": order_number, "items": reservations}
    except BindingError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _query_failure(exc) from exc
    finally:
        await engine.dispose()



async def _write_engine(
    organization_id: UUID,
    config: dict[str, Any],
    *,
    workspace_id: UUID | None,
):
    """Valida el binding de escritura y devuelve un engine per-request."""
    from urllib.parse import quote_plus

    from sqlalchemy.ext.asyncio import create_async_engine

    from src.infrastructure.postgres.relational_db import PostgresConnectorRepository
    from src.infrastructure.secrets.secret_store_resolver import get_secret_store

    if config.get("write") is not True:
        raise BindingError(
            "PERMISSION_DENIED", "el conector no esta habilitado para escritura"
        )
    try:
        connector_id = UUID(str(config.get("connector_id") or ""))
    except (TypeError, ValueError) as exc:
        raise BindingError("NEEDS_CONFIGURATION", "inventory requiere connector_id") from exc
    connector = await PostgresConnectorRepository().get_connector(
        organization_id, connector_id
    )
    if connector is None or str(connector.status or "").lower() != "active":
        raise BindingError("RESOURCE_NOT_EXPOSED", "conector de escritura no disponible")
    if (
        connector.workspace_id
        and workspace_id
        and str(connector.workspace_id) != str(workspace_id)
    ):
        raise BindingError("PERMISSION_DENIED", "el conector pertenece a otro workspace")
    cfg = connector.config_json if isinstance(connector.config_json, dict) else {}
    if str(connector.type or "").lower() not in ("postgres", "postgresql"):
        raise BindingError("PROVIDER_NOT_SUPPORTED", "solo PostgreSQL")
    host = str(cfg.get("host") or "").strip()
    database = str(cfg.get("database") or "").strip()
    user = str(cfg.get("user") or "").strip()
    if not host or not database or not user:
        raise BindingError("NEEDS_CONFIGURATION", "conector de escritura incompleto")
    secret = await get_secret_store().get(organization_id, connector_id)
    password = secret.get("password") if isinstance(secret, dict) else None
    if not password:
        raise BindingError("NEEDS_CREDENTIALS", "sin credencial de escritura")
    dsn = (
        f"postgresql+asyncpg://{quote_plus(user)}:{quote_plus(str(password))}"
        f"@{host}:{int(cfg.get('port') or 5432)}/{quote_plus(database)}"
    )
    return create_async_engine(dsn, pool_size=1, max_overflow=0, pool_pre_ping=True)


def _order_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_items = payload.get("items")
    if isinstance(raw_items, str):
        import json as _json

        try:
            raw_items = _json.loads(raw_items)
        except ValueError as exc:
            raise BindingError("INVALID_PARAMS", "items no es JSON valido") from exc
    if not isinstance(raw_items, list) or not raw_items or len(raw_items) > 20:
        raise BindingError("INVALID_PARAMS", "items requiere 1..20 lineas")
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_items:
        if not isinstance(raw, dict):
            raise BindingError("INVALID_PARAMS", "item invalido")
        sku = str(raw.get("sku") or "").strip()
        if not re.match(r"^[A-Za-z0-9_-]{3,40}$", sku):
            raise BindingError("INVALID_PARAMS", "sku invalido")
        if sku in seen:
            raise BindingError("INVALID_PARAMS", "sku duplicado")
        seen.add(sku)
        try:
            quantity = int(raw.get("quantity") or 0)
            unit_price = Decimal(str(raw.get("unit_price") or 0))
        except (TypeError, ValueError, InvalidOperation) as exc:
            raise BindingError("INVALID_PARAMS", "quantity/unit_price invalidos") from exc
        if quantity < 1 or quantity > 100:
            raise BindingError("INVALID_PARAMS", "quantity fuera de rango")
        if unit_price < 0:
            raise BindingError("INVALID_PARAMS", "unit_price negativo")
        items.append(
            {
                "sku": sku,
                "quantity": quantity,
                "unit_price": unit_price.quantize(Decimal("0.01")),
            }
        )
    return items


async def create_order_projection(
    organization_id: UUID,
    binding: dict[str, Any],
    payload: dict[str, Any],
    *,
    workspace_id: UUID | None,
) -> dict[str, Any]:
    """Proyecta la orden ZENT a bodega.orders para poder reservar/commit stock.

    ZENT sigue siendo la autoridad de la orden; esta fila es una proyeccion
    idempotente. No acepta montos del cliente: recalcula el total con Decimal.
    """
    config = binding.get("config") or {}
    order_number = str(payload.get("order_number") or "").strip()
    if not re.match(r"^[A-Za-z0-9_-]{3,40}$", order_number):
        raise BindingError("INVALID_PARAMS", "order_number invalido")
    customer_ref = str(payload.get("customer_ref") or "").strip()[:160]
    if not customer_ref:
        raise BindingError("INVALID_PARAMS", "customer_ref requerido")
    currency = str(payload.get("currency") or "PEN").upper()[:3]
    if not re.match(r"^[A-Z]{3}$", currency):
        raise BindingError("INVALID_PARAMS", "currency invalida")
    items = _order_items(payload)
    total = sum(
        (item["unit_price"] * item["quantity"] for item in items),
        Decimal("0"),
    ).quantize(Decimal("0.01"))

    engine = await _write_engine(organization_id, config, workspace_id=workspace_id)
    try:
        async with engine.begin() as conn:
            existing = (
                await conn.execute(
                    text(
                        "SELECT status FROM bodega.orders "
                        "WHERE order_number = :on FOR UPDATE"
                    ),
                    {"on": order_number},
                )
            ).fetchone()
            if existing is not None and str(existing.status) in (
                "confirmed",
                "cancelled",
            ):
                return {
                    "status": "ALREADY_CLOSED",
                    "order_number": order_number,
                    "projection_status": str(existing.status),
                }
            await conn.execute(
                text(
                    "INSERT INTO bodega.orders "
                    "(order_number, customer_ref, status, payment_status, total, currency) "
                    "VALUES (:on, :cust, 'pending_approval', 'pending', :total, :cur) "
                    "ON CONFLICT (order_number) DO UPDATE SET "
                    "customer_ref = EXCLUDED.customer_ref, total = EXCLUDED.total, "
                    "currency = EXCLUDED.currency, updated_at = NOW()"
                ),
                {
                    "on": order_number,
                    "cust": customer_ref,
                    "total": str(total),
                    "cur": currency,
                },
            )
            for item in items:
                await conn.execute(
                    text(
                        "INSERT INTO bodega.order_items "
                        "(order_number, sku, quantity, unit_price) "
                        "VALUES (:on, :sku, :qty, :price) "
                        "ON CONFLICT (order_number, sku) DO UPDATE SET "
                        "quantity = EXCLUDED.quantity, unit_price = EXCLUDED.unit_price"
                    ),
                    {
                        "on": order_number,
                        "sku": item["sku"],
                        "qty": item["quantity"],
                        "price": str(item["unit_price"]),
                    },
                )
        return {
            "status": "CREATED",
            "order_number": order_number,
            "total": float(total),
            "currency": currency,
            "items": len(items),
        }
    except BindingError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _query_failure(exc) from exc
    finally:
        await engine.dispose()


async def settle_order_stock(
    organization_id: UUID,
    binding: dict[str, Any],
    payload: dict[str, Any],
    *,
    workspace_id: UUID | None,
    commit: bool,
) -> dict[str, Any]:
    """Commit o release atomico de todas las reservas de una orden."""
    config = binding.get("config") or {}
    order_number = str(payload.get("order_number") or "").strip()
    if not re.match(r"^[A-Za-z0-9_-]{3,40}$", order_number):
        raise BindingError("INVALID_PARAMS", "order_number invalido")

    engine = await _write_engine(organization_id, config, workspace_id=workspace_id)
    try:
        async with engine.begin() as conn:
            order = (
                await conn.execute(
                    text(
                        "SELECT status, payment_status FROM bodega.orders "
                        "WHERE order_number = :on FOR UPDATE"
                    ),
                    {"on": order_number},
                )
            ).fetchone()
            if order is None:
                raise BindingError("NOT_FOUND", "pedido no encontrado")
            reservations = (
                await conn.execute(
                    text(
                        "SELECT id, sku, quantity FROM bodega.stock_reservations "
                        "WHERE order_number = :on AND status = 'active' "
                        "ORDER BY sku FOR UPDATE"
                    ),
                    {"on": order_number},
                )
            ).fetchall()
            if not reservations:
                if commit and str(order.status) == "confirmed":
                    return {
                        "status": "ALREADY_APPLIED",
                        "order_number": order_number,
                        "items": [],
                    }
                return {
                    "status": "NO_ACTIVE_RESERVATION",
                    "order_number": order_number,
                    "items": [],
                }

            settled: list[dict[str, Any]] = []
            for reservation in reservations:
                sku = str(reservation.sku)
                quantity = int(reservation.quantity)
                stock = (
                    await conn.execute(
                        text(
                            "SELECT on_hand, reserved FROM bodega.stock "
                            "WHERE sku = :sku FOR UPDATE"
                        ),
                        {"sku": sku},
                    )
                ).fetchone()
                if stock is None:
                    raise BindingError("RESOURCE_NOT_EXPOSED", f"SKU no expuesto: {sku}")
                before = int(stock.on_hand)
                if commit:
                    if before < quantity:
                        raise BindingError("CONFLICT", f"stock insuficiente para {sku}")
                    after = before - quantity
                    movement = (
                        await conn.execute(
                            text(
                                "SELECT id FROM bodega.stock_movements "
                                "WHERE idempotency_key = :key"
                            ),
                            {"key": f"commit:{order_number}:{sku}"},
                        )
                    ).fetchone()
                    if movement is None:
                        await conn.execute(
                            text(
                                "UPDATE bodega.stock SET on_hand = :after, "
                                "reserved = GREATEST(reserved - :qty, 0), "
                                "version = version + 1 WHERE sku = :sku"
                            ),
                            {"after": after, "qty": quantity, "sku": sku},
                        )
                        await conn.execute(
                            text(
                                "INSERT INTO bodega.stock_movements "
                                "(order_number, sku, quantity, movement_type, "
                                "idempotency_key, before_on_hand, after_on_hand) "
                                "VALUES (:on, :sku, :qty, 'commit', :key, :before, :after)"
                            ),
                            {
                                "on": order_number,
                                "sku": sku,
                                "qty": quantity,
                                "key": f"commit:{order_number}:{sku}",
                                "before": before,
                                "after": after,
                            },
                        )
                    await conn.execute(
                        text(
                            "UPDATE bodega.stock_reservations "
                            "SET status = 'committed', committed_at = NOW() "
                            "WHERE id = :rid"
                        ),
                        {"rid": reservation.id},
                    )
                    settled.append(
                        {
                            "sku": sku,
                            "quantity": quantity,
                            "status": "committed",
                            "on_hand": after,
                        }
                    )
                else:
                    await conn.execute(
                        text(
                            "UPDATE bodega.stock SET "
                            "reserved = GREATEST(reserved - :qty, 0), "
                            "version = version + 1 WHERE sku = :sku"
                        ),
                        {"qty": quantity, "sku": sku},
                    )
                    await conn.execute(
                        text(
                            "UPDATE bodega.stock_reservations "
                            "SET status = 'released', released_at = NOW() "
                            "WHERE id = :rid"
                        ),
                        {"rid": reservation.id},
                    )
                    settled.append(
                        {
                            "sku": sku,
                            "quantity": quantity,
                            "status": "released",
                        }
                    )
            await conn.execute(
                text(
                    "UPDATE bodega.orders SET status = :status, "
                    "payment_status = :payment, updated_at = NOW() "
                    "WHERE order_number = :on"
                ),
                {
                    "on": order_number,
                    "status": "confirmed" if commit else "cancelled",
                    "payment": "paid" if commit else "cancelled",
                },
            )
        return {
            "status": "COMMITTED" if commit else "RELEASED",
            "order_number": order_number,
            "items": settled,
        }
    except BindingError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _query_failure(exc) from exc
    finally:
        await engine.dispose()


#: Palabras de una pregunta que no describen el producto. Sin esto,
#: "tienes arroz" busca el literal y no encuentra nada.
_QUERY_STOPWORDS = frozenset(
    {
        "tienes",
        "tiene",
        "hay",
        "quiero",
        "quisiera",
        "busco",
        "buscame",
        "necesito",
        "dame",
        "vendes",
        "vende",
        "precio",
        "precios",
        "cuanto",
        "cuesta",
        "cuestan",
        "vale",
        "de",
        "del",
        "el",
        "la",
        "los",
        "las",
        "un",
        "una",
        "unos",
        "unas",
        "y",
        "en",
        "por",
        "favor",
        "hola",
        "buenas",
        "me",
        "mi",
        "para",
        "con",
        "que",
        "algo",
        "kilo",
        "kilos",
        "kg",
        "unidad",
        "unidades",
    }
)


def _search_terms(text: str) -> list[str]:
    sku = re.search(r"\b[A-Z][A-Z0-9]{1,7}(?:-[A-Z0-9]{1,10}){1,3}\b", str(text or ""))
    if sku:
        return [sku.group(0).lower()]
    normalized = (
        unicodedata.normalize("NFKD", str(text or ""))
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
    )
    terms = [
        token
        for token in re.findall(r"[a-z0-9]+", normalized)
        if (len(token) >= 2 or token.isdigit()) and token not in _QUERY_STOPWORDS
    ]
    return terms[:6]


def _product_search_sql(
    terms: list[str], *, limit: int
) -> tuple[str, str, dict[str, Any]]:
    """SQL fijo (sin interpolación de valores) para buscar por nombre o SKU."""
    term_params: dict[str, Any] = {
        f"q{index + 1}": f"%{term}%" for index, term in enumerate(terms)
    }
    for index in range(len(terms) + 1, 7):
        term_params[f"q{index}"] = None
    and_clause = " AND ".join(
        f"(CAST(:q{index} AS text) IS NULL OR name ILIKE CAST(:q{index} AS text) "
        f"OR sku ILIKE CAST(:q{index} AS text))"
        for index in range(1, 7)
    )
    and_sql = (
        "SELECT sku, name, unit, price, currency, available "
        "FROM bodega.product_catalog_v WHERE "
        + and_clause
        + " ORDER BY name, sku LIMIT :limit"
    )
    or_clause = " OR ".join(
        f"name ILIKE CAST(:q{index} AS text) OR sku ILIKE CAST(:q{index} AS text)"
        for index in range(1, len(terms) + 1)
    )
    or_sql = (
        "SELECT sku, name, unit, price, currency, available "
        "FROM bodega.product_catalog_v WHERE "
        + or_clause
        + " ORDER BY name, sku LIMIT :limit"
    )
    return and_sql, or_sql, {**term_params, "limit": limit}


async def search_products(
    organization_id: UUID,
    binding: dict[str, Any],
    payload: dict[str, Any],
    *,
    workspace_id: UUID | None,
) -> dict[str, Any]:
    """Busca productos por texto libre en el catalogo conectado (solo lectura).

    El precio, la moneda y el stock salen de la vista `bodega.product_catalog_v`;
    el nodo nunca calcula ni inventa esos valores.
    """
    from urllib.parse import quote_plus

    from src.infrastructure.postgres.relational_db import PostgresConnectorRepository
    from src.infrastructure.secrets.secret_store_resolver import get_secret_store

    config = binding.get("config") or {}
    if config.get("write") is True:
        raise BindingError("PERMISSION_DENIED", "search_products es solo lectura")
    try:
        connector_id = UUID(str(config.get("connector_id") or ""))
    except (TypeError, ValueError) as exc:
        raise BindingError("NEEDS_CONFIGURATION", "search requiere connector_id") from exc
    query = str(payload.get("query") or "").strip()[:120]
    terms = _search_terms(query)
    if not terms:
        return {"status": "NOT_FOUND", "rows": [], "row_count": 0, "terms": []}
    try:
        limit = int(payload.get("limit") or config.get("max_rows") or 2)
    except (TypeError, ValueError):
        limit = 2
    limit = min(max(limit, 1), 5)

    connector = await PostgresConnectorRepository().get_connector(
        organization_id, connector_id
    )
    if connector is None or str(connector.status or "").lower() != "active":
        raise BindingError("RESOURCE_NOT_EXPOSED", "conector de catalogo no disponible")
    if connector.workspace_id and workspace_id and str(connector.workspace_id) != str(workspace_id):
        raise BindingError("PERMISSION_DENIED", "el conector pertenece a otro workspace")
    cfg = connector.config_json if isinstance(connector.config_json, dict) else {}
    if str(connector.type or "").lower() not in ("postgres", "postgresql"):
        raise BindingError("PROVIDER_NOT_SUPPORTED", "solo PostgreSQL")
    host = str(cfg.get("host") or "").strip()
    database = str(cfg.get("database") or "").strip()
    user = str(cfg.get("user") or "").strip()
    if not host or not database or not user:
        raise BindingError("NEEDS_CONFIGURATION", "conector de catalogo incompleto")
    secret = await get_secret_store().get(organization_id, connector_id)
    password = secret.get("password") if isinstance(secret, dict) else None
    if not password:
        raise BindingError("NEEDS_CREDENTIALS", "sin credencial de lectura")
    dsn = (
        f"postgresql+asyncpg://{quote_plus(user)}:{quote_plus(str(password))}"
        f"@{host}:{int(cfg.get('port') or 5432)}/{quote_plus(database)}"
    )

    and_sql, or_sql, params = _product_search_sql(terms, limit=limit)

    engine = create_async_engine(dsn, pool_size=1, max_overflow=0, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SET statement_timeout = 3000"))
            rows = (await conn.execute(text(and_sql), params)).fetchall()
            if not rows and len(terms) > 1:
                rows = (
                    await conn.execute(text(or_sql), params)
                ).fetchall()
    except Exception as exc:  # noqa: BLE001
        raise _query_failure(exc) from exc
    finally:
        await engine.dispose()

    data = [
        {
            "sku": str(row.sku),
            "name": str(row.name),
            "unit": str(row.unit or ""),
            "price": float(row.price or 0),
            "currency": str(row.currency or "").strip(),
            "available": int(row.available or 0),
        }
        for row in rows
    ]
    return {
        "status": "FOUND" if data else "NOT_FOUND",
        "rows": data,
        "row_count": len(data),
        "terms": terms,
    }
