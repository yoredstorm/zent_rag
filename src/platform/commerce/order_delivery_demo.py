# =============================================================================
# Retail Order Delivery Demo - pedido, cliente y delivery simulado.
# =============================================================================
# Flujo funcional para una bodega:
#   1. consulta precio y stock reales en bodega.product_catalog_v;
#   2. decide si hay stock;
#   3. consulta si el cliente tiene pedidos previos;
#   4. decide delivery o recojo;
#   5. crea el pedido y reserva stock en bodega.*;
#   6. pide aprobación humana para simular el pago;
#   7. confirma stock y registra el resultado.
#
# La venta vive en bodega.orders. No hay cobro real ni courier.
# El delivery es una rama del workflow y un BusinessResult; no escribe
# sales.orders.
# =============================================================================
from __future__ import annotations

from typing import Any
from uuid import uuid4

TEMPLATE_SLUG = "retail_order_delivery_demo"
TEMPLATE_NAME = "Bodega: pedido, cliente y delivery (demo)"
TEMPLATE_CATEGORY = "ventas"
TEMPLATE_DESCRIPTION = (
    "Simula una venta de bodega: valida stock, revisa si el cliente tiene "
    "pedidos, elige delivery o recojo, reserva stock y pide aprobación humana "
    "para confirmar la venta."
)
PACKAGE_VERSION = "1.0.0"

DEFAULT_PARAMETERS: dict[str, Any] = {
    "currency": "PEN",
    "reservation_ttl_seconds": 900,
    "approval_expires_minutes": 60,
    "default_address": "Av. Demo 123",
}

CAPABILITIES = (
    "bodega.product.get",
    "p19.customer.orders",
    "bodega.order.create",
    "bodega.stock.reserve_batch",
    "bodega.stock.commit_batch",
    "bodega.stock.release_batch",
)


def _node(
    nid: str,
    ntype: str,
    label: str,
    config: dict[str, Any] | None = None,
    ports: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": nid,
        "type": ntype,
        "label": label,
        "config": config or {},
        "input_ports": [{"name": "in", "type": "json"}],
        "output_ports": [{"name": name, "type": "json"} for name in (ports or ["out"])],
        "retry_policy": {"max_attempts": 1, "backoff_seconds": 0},
        "timeout_ms": 60000,
        "error_policy": "fail",
        "metadata": {},
    }


def _edge(
    eid: str,
    frm: str,
    to: str,
    *,
    from_port: str = "out",
    label: str | None = None,
) -> dict[str, Any]:
    edge: dict[str, Any] = {
        "id": eid,
        "from_node": frm,
        "from_port": from_port,
        "to_node": to,
        "to_port": "in",
    }
    if label:
        edge["label"] = label
    return edge


