# =============================================================================
# P20-11 — checkout manual MVP para el vendedor externo.
# =============================================================================
# Cierra el carrito temporal en una orden ZENT, proyecta la orden a Bodega,
# reserva stock batch, espera una aprobación humana (pago manual temporal),
# marca la orden pagada y commitea el stock.
#
# TEMPORAL: el nodo `manual_payment_validation` se reemplaza por Stripe/PSP
# real. No cobra, no acepta "ya pagué" del cliente y está bloqueado en
# producción.
# =============================================================================
from __future__ import annotations

from typing import Any

from src.platform.commerce import contracts as C

TEMPLATE_SLUG = "retail_checkout_manual"
TEMPLATE_NAME = "Retail Checkout Manual (MVP temporal)"
TEMPLATE_DESCRIPTION = (
    "Cierra el carrito de la conversación, reserva stock real y valida el pago "
    "con aprobación humana. Nodo manual temporal hasta integrar Stripe/PSP."
)
TEMPLATE_CATEGORY = "ventas"
PACKAGE_VERSION = "1.0.0"

DEFAULT_PARAMETERS: dict[str, Any] = {
    "currency": "PEN",
    "cart_ttl_seconds": 3600,
    "reservation_ttl_seconds": 900,
    "manual_instructions": (
        "Pago manual MVP: verifica el abono sandbox y aprueba este paso. "
        "Este nodo es temporal."
    ),
}

DEPENDENCIES: list[dict[str, str]] = [
    {"kind": "capability", "ref": C.CAP_CART_GET, "requirement": "required"},
    {"kind": "capability", "ref": C.CAP_ORDER_CREATE, "requirement": "required"},
    {"kind": "capability", "ref": C.CAP_ORDER_MARK_PAID, "requirement": "required"},
    {"kind": "capability", "ref": "bodega.order.create", "requirement": "required"},
    {
        "kind": "capability",
        "ref": "bodega.stock.reserve_batch",
        "requirement": "required",
    },
    {
        "kind": "capability",
        "ref": "bodega.stock.commit_batch",
        "requirement": "required",
    },
    {
        "kind": "capability",
        "ref": "bodega.stock.release_batch",
        "requirement": "optional",
    },
    {"kind": "capability", "ref": "payments.manual.validate", "requirement": "required"},
    {"kind": "capability", "ref": "conversation.send", "requirement": "required"},
]


def _node(
    node_id: str,
    node_type: str,
    label: str,
    config: dict[str, Any] | None = None,
    *,
    ports: list[str] | None = None,
    error_policy: str | None = None,
) -> dict[str, Any]:
    node: dict[str, Any] = {
        "id": node_id,
        "type": node_type,
        "label": label,
        "config": config or {},
        "input_ports": [{"name": "in", "type": "json"}],
        "output_ports": [
            {"name": name, "type": "json"} for name in (ports or ["out"])
        ],
    }
    if error_policy:
        node["error_policy"] = error_policy
    return node


def _edge(
    edge_id: str,
    source: str,
    target: str,
    *,
    from_port: str = "out",
) -> dict[str, Any]:
    return {
        "id": edge_id,
        "from_node": source,
        "from_port": from_port,
        "to_node": target,
        "to_port": "in",
    }


