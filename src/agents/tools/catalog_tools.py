# =============================================================================
# P20-05 - tools comerciales read-only sobre la fuente externa autorizada.
# =============================================================================
# Precio, moneda y stock salen de la BD; el LLM solo recibe JSON tipado.
# No crean carrito, orden ni pago. Reutilizan grants P20-04.
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, ClassVar
from uuid import UUID

from sqlalchemy import text

from src.agents.tools.base import Tool, ToolContext, ToolResult
from src.core.config import get_settings

_CATALOG_RESOURCE = "bodega.product_catalog_v"


async def _authorized_catalog_source(
    ctx: ToolContext,
    capability_ref: str,
) -> tuple[dict | None, Any | None, str | None]:
    """Resuelve fuente, grant y sesión externa para catálogo.

    Acepta la capability específica o el grant genérico `store.query_database`.
    En ambos casos exige el recurso `bodega.product_catalog_v`.
    """
    from src.platform.agents.data_grants import (
        allowed_capability_resources,
        allowed_query_resources,
    )
    from src.platform.agents.database_access import resolve_agent_database_source
    from src.platform.workflows.external_connector import (
        resolve_external_postgres_connection,
    )

    source_ids = [
        str(item).strip()
        for item in ((ctx.org_config or {}).get("source_ids") or [])
        if str(item).strip()
    ]
    source, source_error = await resolve_agent_database_source(
        organization_id=ctx.tenant_id,
        user_id=ctx.user_id,
        source_ids=source_ids,
    )
    if source_error:
        return None, None, source_error
    if source is None:
        return None, None, (
            "NO_DATABASE_SOURCE: el agente no tiene una base de datos vinculada"
        )
    workspace = UUID(source.workspace_id) if source.workspace_id else None
    allowed, grant_error = await allowed_capability_resources(
        ctx.tenant_id,
        ctx.agent_id,
        capability_ref,
        workspace_id=workspace,
    )
    if not allowed:
        allowed, grant_error = await allowed_query_resources(
            ctx.tenant_id,
            ctx.agent_id,
            workspace_id=workspace,
        )
    if grant_error:
        return None, None, grant_error
    if _CATALOG_RESOURCE not in allowed:
        return None, None, (
            "PERMISSION_DENIED: el agente no tiene grant sobre "
            f"{_CATALOG_RESOURCE}"
        )
    resolved = await resolve_external_postgres_connection(
        organization_id=ctx.tenant_id,
        connector_id=UUID(source.connector_id),
        workspace_id=workspace,
    )
    if resolved.error or resolved.session_factory is None:
        return None, None, resolved.error or "SOURCE_UNAVAILABLE"
    return (
        {
            "source_id": source.source_id,
            "connector_id": source.connector_id,
            "workspace_id": source.workspace_id,
            "source_mode": source.source_mode,
            "resource_ref": _CATALOG_RESOURCE,
        },
        resolved.session_factory(),
        None,
    )


async def _run_catalog_query(
    session,
    sql: str,
    params: dict,
) -> list[dict]:
    from src.infrastructure.postgres.readonly_session import (
        apply_readonly_transaction,
    )

    timeout_seconds = get_settings().RAG_SQL_TIMEOUT_SECONDS
    try:
        await apply_readonly_transaction(session, timeout_seconds)
        result = await session.execute(text(sql), params)
        return [dict(row._mapping) for row in result.fetchall()]
    finally:
        await session.close()


def _money(value: Any) -> str:
    try:
        return str(Decimal(str(value)).quantize(Decimal("0.01")))
    except (InvalidOperation, TypeError, ValueError):
        return str(value)


_STOPWORDS = {"de", "del", "el", "la", "los", "las", "un", "una", "y", "en"}


def _search_terms(query: str) -> list[str]:
    terms = [
        token
        for token in re.split(r"\s+", query.strip().lower())
        if (len(token) >= 2 or token.isdigit()) and token not in _STOPWORDS
    ]
    return terms or [query.strip().lower()]