def build_graph(parameters: dict[str, Any] | None = None) -> dict[str, Any]:
    """Grafo del ejemplo. Entrada manual por payload del run."""
    params = {**DEFAULT_PARAMETERS, **(parameters or {})}

    nodes = [
        _node(
            "inicio",
            "trigger_webhook",
            "Simular pedido",
            {"note": "Ejecutar manualmente con customer_ref, sku, quantity y delivery."},
            ports=["out"],
        ),
        _node(
            "guardar_pedido",
            "state_merge",
            "Guardar datos del pedido",
            {
                "path": "pedido",
                "value": {
                    "customer_ref": "{{trigger.customer_ref}}",
                    "sku": "{{trigger.sku}}",
                    "quantity": "{{trigger.quantity}}",
                    "delivery": "{{trigger.delivery}}",
                    "address": "{{trigger.address}}",
                    "order_number": "{{trigger.order_number}}",
                },
            },
        ),
        _node(
            "precio",
            "data_query",
            "Precio y stock",
            {
                "capability": "bodega.product.get",
                "params": {"sku": "{{instance.state.pedido.sku}}"},
            },
        ),
        _node(
            "stock_ok",
            "condition",
            "¿Hay stock suficiente?",
            {
                "field": "{{nodes.precio.output.record.available}}",
                "operator": ">=",
                "value": "{{instance.state.pedido.quantity}}",
            },
            ports=["out", "then", "else"],
        ),
        _node(
            "sin_stock",
            "notify",
            "Sin stock",
            {
                "channel": "in_app",
                "title": "Sin stock",
                "message": (
                    "No hay stock suficiente para {{instance.state.pedido.sku}}. "
                    "Disponible: {{nodes.precio.output.record.available}}."
                ),
            },
        ),
        _node(
            "historial",
            "data_query",
            "Pedidos del cliente",
            {
                "capability": "p19.customer.orders",
                "params": {"customer_ref": "{{instance.state.pedido.customer_ref}}"},
            },
        ),
        _node(
            "recurrente",
            "condition",
            "¿Cliente con pedidos?",
            {
                "field": "{{nodes.historial.output.row_count}}",
                "operator": ">",
                "value": 0,
            },
            ports=["out", "then", "else"],
        ),
        _node(
            "marcar_recurrente",
            "state_set",
            "Cliente recurrente",
            {"path": "customer_type", "value": "recurrente"},
        ),
        _node(
            "marcar_nuevo",
            "state_set",
            "Cliente nuevo",
            {"path": "customer_type", "value": "nuevo"},
        ),
        _node(
            "delivery_check",
            "condition",
            "¿Delivery?",
            {
                "field": "{{instance.state.pedido.delivery}}",
                "operator": "==",
                "value": True,
            },
            ports=["out", "then", "else"],
        ),
        _node(
            "address_check",
            "condition",
            "¿Tiene dirección?",
            {
                "field": "{{instance.state.pedido.address}}",
                "operator": "!=",
                "value": "",
            },
            ports=["out", "then", "else"],
        ),
        _node(
            "sin_direccion",
            "notify",
            "Falta dirección",
            {
                "channel": "in_app",
                "title": "Delivery sin dirección",
                "message": "El pedido es delivery pero falta la dirección de entrega.",
            },
        ),
        _node(
            "marcar_delivery",
            "state_set",
            "Delivery",
            {"path": "delivery_mode", "value": "delivery"},
        ),
        _node(
            "marcar_recojo",
            "state_set",
            "Recojo",
            {"path": "delivery_mode", "value": "pickup"},
        ),
        _node(
            "crear_pedido",
            "capability_call",
            "Crear pedido Bodega",
            {
                "capability": "bodega.order.create",
                "inputs": {
                    "order_number": "{{trigger.order_number}}",
                    "customer_ref": "{{instance.state.pedido.customer_ref}}",
                    "currency": "{{variables.currency}}",
                    "items": [
                        {
                            "sku": "{{instance.state.pedido.sku}}",
                            "quantity": "{{instance.state.pedido.quantity}}",
                            "unit_price": "{{nodes.precio.output.record.price}}",
                        }
                    ],
                },
            },
        ),
        _node(
            "reservar",
            "capability_call",
            "Reservar stock",
            {
                "capability": "bodega.stock.reserve_batch",
                "inputs": {
                    "order_number": "{{nodes.crear_pedido.output.order_number}}",
                    "ttl_seconds": "{{variables.reservation_ttl_seconds}}",
                    "items": [
                        {
                            "sku": "{{instance.state.pedido.sku}}",
                            "quantity": "{{instance.state.pedido.quantity}}",
                        }
                    ],
                },
            },
        ),
        _node(
            "aprobacion",
            "human_approval",
            "Validar pago simulado",
            {
                "action": "Aprobar venta simulada",
                "summary": (
                    "Pedido {{nodes.crear_pedido.output.order_number}} · "
                    "{{nodes.crear_pedido.output.total}} {{nodes.crear_pedido.output.currency}} · "
                    "{{nodes.crear_pedido.output.items}} ítem(s) · "
                    "cliente {{instance.state.pedido.customer_ref}} ({{instance.state.customer_type}}) · "
                    "{{instance.state.delivery_mode}}"
                ),
                "data": {
                    "order_number": "{{nodes.crear_pedido.output.order_number}}",
                    "customer_ref": "{{instance.state.pedido.customer_ref}}",
                    "customer_type": "{{instance.state.customer_type}}",
                    "delivery_mode": "{{instance.state.delivery_mode}}",
                    "address": "{{instance.state.pedido.address}}",
                    "total": "{{nodes.crear_pedido.output.total}}",
                    "currency": "{{nodes.crear_pedido.output.currency}}",
                    "sku": "{{instance.state.pedido.sku}}",
                    "quantity": "{{instance.state.pedido.quantity}}",
                },
                "expires_minutes": 60,
            },
        ),
        _node(
            "commit",
            "capability_call",
            "Confirmar stock",
            {
                "capability": "bodega.stock.commit_batch",
                "inputs": {
                    "order_number": "{{nodes.crear_pedido.output.order_number}}",
                },
            },
        ),
        _node(
            "entrega_final",
            "condition",
            "¿Delivery o recojo?",
            {
                "field": "{{instance.state.delivery_mode}}",
                "operator": "==",
                "value": "delivery",
            },
            ports=["out", "then", "else"],
        ),
        _node(
            "aviso_delivery",
            "notify",
            "Pedido en reparto",
            {
                "channel": "in_app",
                "title": "Pedido en reparto",
                "message": (
                    "Pedido {{nodes.crear_pedido.output.order_number}} confirmado. "
                    "Sale a {{instance.state.pedido.address}}."
                ),
            },
        ),
        _node(
            "aviso_recojo",
            "notify",
            "Listo para recojo",
            {
                "channel": "in_app",
                "title": "Pedido listo para recojo",
                "message": (
                    "Pedido {{nodes.crear_pedido.output.order_number}} confirmado. "
                    "El cliente puede recogerlo."
                ),
            },
        ),
        _node(
            "resultado",
            "business_result",
            "Registrar venta simulada",
            {
                "title": "Venta simulada de bodega",
                "section": "completed",
                "summary": (
                    "Pedido {{nodes.crear_pedido.output.order_number}} · "
                    "{{nodes.crear_pedido.output.total}} {{nodes.crear_pedido.output.currency}} · "
                    "{{instance.state.pedido.customer_ref}} · {{instance.state.customer_type}} · "
                    "{{instance.state.delivery_mode}}"
                ),
            },
        ),
        _node("fin", "end", "Fin"),
        _node("fin_sin_stock", "end", "Fin sin stock"),
        _node("fin_sin_direccion", "end", "Fin sin dirección"),
    ]

    edges = [
        _edge("e1", "inicio", "guardar_pedido"),
        _edge("e1b", "guardar_pedido", "precio"),
        _edge("e2", "precio", "stock_ok"),
        _edge("e3", "stock_ok", "historial", from_port="then", label="sí"),
        _edge("e4", "stock_ok", "sin_stock", from_port="else", label="no"),
        _edge("e5", "sin_stock", "fin_sin_stock"),
        _edge("e6", "historial", "recurrente"),
        _edge("e7", "recurrente", "marcar_recurrente", from_port="then", label="sí"),
        _edge("e8", "recurrente", "marcar_nuevo", from_port="else", label="no"),
        _edge("e9", "marcar_recurrente", "delivery_check"),
        _edge("e10", "marcar_nuevo", "delivery_check"),
        _edge("e11", "delivery_check", "address_check", from_port="then", label="sí"),
        _edge("e12", "delivery_check", "marcar_recojo", from_port="else", label="no"),
        _edge("e13", "address_check", "marcar_delivery", from_port="then", label="sí"),
        _edge("e14", "address_check", "sin_direccion", from_port="else", label="no"),
        _edge("e15", "sin_direccion", "fin_sin_direccion"),
        _edge("e16", "marcar_delivery", "crear_pedido"),
        _edge("e17", "marcar_recojo", "crear_pedido"),
        _edge("e18", "crear_pedido", "reservar"),
        _edge("e19", "reservar", "aprobacion"),
        _edge("e20", "aprobacion", "commit"),
        _edge("e21", "commit", "entrega_final"),
        _edge("e22", "entrega_final", "aviso_delivery", from_port="then", label="delivery"),
        _edge("e23", "entrega_final", "aviso_recojo", from_port="else", label="recojo"),
        _edge("e24", "aviso_delivery", "resultado"),
        _edge("e25", "aviso_recojo", "resultado"),
        _edge("e26", "resultado", "fin"),
    ]

    return {
        "workflow_version": 2,
        "nodes": nodes,
        "edges": edges,
        "variables": params,
        "entrypoints": ["inicio"],
        "metadata": {
            "template": TEMPLATE_SLUG,
            "category": TEMPLATE_CATEGORY,
            "applies_to": ["WORKFLOWS"],
            "simulation": "manual_approval",
        },
    }