def build_graph(parameters: dict[str, Any] | None = None) -> dict[str, Any]:
    params = {**DEFAULT_PARAMETERS, **(parameters or {})}
    nodes = [
        _node(
            "pedido",
            "trigger_webhook",
            "Checkout solicitado",
            {},
        ),
        _node(
            "carrito",
            "capability_call",
            "Leer carrito",
            {
                "capability": C.CAP_CART_GET,
                "inputs": {
                    "conversation_id": "{{trigger.conversation_id}}",
                    "ttl_seconds": "{{variables.cart_ttl_seconds}}",
                },
            },
        ),
        _node(
            "carrito_lleno",
            "condition",
            "¿Carrito con items?",
            {
                "field": "{{nodes.carrito.output.count}}",
                "operator": ">",
                "value": 0,
            },
            ports=["out", "then", "else"],
        ),
        _node(
            "crear_orden",
            "capability_call",
            "Crear orden ZENT",
            {
                "capability": C.CAP_ORDER_CREATE,
                "inputs": {
                    "conversation_id": "{{trigger.conversation_id}}",
                    "currency": "{{variables.currency}}",
                    "customer": {
                        "ref": "{{trigger.customer_ref}}",
                        "name": "{{trigger.customer_name}}",
                    },
                    "business_operation_id": "{{trigger.order_operation_id}}",
                },
            },
        ),
        _node(
            "proyectar_bodega",
            "capability_call",
            "Proyectar orden a Bodega",
            {
                "capability": "bodega.order.create",
                "inputs": {
                    "order_number": "{{nodes.crear_orden.output.order_number}}",
                    "customer_ref": "{{trigger.customer_ref}}",
                    "currency": "{{nodes.crear_orden.output.currency}}",
                    "items": "{{nodes.carrito.output.items}}",
                },
            },
        ),
        _node(
            "reservar_stock",
            "capability_call",
            "Reservar stock real",
            {
                "capability": "bodega.stock.reserve_batch",
                "inputs": {
                    "order_number": "{{nodes.crear_orden.output.order_number}}",
                    "items": "{{nodes.carrito.output.items}}",
                    "ttl_seconds": "{{variables.reservation_ttl_seconds}}",
                },
            },
        ),
        _node(
            "instrucciones",
            "capability_call",
            "Enviar instrucciones",
            {
                "capability": "conversation.send",
                "inputs": {
                    "title": "Pago manual pendiente",
                    "conversation_id": "{{trigger.conversation_id}}",
                    "message": (
                        "Pedido {{nodes.crear_orden.output.order_number}} por "
                        "{{nodes.crear_orden.output.total}} "
                        "{{nodes.crear_orden.output.currency}}.\n"
                        "{{variables.manual_instructions}}"
                    ),
                },
            },
            error_policy="continue",
        ),
        _node(
            "validar_pago",
            "manual_payment_validation",
            "Validación manual de pago (MVP temporal)",
            {
                "order_id": "{{nodes.crear_orden.output.order_id}}",
                "amount": "{{nodes.crear_orden.output.total}}",
                "currency": "{{nodes.crear_orden.output.currency}}",
                "payment_reference": "{{trigger.payment_reference}}",
                "instructions": "{{variables.manual_instructions}}",
                "expires_minutes": 1440,
            },
        ),
        _node(
            "marcar_pagada",
            "capability_call",
            "Marcar orden pagada",
            {
                "capability": C.CAP_ORDER_MARK_PAID,
                "inputs": {
                    "order_id": "{{nodes.crear_orden.output.order_id}}",
                    "payment_reference": (
                        "{{nodes.validar_pago.output.approval_id}}"
                    ),
                    "provider": "manual_mvp",
                },
            },
        ),
        _node(
            "commit_stock",
            "capability_call",
            "Confirmar stock Bodega",
            {
                "capability": "bodega.stock.commit_batch",
                "inputs": {
                    "order_number": "{{nodes.crear_orden.output.order_number}}",
                },
            },
        ),
        _node(
            "confirmar",
            "capability_call",
            "Confirmar al cliente",
            {
                "capability": "conversation.send",
                "inputs": {
                    "title": "Pedido confirmado",
                    "conversation_id": "{{trigger.conversation_id}}",
                    "message": (
                        "Listo. Pedido {{nodes.crear_orden.output.order_number}} "
                        "pagado y stock confirmado."
                    ),
                },
            },
            error_policy="continue",
        ),
        _node(
            "resultado",
            "business_result",
            "Registrar venta",
            {
                "title": "Venta concretada",
                "section": "sales",
                "summary": (
                    "Pedido {{nodes.crear_orden.output.order_number}} pagado "
                    "con validación manual MVP."
                ),
            },
            error_policy="continue",
        ),
        _node("fin", "end", "Fin"),
        _node(
            "carrito_vacio",
            "capability_call",
            "Carrito vacío",
            {
                "capability": "conversation.send",
                "inputs": {
                    "title": "Carrito vacío",
                    "conversation_id": "{{trigger.conversation_id}}",
                    "message": "No hay productos en el carrito para cobrar.",
                },
            },
            error_policy="continue",
        ),
        _node("fin_vacio", "end", "Fin (sin items)"),
    ]
    edges = [
        _edge("e1", "pedido", "carrito"),
        _edge("e2", "carrito", "carrito_lleno"),
        _edge("e3", "carrito_lleno", "crear_orden", from_port="then"),
        _edge("e4", "crear_orden", "proyectar_bodega"),
        _edge("e5", "proyectar_bodega", "reservar_stock"),
        _edge("e6", "reservar_stock", "instrucciones"),
        _edge("e7", "instrucciones", "validar_pago"),
        _edge("e8", "validar_pago", "marcar_pagada"),
        _edge("e9", "marcar_pagada", "commit_stock"),
        _edge("e10", "commit_stock", "confirmar"),
        _edge("e11", "confirmar", "resultado"),
        _edge("e12", "resultado", "fin"),
        _edge("e13", "carrito_lleno", "carrito_vacio", from_port="else"),
        _edge("e14", "carrito_vacio", "fin_vacio"),
    ]
    return {
        "workflow_version": 2,
        "nodes": nodes,
        "edges": edges,
        "variables": params,
        "entrypoints": ["pedido"],
        "metadata": {
            "template": TEMPLATE_SLUG,
            "category": TEMPLATE_CATEGORY,
            "applies_to": ["WORKFLOWS"],
            "temporary_manual_payment": True,
        },
    }


