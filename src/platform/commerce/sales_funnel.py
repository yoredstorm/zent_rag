# =============================================================================
# Retail Sales Funnel — plantilla oficial de ventas por conversación
# =============================================================================
# Un solo sistema: es un `WorkflowDefinition` (IR v2) con nodos `wait_event`
# (WAIT durable) y `loop` (re-entrada acotada). El motor sigue siendo
# `execute_graph` y las dependencias se declaran como CAPACIDADES:
#
#   catalog.products.search · catalog.product.get · sales.cart.quote
#   inventory.stock.get     · sales.order.create   · sales.order.mark_paid
#   inventory.commit        · payments.checkout.create
#   conversation.send       · payment.succeeded (evento)
#
# El LLM no participa en ninguna ruta de dinero: precios, stock, total, cobro y
# estado de la orden salen de capacidades deterministas. Los puntos de intención
# usan condiciones deterministas sobre el texto; en Studio se pueden sustituir
# por un nodo de IA (`ai_decision`) sin tocar el resto del proceso.
# =============================================================================
from __future__ import annotations

from typing import Any

from src.platform.commerce import contracts as C

TEMPLATE_SLUG = "retail_sales_funnel"
TEMPLATE_NAME = "Retail Sales Funnel"
TEMPLATE_CATEGORY = "ventas"
TEMPLATE_DESCRIPTION = (
    "Convierte conversaciones en ventas usando tu catálogo, inventario y "
    "proveedor de pagos."
)
PACKAGE_VERSION = "1.0.0"

#: Parámetros configurables del embudo (graph.variables).
DEFAULT_PARAMETERS: dict[str, Any] = {
    "currency": "PEN",
    "maximum_cart_items": 20,
    "reservation_policy": C.RESERVATION_POLICY_CHECKOUT,
    "payment_timeout": "PT30M",
    "allow_alternatives": True,
    "allow_cross_sell": False,
    "require_stock": True,
    "confirmation_message": "¿Confirmas el pedido?",
    "completion_message": "¡Pago confirmado! Tu pedido está en preparación.",
    "closer_markers": "nada",
    "affirmative_operator": "not_contains",
    "affirmative_marker": "no",
}

DEPENDENCIES: list[dict[str, str]] = [
    {"kind": "capability", "ref": C.CAP_CATALOG_SEARCH, "requirement": "required"},
    {"kind": "capability", "ref": C.CAP_CATALOG_GET, "requirement": "required"},
    {"kind": "capability", "ref": C.CAP_CART_QUOTE, "requirement": "required"},
    {"kind": "capability", "ref": C.CAP_STOCK_GET, "requirement": "required"},
    {"kind": "capability", "ref": C.CAP_ORDER_CREATE, "requirement": "required"},
    {"kind": "capability", "ref": C.CAP_ORDER_MARK_PAID, "requirement": "required"},
    {"kind": "capability", "ref": C.CAP_STOCK_COMMIT, "requirement": "required"},
    {"kind": "capability", "ref": C.CAP_PAYMENT_CHECKOUT_CREATE, "requirement": "required"},
    {"kind": "capability", "ref": "conversation.send", "requirement": "required"},
    {"kind": "event", "ref": C.EVENT_PAYMENT_SUCCEEDED, "requirement": "required"},
    {"kind": "event", "ref": "conversation.message", "requirement": "required"},
]

#: Metadatos visuales del canvas: iconografía diferenciada por rol del nodo.
CANVAS_ICONS: dict[str, str] = {
    "trigger": "trigger",
    "ai": "ai",
    "data": "data",
    "decision": "decision",
    "action": "action",
    "wait": "wait",
    "payment": "payment",
    "business_result": "business_result",
    "end": "end",
}


def canvas_role(node_type: str, config: dict[str, Any] | None = None) -> str:
    """Rol visual del nodo (iconografía sin saturar colores)."""
    if node_type in ("trigger_event", "trigger_webhook", "trigger_schedule"):
        return "trigger"
    if node_type in ("ai_decision", "llm"):
        return "ai"
    if node_type == "wait_event":
        preset = str((config or {}).get("preset") or "")
        return "payment" if preset == "payment" else "wait"
    if node_type == "condition":
        return "decision"
    if node_type in ("end", "stop"):
        return "end"
    if node_type == "business_result":
        return "business_result"
    if node_type == "capability_call":
        capability = str((config or {}).get("capability") or "")
        if capability.startswith("catalog.") or capability.startswith("inventory."):
            return "data"
        if capability.startswith("payments."):
            return "payment"
        if capability.startswith("sales."):
            return "action"
        return "action"
    if node_type in ("state_get", "state_set", "state_merge", "state_append", "state_remove", "set_variable"):
        return "data"
    return "action"