def template_row() -> dict[str, Any]:
    return {
        "slug": TEMPLATE_SLUG,
        "name": TEMPLATE_NAME,
        "description": TEMPLATE_DESCRIPTION,
        "category": TEMPLATE_CATEGORY,
        "trigger_type": "webhook",
        "trigger_config": {},
        "steps": [],
        "graph": build_graph(),
        "package": {
            "schema": "zent.workflow.package/v1",
            "package_version": PACKAGE_VERSION,
            "metadata": {
                "name": TEMPLATE_NAME,
                "description": TEMPLATE_DESCRIPTION,
                "category": TEMPLATE_CATEGORY,
                "applies_to": ["WORKFLOWS"],
            },
            "dependencies": [
                {"kind": "capability", "ref": ref, "requirement": "required"}
                for ref in CAPABILITIES
            ],
            "capabilities": [
                {"kind": "capability", "ref": ref, "requirement": "required"}
                for ref in CAPABILITIES
            ],
            "permissions": ["workflows:run", "workflow_approvals:approve"],
            "tests": [
                "cliente con pedidos + delivery + dirección",
                "cliente nuevo + recojo",
                "stock insuficiente",
                "delivery sin dirección",
            ],
            "security": {"contains_secrets": False, "tenant_scoped": True},
        },
    }


def demo_payload(
    *,
    customer_ref: str = "CUST-A",
    sku: str = "BD-ARROZ-01",
    quantity: int = 2,
    delivery: bool = True,
    address: str = "Av. Demo 123",
    order_number: str | None = None,
) -> dict[str, Any]:
    return {
        "customer_ref": customer_ref,
        "sku": sku,
        "quantity": quantity,
        "delivery": delivery,
        "address": address,
        "order_number": order_number or f"SIM-{customer_ref}-{uuid4().hex[:8].upper()}",
        "currency": "PEN",
    }