def build_package(parameters: dict[str, Any] | None = None) -> dict[str, Any]:
    params = {**DEFAULT_PARAMETERS, **(parameters or {})}
    return {
        "schema": "zent.workflow.package/v1",
        "package_version": PACKAGE_VERSION,
        "metadata": {
            "name": TEMPLATE_NAME,
            "description": TEMPLATE_DESCRIPTION,
            "category": TEMPLATE_CATEGORY,
            "applies_to": ["WORKFLOWS"],
            "min_zent_version": None,
        },
        "dependencies": list(DEPENDENCIES),
        "capabilities": [d for d in DEPENDENCIES if d["kind"] == "capability"],
        "events": [],
        "parameters": params,
        "permissions": ["workflows:run", "external_actions:execute"],
        "tests": [
            "carrito con items → orden ZENT + proyección Bodega + reserva",
            "aprobación humana → orden PAID + stock Bodega committed",
            "carrito vacío → no crea orden",
            "producción → nodo manual bloqueado",
        ],
        "security": {"contains_secrets": False, "tenant_scoped": False},
    }


def template_row() -> dict[str, Any]:
    return {
        "slug": TEMPLATE_SLUG,
        "name": TEMPLATE_NAME,
        "description": TEMPLATE_DESCRIPTION,
        "category": TEMPLATE_CATEGORY,
        "trigger_type": "webhook",
        "trigger_config": {},
        "graph": build_graph(),
        "package": build_package(),
    }


def marketplace_product_row() -> dict[str, Any]:
    capabilities = [d["ref"] for d in DEPENDENCIES if d["kind"] == "capability"]
    return {
        "slug": TEMPLATE_SLUG.replace("_", "-"),
        "name": TEMPLATE_NAME,
        "short_description": TEMPLATE_DESCRIPTION,
        "long_description": (
            "Checkout externo MVP: carrito temporal, orden ZENT, proyección a "
            "Bodega, reserva/commit de stock y pago manual con aprobación. "
            "Temporal hasta Stripe/PSP."
        ),
        "product_type": "WORKFLOW_TEMPLATE",
        "version": 1,
        "status": "PUBLISHED",
        "category": "sales",
        "applies_to": ["WORKFLOWS"],
        "capabilities": capabilities,
        "events": [],
        "included_assets": [
            {"kind": "workflow_template", "ref": TEMPLATE_SLUG, "alias": "checkout"}
        ],
        "pricing": {"model": "FREE"},
        "entitlements": {"workflows": 1},
        "configuration_schema": {
            "type": "object",
            "properties": {
                "currency": {"type": "string", "default": "PEN"},
                "cart_ttl_seconds": {"type": "integer", "default": 3600},
                "reservation_ttl_seconds": {"type": "integer", "default": 900},
                "manual_instructions": {"type": "string"},
            },
        },
        "security": {
            "contains_secrets": False,
            "monetary_values": "server_side",
            "llm_controls_amount": False,
        },
        "privacy": {"contains_personal_data": True, "data_classes": ["customer_contact"]},
        "certification": {"gold_workflow": False, "temporary": True},
        "featured": {"homepage": False},
        "tags": ["retail", "checkout", "manual", "mvp"],
    }


def snapshot_payload() -> dict[str, Any]:
    return {
        "template": template_row(),
        "product": marketplace_product_row(),
    }


__all__ = [
    "DEFAULT_PARAMETERS",
    "DEPENDENCIES",
    "TEMPLATE_SLUG",
    "build_graph",
    "build_package",
    "marketplace_product_row",
    "snapshot_payload",
    "template_row",
]

