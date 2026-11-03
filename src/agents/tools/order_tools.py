# =============================================================================
# P20-12 — postventa segura: el cliente solo ve SUS pedidos.
# =============================================================================
# Sin identidad verificada no se leen órdenes externas. Para el MVP, la
# identidad es la conversación autenticada: la orden debe tener el mismo
# `conversation_id` que la sesión actual. Un número de orden ajeno devuelve
# NOT_FOUND, nunca datos ni existencia.
# =============================================================================
from __future__ import annotations

import json
from typing import ClassVar

from src.agents.tools.base import Tool, ToolContext, ToolResult
from src.platform.commerce import store


def _evidence(order: dict) -> list[dict]:
    ref = f"order:{order.get('order_id')}:{order.get('status')}"
    return [
        {
            "ref": ref,
            "content": json.dumps(
                {
                    "source": "commerce_order",
                    "order_id": order.get("order_id"),
                    "order_number": order.get("order_number"),
                    "status": order.get("status"),
                    "total": order.get("total"),
                    "currency": order.get("currency"),
                    "items": order.get("items") or [],
                    "payment_status": order.get("payment_status"),
                    "created_at": order.get("created_at"),
                    "paid_at": order.get("paid_at"),
                },
                ensure_ascii=False,
                default=str,
            ),
            "source_type": "commerce_order",
            "title": f"Pedido {order.get('order_number')}",
            "retrieval": "commerce_order",
        }
    ]


class GetMyOrderTool(Tool):
    name: ClassVar[str] = "get_my_order"
    description: ClassVar[str] = (
        "Consulta el estado del pedido de ESTA conversación. Si das un número "
        "de orden, solo lo devuelve cuando pertenece al mismo cliente. No lee "
        "pedidos de otras conversaciones ni de Bodega sin identidad."
    )
    input_schema: ClassVar[dict] = {
        "type": "object",
        "properties": {
            "order_number": {"type": "string", "maxLength": 80},
        },
    }
    permission: ClassVar[str] = "tool:query_database"
    timeout_seconds: ClassVar[float] = 30.0

    async def execute(self, ctx: ToolContext, arguments: dict) -> ToolResult:
        if ctx.conversation_id is None:
            return ToolResult(
                error=(
                    "IDENTITY_REQUIRED: la consulta de pedidos necesita una "
                    "conversación autenticada"
                )
            )
        order_number = str(arguments.get("order_number") or "").strip() or None
        try:
            order = await store.get_order_for_conversation(
                ctx.tenant_id,
                conversation_id=str(ctx.conversation_id),
                order_number=order_number,
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(error=f"ORDER_READ_FAILED: {str(exc)[:180]}")
        if order is None:
            return ToolResult(
                output=json.dumps(
                    {
                        "status": "NOT_FOUND",
                        "data": None,
                        "message": "No hay un pedido de esta conversación con ese número.",
                    },
                    ensure_ascii=False,
                ),
                meta={
                    "status": "NOT_FOUND",
                    "evidence": [
                        {
                            "ref": f"order:none:{ctx.conversation_id}",
                            "content": (
                                "No existe un pedido asociado a esta conversación "
                                "con el número consultado."
                            ),
                            "source_type": "commerce_order",
                            "title": "Sin pedido en esta conversación",
                            "retrieval": "commerce_order",
                        }
                    ],
                },
            )
        payload = {
            "status": "FOUND",
            "data": {
                "order_id": order.get("order_id"),
                "order_number": order.get("order_number"),
                "status": order.get("status"),
                "total": order.get("total"),
                "currency": order.get("currency"),
                "items": order.get("items") or [],
                "payment_status": order.get("payment_status"),
                "payment_reference": order.get("payment_reference"),
                "created_at": order.get("created_at"),
                "paid_at": order.get("paid_at"),
            },
        }
        return ToolResult(
            output=json.dumps(payload, ensure_ascii=False, default=str),
            meta={
                "status": "FOUND",
                "order_id": order.get("order_id"),
                "source_ref": f"order:{order.get('order_id')}",
                "evidence": _evidence(order),
            },
        )


__all__ = ["GetMyOrderTool"]
