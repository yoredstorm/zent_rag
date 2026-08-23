# =============================================================================
# Demo Farmacia — tools de dominio del Agent Runtime (vertical pluggable)
# =============================================================================
# Tools determinísticas con queries parametrizadas (read-only session).
# NUNCA SQL generado por el modelo: solo parámetros validados.
# Se cargan vía RAG_AGENT_TOOL_MODULES=src.verticals.demo_farmacia.tools
# =============================================================================
from __future__ import annotations

import time
from typing import ClassVar

from sqlalchemy import text

from src.agents.tools.base import Tool, ToolContext, ToolResult
from src.agents.tools.registry import register_tool
from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)


async def _query(
    sql: str,
    params: dict,
    *,
    limit: int = 5,
) -> tuple[list[str], list[list[str]]]:
    from src.infrastructure.postgres.readonly_session import get_readonly_session

    session = await get_readonly_session()
    try:
        result = await session.execute(text(sql), params)
        rows = result.fetchmany(limit)
        columns = list(result.keys()) if rows else []
        return columns, [[str(v) for v in row] for row in rows]
    finally:
        await session.close()


def _format(columns: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return "(no results)"
    header = " | ".join(columns)
    return header + "\n" + "\n".join(" | ".join(r) for r in rows)


class GetProductTool(Tool):
    """Busca productos por nombre en el catálogo del tenant."""

    name: ClassVar[str] = "get_product"
    description: ClassVar[str] = (
        "Busca productos por nombre (ILIKE). Input: product (nombre parcial)."
    )
    input_schema: ClassVar[dict] = {
        "type": "object",
        "required": ["product"],
        "properties": {
            "product": {"type": "string", "minLength": 2, "maxLength": 200}
        },
    }

    async def execute(self, ctx: ToolContext, arguments: dict) -> ToolResult:
        start = time.perf_counter()
        try:
            columns, rows = await _query(
                "SELECT name, sku, price, currency, requires_prescription "
                "FROM farmacia.products "
                "WHERE organization_id = :org AND name ILIKE :term "
                "ORDER BY name LIMIT 5",
                {"org": ctx.tenant_id, "term": f"%{arguments['product']}%"},
            )
            return ToolResult(
                output=_format(columns, rows),
                latency_ms=(time.perf_counter() - start) * 1000,
            )
        except Exception as exc:
            return ToolResult(
                error=str(exc), latency_ms=(time.perf_counter() - start) * 1000
            )


class GetStockTool(Tool):
    """Consulta stock disponible de un producto."""

    name: ClassVar[str] = "get_stock"
    description: ClassVar[str] = (
        "Stock disponible de un producto. Input: product (nombre parcial)."
    )
    input_schema: ClassVar[dict] = {
        "type": "object",
        "required": ["product"],
        "properties": {
            "product": {"type": "string", "minLength": 2, "maxLength": 200}
        },
    }

    async def execute(self, ctx: ToolContext, arguments: dict) -> ToolResult:
        start = time.perf_counter()
        try:
            columns, rows = await _query(
                "SELECT p.name, i.quantity_available, i.quantity_reserved, "
                "i.warehouse_location, i.is_in_stock "
                "FROM farmacia.inventory i "
                "JOIN farmacia.products p ON i.product_id = p.id "
                "WHERE p.organization_id = :org AND p.name ILIKE :term "
                "ORDER BY p.name LIMIT 5",
                {"org": ctx.tenant_id, "term": f"%{arguments['product']}%"},
            )
            return ToolResult(
                output=_format(columns, rows),
                latency_ms=(time.perf_counter() - start) * 1000,
            )
        except Exception as exc:
            return ToolResult(
                error=str(exc), latency_ms=(time.perf_counter() - start) * 1000
            )


class GetCustomerTool(Tool):
    """Busca clientes por nombre o email."""

    name: ClassVar[str] = "get_customer"
    description: ClassVar[str] = (
        "Busca clientes por nombre/email (ILIKE). Input: customer (parcial)."
    )
    input_schema: ClassVar[dict] = {
        "type": "object",
        "required": ["customer"],
        "properties": {
            "customer": {"type": "string", "minLength": 2, "maxLength": 200}
        },
    }

    async def execute(self, ctx: ToolContext, arguments: dict) -> ToolResult:
        start = time.perf_counter()
        try:
            columns, rows = await _query(
                "SELECT name, email, phone, city, region, total_orders "
                "FROM farmacia.customers "
                "WHERE organization_id = :org "
                "AND (name ILIKE :term OR email ILIKE :term) "
                "ORDER BY name LIMIT 5",
                {"org": ctx.tenant_id, "term": f"%{arguments['customer']}%"},
            )
            return ToolResult(
                output=_format(columns, rows),
                latency_ms=(time.perf_counter() - start) * 1000,
            )
        except Exception as exc:
            return ToolResult(
                error=str(exc), latency_ms=(time.perf_counter() - start) * 1000
            )


class GetOrderTool(Tool):
    """Consulta un pedido/venta por identificador externo."""

    name: ClassVar[str] = "get_order"
    description: ClassVar[str] = (
        "Pedido de un cliente por código/order_number. "
        "Input: order (identificador externo o parcial)."
    )
    input_schema: ClassVar[dict] = {
        "type": "object",
        "required": ["order"],
        "properties": {
            "order": {"type": "string", "minLength": 2, "maxLength": 200}
        },
    }

    async def execute(self, ctx: ToolContext, arguments: dict) -> ToolResult:
        start = time.perf_counter()
        try:
            columns, rows = await _query(
                "SELECT s.id, c.name AS customer, p.name AS product, "
                "s.quantity, s.total_amount, s.sale_date, s.order_status "
                "FROM farmacia.sales s "
                "LEFT JOIN farmacia.customers c ON s.customer_id = c.external_id "
                "JOIN farmacia.products p ON s.product_id = p.id "
                "WHERE s.organization_id = :org "
                "AND (s.id::text ILIKE :term OR s.customer_id ILIKE :term) "
                "ORDER BY s.sale_date DESC LIMIT 5",
                {"org": ctx.tenant_id, "term": f"%{arguments['order']}%"},
            )
            return ToolResult(
                output=_format(columns, rows),
                latency_ms=(time.perf_counter() - start) * 1000,
            )
        except Exception as exc:
            return ToolResult(
                error=str(exc), latency_ms=(time.perf_counter() - start) * 1000
            )


def register() -> None:
    """Registra las tools del vertical (llamado por load_tool_modules)."""
    register_tool(GetProductTool())
    register_tool(GetStockTool())
    register_tool(GetCustomerTool())
    register_tool(GetOrderTool())
    logger.info("Demo farmacia tools registered", count=4)