def _node(
    nid: str,
    ntype: str,
    label: str,
    config: dict[str, Any] | None = None,
    ports: list[str] | None = None,
    *,
    error_policy: str = "fail",
) -> dict[str, Any]:
    config = config or {}
    return {
        "id": nid,
        "type": ntype,
        "label": label,
        "config": config,
        "input_ports": [{"name": "in", "type": "json"}],
        "output_ports": [{"name": name, "type": "json"} for name in (ports or ["out"])],
        "retry_policy": {"max_attempts": 1, "backoff_seconds": 0},
        "timeout_ms": 60000,
        "error_policy": error_policy,
        "metadata": {"canvas_role": canvas_role(ntype, config)},
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
    """Grafo del embudo (IR v2). Acíclico: los bucles son nodos `loop`."""
    params = {**DEFAULT_PARAMETERS, **(parameters or {})}
    payment_timeout = str(params.get("payment_timeout") or "PT30M")
    conversation_wait = 86400
    nodes: list[dict[str, Any]] = [
        _node(
            "cliente",
            "trigger_event",
            "Mensaje del cliente",
            {"event_type": "conversation.message"},
        ),
        _node(
            "buscar",
            "capability_call",
            "Buscar producto",
            {
                "capability": C.CAP_CATALOG_SEARCH,
                "inputs": {"query": "{{trigger.text}}", "limit": 3},
            },
            error_policy="continue",
        ),
        _node(
            "encontrado",
            "condition",
            "¿Encontrado?",
            {"field": "{{nodes.buscar.output.count}}", "operator": ">", "value": 0},
            ports=["out", "then", "else"],
        ),
        _node(
            "unico",
            "condition",
            "¿Una sola opción?",
            {"field": "{{nodes.buscar.output.count}}", "operator": "==", "value": 1},
            ports=["out", "then", "else"],
        ),
        _node(
            "agregar_directo",
            "state_append",
            "Agregar producto",
            {"path": "cart.items", "value": "{{nodes.buscar.output.cart_lines.0}}"},
        ),
        _node(
            "guardar_opciones",
            "state_set",
            "Guardar opciones",
            {"path": "catalog.options", "value": "{{nodes.buscar.output.products}}"},
            error_policy="continue",
        ),
        _node(
            "mostrar_opciones",
            "capability_call",
            "Mostrar opciones",
            {
                "capability": "conversation.send",
                "inputs": {
                    "title": "Opciones disponibles",
                    "message": "{{nodes.buscar.output.summary}}\n¿Cuál prefieres?",
                },
            },
            error_policy="continue",
        ),
        _node(
            "esperar_eleccion",
            "wait_event",
            "WAIT: elección del cliente",
            {"preset": "message", "timeout_seconds": conversation_wait, "on_timeout": "expire"},
            ports=["out", "timeout"],
        ),
        _node(
            "preguntar_otra_vez",
            "capability_call",
            "Pedir aclaración",
            {
                "capability": "conversation.send",
                "inputs": {
                    "title": "No encontré ese producto",
                    "message": (
                        "No encontré ese producto en el catálogo. "
                        "¿Me lo describes de otra forma?"
                    ),
                },
            },
            error_policy="continue",
        ),
        _node(
            "esperar_aclaracion",
            "wait_event",
            "WAIT: nueva descripción",
            {"preset": "message", "timeout_seconds": conversation_wait, "on_timeout": "expire"},
            ports=["out", "timeout"],
        ),
        _node(
            "reintentar_busqueda",
            "loop",
            "Volver a buscar",
            {"target": "buscar", "max_iterations": 12},
        ),
        _node(
            "elegir",
            "capability_call",
            "Interpretar selección",
            {"capability": C.CAP_CATALOG_GET, "inputs": {"query": "{{trigger.text}}"}},
            error_policy="continue",
        ),
        _node(
            "eleccion_valida",
            "condition",
            "¿Selección válida?",
            {"field": "{{nodes.elegir.output.found}}", "operator": "==", "value": True},
            ports=["out", "then", "else"],
        ),
        _node(
            "no_entendido",
            "capability_call",
            "Selección no entendida",
            {
                "capability": "conversation.send",
                "inputs": {
                    "title": "No te entendí",
                    "message": (
                        "No identifiqué cuál opción prefieres. "
                        "Dime el nombre del producto, por ejemplo: «arroz integral»."
                    ),
                },
            },
            error_policy="continue",
        ),
        _node(
            "esperar_reintento_eleccion",
            "wait_event",
            "WAIT: reintento de elección",
            {"preset": "message", "timeout_seconds": conversation_wait, "on_timeout": "expire"},
            ports=["out", "timeout"],
        ),
        _node(
            "reintentar_eleccion",
            "loop",
            "Volver a interpretar",
            {"target": "elegir", "max_iterations": 12},
        ),
        _node(
            "verificar_stock",
            "capability_call",
            "Verificar stock",
            {
                "capability": C.CAP_STOCK_GET,
                "inputs": {"product_id": "{{nodes.elegir.output.product.product_id}}"},
            },
            error_policy="continue",
        ),
        _node(
            "agregar_carrito",
            "state_append",
            "Actualizar carrito",
            {"path": "cart.items", "value": "{{nodes.elegir.output.cart_line}}"},
        ),
        _node(
            "resumen_carrito",
            "capability_call",
            "Calcular carrito",
            {"capability": C.CAP_CART_QUOTE, "inputs": {"items": "{{instance.state.cart.items}}"}},
            error_policy="continue",
        ),
        _node(
            "preguntar_mas",
            "capability_call",
            "¿Algo más?",
            {
                "capability": "conversation.send",
                "inputs": {
                    "title": "Carrito actualizado",
                    "message": "{{nodes.resumen_carrito.output.summary}}\n¿Deseas algo más?",
                },
            },
            error_policy="continue",
        ),
        _node(
            "esperar_mas",
            "wait_event",
            "WAIT: ¿algo más?",
            {"preset": "message", "timeout_seconds": conversation_wait, "on_timeout": "expire"},
            ports=["out", "timeout"],
        ),
        _node(
            "nada_mas",
            "condition",
            "¿Nada más?",
            {"field": "{{trigger.text}}", "operator": "contains", "value": "{{variables.closer_markers}}"},
            ports=["out", "then", "else"],
        ),
        _node(
            "volver_al_catalogo",
            "loop",
            "Volver al catálogo",
            {"target": "buscar", "max_iterations": 20},
        ),
        _node(
            "pedir_confirmacion",
            "capability_call",
            "Pedir confirmación",
            {
                "capability": "conversation.send",
                "inputs": {
                    "title": "Confirmar pedido",
                    "message": "{{nodes.resumen_carrito.output.summary}}\n{{variables.confirmation_message}}",
                },
            },
            error_policy="continue",
        ),
        _node(
            "esperar_confirmacion",
            "wait_event",
            "WAIT: confirmación",
            {"preset": "message", "timeout_seconds": conversation_wait, "on_timeout": "expire"},
            ports=["out", "timeout"],
        ),
        _node(
            "confirmado",
            "condition",
            "¿Confirmado?",
            {
                "field": "{{trigger.text}}",
                "operator": "{{variables.affirmative_operator}}",
                "value": "{{variables.affirmative_marker}}",
            },
            ports=["out", "then", "else"],
        ),
        _node(
            "confirmar_otra_vez",
            "loop",
            "Volver a pedir confirmación",
            {"target": "pedir_confirmacion", "max_iterations": 3},
        ),
        _node(
            "crear_orden",
            "capability_call",
            "Crear venta",
            {
                "capability": C.CAP_ORDER_CREATE,
                "inputs": {
                    "items": "{{instance.state.cart.items}}",
                    "currency": "{{variables.currency}}",
                    "conversation_id": "{{trigger.conversation_id}}",
                    "business_operation_id": "{{trigger.order_operation_id}}",
                    "reservation_policy": "{{variables.reservation_policy}}",
                },
            },
        ),
        _node(
            "crear_checkout",
            "capability_call",
            "Crear checkout",
            {
                "capability": C.CAP_PAYMENT_CHECKOUT_CREATE,
                "inputs": {"order_id": "{{nodes.crear_orden.output.order_id}}"},
            },
        ),
        _node(
            "enviar_pago",
            "capability_call",
            "QR / link de pago",
            {
                "capability": "conversation.send",
                "inputs": {
                    "title": "Pago pendiente",
                    "message": "{{nodes.crear_checkout.output.payment_instructions}}",
                },
            },
            error_policy="continue",
        ),
        _node(
            "esperar_pago",
            "wait_event",
            "WAIT: pago",
            {
                "preset": "payment",
                "timeout": payment_timeout,
                "on_timeout": "branch",
                "correlation": {
                    "payment_reference": "{{nodes.crear_orden.output.order_number}}"
                },
            },
            ports=["out", "timeout"],
        ),
        _node(
            "marcar_pagada",
            "capability_call",
            "Confirmar venta",
            {
                "capability": C.CAP_ORDER_MARK_PAID,
                "inputs": {
                    "order_id": "{{nodes.crear_orden.output.order_id}}",
                    "payment_reference": "{{trigger.payment_reference}}",
                    "provider": "{{trigger.provider}}",
                },
            },
            error_policy="continue",
        ),
        _node(
            "confirmar_inventario",
            "capability_call",
            "Actualizar inventario",
            {
                "capability": C.CAP_STOCK_COMMIT,
                "inputs": {"order_id": "{{nodes.crear_orden.output.order_id}}"},
            },
            error_policy="continue",
        ),
        _node(
            "mensaje_final",
            "capability_call",
            "Confirmación al cliente",
            {
                "capability": "conversation.send",
                "inputs": {
                    "title": "Pago confirmado",
                    "message": "{{variables.completion_message}}",
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
                "summary": "Pedido {{nodes.crear_orden.output.order_number}} pagado y confirmado.",
            },
            error_policy="continue",
        ),
        _node("fin", "end", "Fin"),
        _node(
            "pago_no_completado",
            "capability_call",
            "Pago no completado",
            {
                "capability": "conversation.send",
                "inputs": {
                    "title": "Pago no completado",
                    "message": (
                        "No recibimos el pago a tiempo y el pedido quedó cancelado. "
                        "Puedes pedirme de nuevo lo que necesitas."
                    ),
                },
            },
            error_policy="continue",
        ),
        _node(
            "cancelar_orden",
            "capability_call",
            "Cancelar venta",
            {"capability": C.CAP_ORDER_CANCEL, "inputs": {"order_id": "{{nodes.crear_orden.output.order_id}}"}},
            error_policy="continue",
        ),
        _node(
            "liberar_inventario",
            "capability_call",
            "Liberar inventario",
            {"capability": C.CAP_STOCK_RELEASE, "inputs": {"order_id": "{{nodes.crear_orden.output.order_id}}"}},
            error_policy="continue",
        ),
        _node("fin_pago", "end", "Fin (sin pago)"),
    ]

    edges: list[dict[str, Any]] = [
        _edge("e1", "cliente", "buscar"),
        _edge("e2", "buscar", "encontrado"),
        _edge("e3", "encontrado", "unico", from_port="then", label="sí"),
        _edge("e4", "encontrado", "preguntar_otra_vez", from_port="else", label="no"),
        _edge("e5", "unico", "agregar_directo", from_port="then", label="una sola"),
        _edge("e6", "unico", "guardar_opciones", from_port="else", label="varias"),
        _edge("e5b", "agregar_directo", "resumen_carrito"),
        _edge("e5c", "guardar_opciones", "mostrar_opciones"),
        _edge("e6b", "mostrar_opciones", "esperar_eleccion"),
        _edge("e7", "esperar_eleccion", "elegir"),
        _edge("e8", "preguntar_otra_vez", "esperar_aclaracion"),
        _edge("e9", "esperar_aclaracion", "reintentar_busqueda"),
        _edge("e10", "reintentar_busqueda", "buscar"),
        _edge("e11", "elegir", "eleccion_valida"),
        _edge("e12", "eleccion_valida", "verificar_stock", from_port="then", label="sí"),
        _edge("e13", "eleccion_valida", "no_entendido", from_port="else", label="no"),
        _edge("e14", "no_entendido", "esperar_reintento_eleccion"),
        _edge("e15", "esperar_reintento_eleccion", "reintentar_eleccion"),
        _edge("e16", "reintentar_eleccion", "elegir"),
        _edge("e17", "verificar_stock", "agregar_carrito"),
        _edge("e18", "agregar_carrito", "resumen_carrito"),
        _edge("e19", "resumen_carrito", "preguntar_mas"),
        _edge("e20", "preguntar_mas", "esperar_mas"),
        _edge("e21", "esperar_mas", "nada_mas"),
        _edge("e22", "nada_mas", "pedir_confirmacion", from_port="then", label="nada más"),
        _edge("e23", "nada_mas", "volver_al_catalogo", from_port="else", label="otro producto"),
        _edge("e24", "volver_al_catalogo", "buscar"),
        _edge("e25", "pedir_confirmacion", "esperar_confirmacion"),
        _edge("e26", "esperar_confirmacion", "confirmado"),
        _edge("e27", "confirmado", "crear_orden", from_port="then", label="sí"),
        _edge("e28", "confirmado", "confirmar_otra_vez", from_port="else", label="no"),
        _edge("e29", "confirmar_otra_vez", "pedir_confirmacion"),
        _edge("e30", "crear_orden", "crear_checkout"),
        _edge("e31", "crear_checkout", "enviar_pago"),
        _edge("e32", "enviar_pago", "esperar_pago"),
        _edge("e33", "esperar_pago", "marcar_pagada"),
        _edge("e34", "marcar_pagada", "confirmar_inventario"),
        _edge("e35", "confirmar_inventario", "mensaje_final"),
        _edge("e36", "mensaje_final", "resultado"),
        _edge("e37", "resultado", "fin"),
        _edge("e38", "esperar_pago", "pago_no_completado", from_port="timeout", label="sin pago"),
        _edge("e39", "pago_no_completado", "cancelar_orden"),
        _edge("e40", "cancelar_orden", "liberar_inventario"),
        _edge("e41", "liberar_inventario", "fin_pago"),
    ]
    return {
        "workflow_version": 2,
        "nodes": nodes,
        "edges": edges,
        "variables": params,
        "entrypoints": ["cliente"],
        "metadata": {
            "template": TEMPLATE_SLUG,
            "category": TEMPLATE_CATEGORY,
            "applies_to": ["WORKFLOWS", "AGENTS"],
            "canvas": {
                "legend": CANVAS_ICONS,
                "roles": {n["id"]: (n.get("metadata") or {}).get("canvas_role") for n in nodes},
            },
        },
    }


def build_package(parameters: dict[str, Any] | None = None) -> dict[str, Any]:
    """Paquete portable `zent.workflow.package/v1` de la plantilla."""
    params = {**DEFAULT_PARAMETERS, **(parameters or {})}
    return {
        "schema": "zent.workflow.package/v1",
        "package_version": PACKAGE_VERSION,
        "metadata": {
            "name": TEMPLATE_NAME,
            "description": TEMPLATE_DESCRIPTION,
            "category": TEMPLATE_CATEGORY,
            "applies_to": ["WORKFLOWS", "AGENTS"],
            "min_zent_version": None,
        },
        "dependencies": list(DEPENDENCIES),
        "capabilities": [d for d in DEPENDENCIES if d["kind"] == "capability"],
        "events": [d for d in DEPENDENCIES if d["kind"] == "event"],
        "parameters": params,
        "permissions": ["workflows:run", "external_actions:execute"],
        "tests": [
            "customer: quiero 1 kilo de arroz → opciones con precio real",
            "customer: mejor integral → carrito con arroz integral",
            "customer: también una leche → carrito con 2 líneas",
            "customer: nada más → resumen y confirmación",
            "customer: sí → checkout + QR",
            "provider: payment.succeeded → orden PAID + inventario confirmado",
        ],
        "security": {"contains_secrets": False, "tenant_scoped": False},
    }


def template_row() -> dict[str, Any]:
    return {
        "slug": TEMPLATE_SLUG,
        "name": TEMPLATE_NAME,
        "description": TEMPLATE_DESCRIPTION,
        "category": TEMPLATE_CATEGORY,
        "trigger_type": "event",
        "trigger_config": {"event_type": "conversation.message"},
        "graph": build_graph(),
        "package": build_package(),
    }


#: Contrato de cada capacidad y evento que el embudo publica en el catálogo de
#: assets (informativo para Studio/Marketplace; la ejecución vive en el binder).
CAPABILITY_SPECS: list[tuple[str, str, str]] = [
    (C.CAP_CATALOG_SEARCH, "Buscar productos", "Catálogo de productos del tenant"),
    (C.CAP_CATALOG_GET, "Obtener producto", "Producto del catálogo por id, sku o texto"),
    (C.CAP_CATALOG_PRICE, "Precio de producto", "Precio y moneda reales del catálogo"),
    (C.CAP_STOCK_GET, "Consultar stock", "Disponibilidad real por producto"),
    (C.CAP_STOCK_RESERVE, "Reservar stock", "Retiene stock sin venderlo"),
    (C.CAP_STOCK_RELEASE, "Liberar stock", "Devuelve stock reservado"),
    (C.CAP_STOCK_COMMIT, "Confirmar stock", "Descuenta stock tras el pago"),
    (C.CAP_ORDER_CREATE, "Crear venta", "Orden de venta con precios del catálogo"),
    (C.CAP_CART_QUOTE, "Cotizar carrito", "Total del carrito sin persistir"),
    (C.CAP_ORDER_GET, "Consultar venta", "Estado de la orden"),
    (C.CAP_ORDER_CONFIRM, "Confirmar venta", "Pasa la orden a espera de pago"),
    (C.CAP_ORDER_MARK_PAID, "Marcar pagada", "La orden pasa a PAID"),
    (C.CAP_ORDER_FULFILL, "Completar venta", "La orden pasa a FULFILLED"),
    (C.CAP_ORDER_CANCEL, "Cancelar venta", "La orden pasa a CANCELLED"),
    (C.CAP_PAYMENT_CHECKOUT_CREATE, "Crear checkout", "Sesión de pago con el proveedor del tenant"),
    (C.CAP_PAYMENT_QR_CREATE, "Crear QR", "QR o link de pago del checkout"),
    (C.CAP_PAYMENT_STATUS_GET, "Consultar pago", "Estado del pago"),
    (C.CAP_PAYMENT_CANCEL, "Cancelar pago", "Anula el checkout pendiente"),
    (C.CAP_PAYMENT_REFUND, "Reembolsar", "Devuelve un pago confirmado"),
    ("conversation.send", "Enviar mensaje", "Mensaje saliente al cliente del proceso"),
]

EVENT_SPECS: list[tuple[str, str]] = [
    (C.EVENT_PAYMENT_PENDING, "Pago iniciado y aún no confirmado"),
    (C.EVENT_PAYMENT_SUCCEEDED, "Pago confirmado por el proveedor"),
    (C.EVENT_PAYMENT_FAILED, "Pago rechazado por el proveedor"),
    (C.EVENT_PAYMENT_EXPIRED, "Pago expirado sin confirmarse"),
    (C.EVENT_PAYMENT_REFUNDED, "Pago devuelto al cliente"),
    ("conversation.message", "Mensaje entrante del cliente"),
]


def provider_kinds_for(capability_ref: str) -> list[str]:
    """Provider kinds con los que se puede resolver la capacidad."""
    if capability_ref.startswith("payments."):
        return [C.PAYMENT_PROVIDER_KIND]
    if capability_ref == "conversation.send":
        return ["conversation"]
    return ["commerce", "managed_db", "connected_db", "rest_api", "marketplace_action"]


PRODUCT_SLUG = "retail-sales-funnel"


def marketplace_product_row() -> dict[str, Any]:
    """Producto del Marketplace GLOBAL que publica el embudo (un solo catálogo)."""
    capabilities = [d["ref"] for d in DEPENDENCIES if d["kind"] == "capability"]
    events = [d["ref"] for d in DEPENDENCIES if d["kind"] == "event"]
    return {
        "slug": PRODUCT_SLUG,
        "name": TEMPLATE_NAME,
        "short_description": TEMPLATE_DESCRIPTION,
        "long_description": (
            "Embudo de ventas conversacional durable: entiende el pedido, busca "
            "en tu catálogo real, arma el carrito, confirma, cobra por QR o link "
            "y cierra la venta con inventario confirmado. Cada turno es un WAIT "
            "durable: el proceso sobrevive reinicios y no pierde el contexto."
        ),
        "product_type": "WORKFLOW_TEMPLATE",
        "version": 1,
        "status": "PUBLISHED",
        "category": "sales",
        "applies_to": ["WORKFLOWS", "AGENTS"],
        "capabilities": capabilities,
        "events": events,
        "included_assets": [
            {"kind": "workflow_template", "ref": TEMPLATE_SLUG, "alias": "funnel"},
            {"kind": "capability", "ref": C.CAP_CATALOG_SEARCH, "alias": "catalog"},
            {"kind": "capability", "ref": C.CAP_PAYMENT_CHECKOUT_CREATE, "alias": "payments"},
        ],
        "pricing": {"model": "FREE"},
        "entitlements": {"workflows": 1},
        "configuration_schema": {
            "type": "object",
            "properties": {
                "currency": {"type": "string", "default": "PEN"},
                "maximum_cart_items": {"type": "integer", "default": 20},
                "reservation_policy": {
                    "type": "string",
                    "enum": list(C.RESERVATION_POLICIES),
                    "default": C.RESERVATION_POLICY_CHECKOUT,
                },
                "payment_timeout": {"type": "string", "default": "PT30M"},
                "allow_alternatives": {"type": "boolean", "default": True},
                "allow_cross_sell": {"type": "boolean", "default": False},
                "require_stock": {"type": "boolean", "default": True},
                "confirmation_message": {"type": "string"},
                "completion_message": {"type": "string"},
            },
        },
        "security": {
            "contains_secrets": False,
            "monetary_values": "server_side",
            "llm_controls_amount": False,
        },
        "privacy": {"contains_personal_data": True, "data_classes": ["customer_contact"]},
        "certification": {"gold_workflow": True},
        "featured": {"homepage": True, "order": 1},
        "tags": ["ventas", "pagos", "conversacional", "durable"],
    }


def snapshot_payload() -> dict[str, Any]:
    """Payload completo que la migración 158 consume como snapshot congelado.

    La migración no puede importar esta capa (invariante de arquitectura), así
    que `scripts/seed_sales_funnel.py` escribe este payload en
    `src/infrastructure/db_init/seeds/retail_sales_funnel.json` y un test de
    certificación falla si el JSON se desvía de esta definición viva.
    """
    contracts: list[dict[str, Any]] = []
    for ref, name, description in CAPABILITY_SPECS:
        contract = C.contract_for(ref)
        contracts.append(
            {
                "ref": ref,
                "name": name,
                "description": description,
                "provider_kinds": provider_kinds_for(ref),
                "input_schema": contract.get("input") or {},
                "output_schema": contract.get("output") or {},
                "read_only": bool(contract.get("read_only", True)),
                "financial": bool(contract.get("financial", False)),
                "idempotency_required": str(contract.get("idempotency") or "") == "required",
            }
        )
    return {
        "template": template_row(),
        "product": marketplace_product_row(),
        "capability_contracts": contracts,
        "events": [{"event_type": e, "description": d} for e, d in EVENT_SPECS],
    }


#: Readiness que el Marketplace muestra antes de instalar (✓ / !).
def readiness_items() -> list[dict[str, Any]]:    return [
        {
            "key": "catalog",
            "label": "Catálogo",
            "capabilities": [C.CAP_CATALOG_SEARCH, C.CAP_CATALOG_GET],
            "hint": "Conecta tus productos o una base gestionada con el catálogo.",
        },
        {
            "key": "inventory",
            "label": "Inventario",
            "capabilities": [C.CAP_STOCK_GET, C.CAP_STOCK_COMMIT, C.CAP_STOCK_RELEASE],
            "hint": "Conecta tu stock real para reservar y confirmar inventario.",
        },
        {
            "key": "sales",
            "label": "Ventas",
            "capabilities": [C.CAP_ORDER_CREATE, C.CAP_ORDER_MARK_PAID, C.CAP_CART_QUOTE],
            "hint": "Zent crea la venta; no necesitas conectar nada.",
            "builtin": True,
        },
        {
            "key": "messaging",
            "label": "Mensajería",
            "capabilities": ["conversation.send"],
            "events": ["conversation.message"],
            "hint": "Canal de conversación para responder al cliente.",
            "builtin": True,
        },
        {
            "key": "payment",
            "label": "Pago",
            "capabilities": [C.CAP_PAYMENT_CHECKOUT_CREATE],
            "events": [C.EVENT_PAYMENT_SUCCEEDED],
            "hint": "IZIPAY está disponible; configura tus credenciales para cobrar.",
            "marketplace_filter": "payments",
        },
    ]