def _product_payload(row: dict) -> dict:
    return {
        "sku": str(row.get("sku") or ""),
        "name": str(row.get("name") or ""),
        "category": str(row.get("category") or ""),
        "unit": str(row.get("unit") or ""),
        "currency": str(row.get("currency") or "").strip(),
        "price": _money(row.get("price")),
        "available": int(row.get("available") or 0),
    }


def _result(
    status: str,
    data: Any,
    *,
    source: dict,
    extra: dict | None = None,
) -> ToolResult:
    payload = {"status": status, "data": data, "source_ref": source["resource_ref"]}
    if extra:
        payload.update(extra)
    return ToolResult(
        output=json.dumps(payload, ensure_ascii=False, default=str),
        meta={
            "status": status,
            "source_id": source["source_id"],
            "connector_id": source["connector_id"],
            "source_mode": source["source_mode"],
            "resource_ref": source["resource_ref"],
        },
    )


class FindProductsTool(Tool):
    name: ClassVar[str] = "find_products"
    description: ClassVar[str] = (
        "Busca productos reales por nombre o SKU en la base conectada. "
        "Devuelve sku, nombre, categoría, unidad, precio, moneda y stock "
        "disponible. Úsala para catálogo, precios y disponibilidad; no "
        "inventes valores."
    )
    input_schema: ClassVar[dict] = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "minLength": 1, "maxLength": 120},
            "question": {"type": "string", "minLength": 1, "maxLength": 120},
            "category": {"type": "string", "maxLength": 80},
            "unit": {"type": "string", "maxLength": 40},
            "max_results": {"type": "integer", "minimum": 1, "maximum": 20},
        },
    }
    permission: ClassVar[str] = "tool:query_database"
    timeout_seconds: ClassVar[float] = 30.0

    async def execute(self, ctx: ToolContext, arguments: dict) -> ToolResult:
        query = str(
            arguments.get("query") or arguments.get("question") or ""
        ).strip()
        if not query:
            return ToolResult(error="INVALID_ARGUMENT: query requerida")
        source, session, error = await _authorized_catalog_source(
            ctx, "store.products.search"
        )
        if error or source is None or session is None:
            return ToolResult(error=error or "SOURCE_UNAVAILABLE")
        limit = int(arguments.get("max_results") or 10)
        limit = max(1, min(limit, 20))
        terms = _search_terms(query)[:6]
        term_params = {
            f"q{index + 1}": f"%{term}%" for index, term in enumerate(terms)
        }
        for index in range(len(terms) + 1, 7):
            term_params[f"q{index}"] = None
        try:
            rows = await _run_catalog_query(
                session,
                "SELECT sku, name, category, unit, price, currency, available "
                "FROM bodega.product_catalog_v "
                "WHERE (CAST(:q1 AS text) IS NULL OR name ILIKE CAST(:q1 AS text) "
                "       OR sku ILIKE CAST(:q1 AS text)) "
                "AND (CAST(:q2 AS text) IS NULL OR name ILIKE CAST(:q2 AS text) "
                "     OR sku ILIKE CAST(:q2 AS text)) "
                "AND (CAST(:q3 AS text) IS NULL OR name ILIKE CAST(:q3 AS text) "
                "     OR sku ILIKE CAST(:q3 AS text)) "
                "AND (CAST(:q4 AS text) IS NULL OR name ILIKE CAST(:q4 AS text) "
                "     OR sku ILIKE CAST(:q4 AS text)) "
                "AND (CAST(:q5 AS text) IS NULL OR name ILIKE CAST(:q5 AS text) "
                "     OR sku ILIKE CAST(:q5 AS text)) "
                "AND (CAST(:q6 AS text) IS NULL OR name ILIKE CAST(:q6 AS text) "
                "     OR sku ILIKE CAST(:q6 AS text)) "
                "AND (:category = '' OR category = :category) "
                "AND (:unit = '' OR unit = :unit) "
                "ORDER BY name, sku LIMIT :limit",
                {
                    **term_params,
                    "category": str(arguments.get("category") or ""),
                    "unit": str(arguments.get("unit") or ""),
                    "limit": limit,
                },
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(error=f"DATA_QUERY_FAILED: {str(exc)[:200]}")
        data = [_product_payload(row) for row in rows]
        return _result("FOUND" if data else "NOT_FOUND", data, source=source)


class GetProductTool(Tool):
    name: ClassVar[str] = "get_product"
    description: ClassVar[str] = (
        "Obtiene un producto por SKU exacto. Devuelve NOT_FOUND o "
        "MULTIPLE_MATCHES; nunca elige uno al azar."
    )
    input_schema: ClassVar[dict] = {
        "type": "object",
        "required": ["sku"],
        "properties": {"sku": {"type": "string", "minLength": 1, "maxLength": 80}},
    }
    permission: ClassVar[str] = "tool:query_database"
    timeout_seconds: ClassVar[float] = 30.0

    async def execute(self, ctx: ToolContext, arguments: dict) -> ToolResult:
        sku = str(arguments.get("sku") or "").strip()
        if not sku:
            return ToolResult(error="INVALID_ARGUMENT: sku requerido")
        source, session, error = await _authorized_catalog_source(
            ctx, "store.product.get"
        )
        if error or source is None or session is None:
            return ToolResult(error=error or "SOURCE_UNAVAILABLE")
        try:
            rows = await _run_catalog_query(
                session,
                "SELECT sku, name, category, unit, price, currency, available "
                "FROM bodega.product_catalog_v WHERE sku = :sku LIMIT 2",
                {"sku": sku},
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(error=f"DATA_QUERY_FAILED: {str(exc)[:200]}")
        if not rows:
            return _result("NOT_FOUND", None, source=source)
        if len(rows) > 1:
            return _result(
                "MULTIPLE_MATCHES",
                [_product_payload(row) for row in rows],
                source=source,
            )
        return _result("FOUND", _product_payload(rows[0]), source=source)


class GetPriceAndStockTool(Tool):
    name: ClassVar[str] = "get_price_and_stock"
    description: ClassVar[str] = (
        "Devuelve precio, moneda y stock disponible reales para un SKU y una "
        "cantidad. No crea carrito ni orden."
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
        source, session, error = await _authorized_catalog_source(
            ctx, "store.price.get"
        )
        if error or source is None or session is None:
            return ToolResult(error=error or "SOURCE_UNAVAILABLE")
        try:
            rows = await _run_catalog_query(
                session,
                "SELECT sku, name, category, unit, price, currency, available "
                "FROM bodega.product_catalog_v WHERE sku = :sku LIMIT 2",
                {"sku": sku},
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(error=f"DATA_QUERY_FAILED: {str(exc)[:200]}")
        if not rows:
            return _result("NOT_FOUND", None, source=source)
        if len(rows) > 1:
            return _result(
                "MULTIPLE_MATCHES",
                [_product_payload(row) for row in rows],
                source=source,
            )
        product = _product_payload(rows[0])
        available = int(product["available"])
        if available <= 0:
            return _result("OUT_OF_STOCK", product, source=source)
        if available < quantity:
            return _result(
                "INSUFFICIENT_STOCK",
                product,
                source=source,
                extra={"requested": quantity, "available": available},
            )
        try:
            line_total = (
                Decimal(product["price"]) * Decimal(quantity)
            ).quantize(Decimal("0.01"))
        except (InvalidOperation, TypeError, ValueError):
            return ToolResult(error="INVALID_PRICE: precio no decimal")
        return _result(
            "FOUND",
            {
                **product,
                "requested": quantity,
                "line_total": str(line_total),
                "observed_at": datetime.now(timezone.utc).isoformat(),
            },
            source=source,
            extra={"pricing": "unit_price_and_backend_line_total"},
        )
