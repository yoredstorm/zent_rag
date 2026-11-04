# =============================================================================
# Bodega conversacional - pedido paso a paso por chat.
# =============================================================================
# El cliente escribe; el workflow responde y espera el siguiente mensaje:
#
#   "tienes arroz?"  -> busca en el catalogo real (precio y stock)
#   "2"              -> cantidad
#   "delivery"       -> modalidad (o "recojo")
#   "Av. Demo 123"   -> direccion (solo delivery)
#   "si"             -> confirma; crea pedido, reserva stock y pide aprobacion
#
# Cada espera es un `wait_event` durable: la instancia se suspende y se
# reanuda con `conversation.message`. El estado sobrevive entre mensajes en
# `instance.state.order`.
#
# Reglas de dinero: precio, stock y total salen de `bodega.*`; el workflow no
# calcula ni inventa esos valores. La venta vive en `bodega.orders`.
# =============================================================================
from __future__ import annotations

from typing import Any
from uuid import uuid4

TEMPLATE_SLUG = "bodega_conversational_order"
TEMPLATE_NAME = "Bodega: pedido por conversación"
TEMPLATE_CATEGORY = "ventas"
TEMPLATE_DESCRIPTION = (
    "Pedido por chat en 8 fases: entrada, producto, cantidad, stock, entrega, "
    "confirmación, pedido y cierre. Cada pregunta pausa el proceso hasta el "
    "siguiente mensaje; el stock y el total salen de Bodega."
)
PACKAGE_VERSION = "1.0.0"

DEFAULT_PARAMETERS: dict[str, Any] = {
    "currency": "PEN",
    "reservation_ttl_seconds": 900,
    "approval_expires_minutes": 60,
    "max_matches": 2,
    "wait_timeout_seconds": 86400,
}

CAPABILITIES = (
    "bodega.product.search",
    "bodega.product.get",
    "bodega.order.create",
    "bodega.stock.reserve_batch",
    "bodega.stock.commit_batch",
    "bodega.stock.release_batch",
)

# El flujo se lee por fases. El id del nodo no cambia (los waits durables
# dependen de él); solo cambian la etiqueta visible, la nota y la columna.
PHASES: tuple[str, ...] = (
    "entrada",
    "producto",
    "cantidad",
    "stock",
    "entrega",
    "confirmacion",
    "pedido",
    "cierre",
    "fin",
)

PHASE_LABELS: dict[str, str] = {
    "entrada": "Entrada",
    "producto": "Producto",
    "cantidad": "Cantidad",
    "stock": "Stock",
    "entrega": "Entrega",
    "confirmacion": "Confirmación",
    "pedido": "Pedido",
    "cierre": "Cierre",
    "fin": "Fin",
}

NODE_COPY: dict[str, dict[str, str]] = {
    "cliente": {
        "phase": "entrada",
        "label": "Entrada · Mensaje del cliente",
        "note": "Cada mensaje inicia el pedido o reanuda la espera actual.",
    },
    "guardar_cliente": {
        "phase": "entrada",
        "label": "Entrada · Guardar cliente y pedido",
        "note": "Guarda customer_ref y order_number en el estado durable.",
    },
    "buscar": {
        "phase": "producto",
        "label": "Producto · Buscar catálogo",
        "note": "Consulta el catálogo real con el texto que escribió el cliente.",
    },
    "encontrado": {
        "phase": "producto",
        "label": "Producto · ¿Encontrado?",
        "note": "Si no hay coincidencias, avisa y termina sin pedido.",
    },
    "sin_producto": {
        "phase": "producto",
        "label": "Producto · Avisar no encontrado",
        "note": "Mensaje al cliente cuando el catálogo no devuelve opciones.",
    },
    "guardar_opciones": {
        "phase": "producto",
        "label": "Producto · Guardar opciones",
        "note": "Guarda las coincidencias para elegir después de la espera.",
    },
    "unico": {
        "phase": "producto",
        "label": "Producto · ¿Una sola opción?",
        "note": "Si hay una sola, se elige automáticamente.",
    },
    "elegir_uno": {
        "phase": "producto",
        "label": "Producto · Elegir opción 1",
        "note": "Toma la primera opción. También sirve cuando era la única.",
    },
    "pedir_opcion": {
        "phase": "producto",
        "label": "Producto · Preguntar cuál",
        "note": "Muestra hasta dos opciones y pide responder 1 o 2.",
    },
    "esperar_opcion": {
        "phase": "producto",
        "label": "Producto · Esperar elección",
        "note": "Pausa durable hasta que llegue la respuesta del cliente.",
    },
    "opcion_uno": {
        "phase": "producto",
        "label": "Producto · ¿Respondió 1?",
        "note": "Rama para la primera opción del catálogo.",
    },
    "elegir_dos": {
        "phase": "producto",
        "label": "Producto · Elegir opción 2",
        "note": "Toma la segunda opción del catálogo.",
    },
    "opcion_dos": {
        "phase": "producto",
        "label": "Producto · ¿Respondió 2?",
        "note": "Rama para la segunda opción del catálogo.",
    },
    "opcion_invalida": {
        "phase": "producto",
        "label": "Producto · Avisar opción inválida",
        "note": "Pide responder 1 o 2 sin crear un pedido.",
    },
    "repetir_opcion": {
        "phase": "producto",
        "label": "Producto · Repetir pregunta",
        "note": "Vuelve a preguntar sin crear ciclos en el grafo.",
    },
    "preguntar_cantidad": {
        "phase": "cantidad",
        "label": "Cantidad · Preguntar",
        "note": "Paso común para las dos opciones de producto.",
    },
    "esperar_cantidad": {
        "phase": "cantidad",
        "label": "Cantidad · Esperar respuesta",
        "note": "Pausa durable hasta que el cliente escribe la cantidad.",
    },
    "guardar_cantidad": {
        "phase": "cantidad",
        "label": "Cantidad · Guardar",
        "note": "Guarda la cantidad en el estado del pedido.",
    },
    "precio": {
        "phase": "stock",
        "label": "Stock · Consultar precio y stock",
        "note": "Lee precio y stock reales del producto elegido.",
    },
    "stock_ok": {
        "phase": "stock",
        "label": "Stock · ¿Hay suficiente?",
        "note": "Compara el stock disponible con la cantidad pedida.",
    },
    "sin_stock": {
        "phase": "stock",
        "label": "Stock · Avisar sin stock",
        "note": "Informa cuánto queda y no reserva nada.",
    },
    "preguntar_entrega": {
        "phase": "entrega",
        "label": "Entrega · Preguntar modalidad",
        "note": "Pregunta si el pedido es delivery o recojo.",
    },
    "esperar_entrega": {
        "phase": "entrega",
        "label": "Entrega · Esperar modalidad",
        "note": "Pausa durable hasta la respuesta de delivery o recojo.",
    },
    "guardar_entrega": {
        "phase": "entrega",
        "label": "Entrega · Guardar modalidad",
        "note": "Guarda el texto de delivery o recojo.",
    },
    "es_delivery": {
        "phase": "entrega",
        "label": "Entrega · ¿Es delivery?",
        "note": "Si es delivery pide dirección; si no, marca recojo.",
    },
    "preguntar_direccion": {
        "phase": "entrega",
        "label": "Entrega · Preguntar dirección",
        "note": "Pide la dirección de entrega.",
    },
    "esperar_direccion": {
        "phase": "entrega",
        "label": "Entrega · Esperar dirección",
        "note": "Pausa durable hasta que llega la dirección.",
    },
    "guardar_direccion": {
        "phase": "entrega",
        "label": "Entrega · Guardar dirección",
        "note": "Guarda modo delivery y dirección.",
    },
    "marcar_recojo": {
        "phase": "entrega",
        "label": "Entrega · Marcar recojo",
        "note": "Guarda modo recojo sin dirección.",
    },
    "preguntar_confirmacion": {
        "phase": "confirmacion",
        "label": "Confirmación · Pedir",
        "note": "Paso común para delivery y recojo.",
    },
    "esperar_confirmacion": {
        "phase": "confirmacion",
        "label": "Confirmación · Esperar",
        "note": "Pausa durable hasta que el cliente responde sí o no.",
    },
    "confirmado": {
        "phase": "confirmacion",
        "label": "Confirmación · ¿Confirmado?",
        "note": "Si dice no, cancela sin reservar stock.",
    },
    "cancelado": {
        "phase": "confirmacion",
        "label": "Confirmación · Avisar cancelado",
        "note": "Mensaje final cuando el cliente cancela.",
    },
    "crear_pedido": {
        "phase": "pedido",
        "label": "Pedido · Crear en Bodega",
        "note": "Crea el pedido con el precio y stock reales.",
    },
    "reservar": {
        "phase": "pedido",
        "label": "Pedido · Reservar stock",
        "note": "Reserva stock por el tiempo configurado.",
    },
    "aprobacion": {
        "phase": "pedido",
        "label": "Pedido · Aprobar pago simulado",
        "note": "Pausa para aprobación humana antes de confirmar.",
    },
    "commit": {
        "phase": "pedido",
        "label": "Pedido · Confirmar stock",
        "note": "Convierte la reserva en salida de stock.",
    },
    "entrega_final": {
        "phase": "cierre",
        "label": "Cierre · ¿Delivery o recojo?",
        "note": "Rama final según la modalidad elegida.",
    },
    "aviso_delivery": {
        "phase": "cierre",
        "label": "Cierre · Avisar reparto",
        "note": "Mensaje con dirección y total del pedido.",
    },
    "aviso_recojo": {
        "phase": "cierre",
        "label": "Cierre · Avisar recojo",
        "note": "Mensaje con total y punto de recojo.",
    },
    "resultado": {
        "phase": "cierre",
        "label": "Cierre · Registrar venta",
        "note": "Resultado de negocio común a ambas entregas.",
    },
    "fin": {
        "phase": "fin",
        "label": "Fin · Pedido completado",
        "note": "Termina el proceso exitoso.",
    },
    "fin_sin_producto": {
        "phase": "fin",
        "label": "Fin · Sin producto",
        "note": "Termina sin crear pedido.",
    },
    "fin_sin_stock": {
        "phase": "fin",
        "label": "Fin · Sin stock",
        "note": "Termina sin reservar stock.",
    },
    "fin_cancelado": {
        "phase": "fin",
        "label": "Fin · Cancelado",
        "note": "Termina sin crear pedido ni reservar stock.",
    },
}


def _node(
    nid: str,
    ntype: str,
    label: str,
    config: dict[str, Any] | None = None,
    ports: list[str] | None = None,
    *,
    error_policy: str = "fail",
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
        "error_policy": error_policy,
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


def _decorate_nodes(nodes: list[dict[str, Any]]) -> None:
    """Aplica copy de negocio y fase sin tocar ids, edges ni configuración."""
    for node in nodes:
        copy = NODE_COPY.get(str(node.get("id") or ""))
        if not copy:
            continue
        phase = copy["phase"]
        node["label"] = copy["label"]
        metadata = node.get("metadata")
        metadata = dict(metadata) if isinstance(metadata, dict) else {}
        metadata.update(
            {
                "phase": phase,
                "phase_label": PHASE_LABELS.get(phase, phase),
                "note": copy["note"],
            }
        )
        node["metadata"] = metadata


def _layout_phases(nodes: list[dict[str, Any]]) -> None:
    """Una columna por fase; los nodos de la fase se apilan en orden.

    El flujo deja de mezclar nodos de fases distintas en la misma columna.
    """
    phase_index = {phase: index for index, phase in enumerate(PHASES)}
    groups: dict[str, list[dict[str, Any]]] = {phase: [] for phase in PHASES}
    for node in nodes:
        metadata = node.get("metadata") if isinstance(node.get("metadata"), dict) else {}
        phase = str(metadata.get("phase") or "entrada")
        groups.setdefault(phase, []).append(node)
    x_gap = 360
    y_gap = 170
    for phase, items in groups.items():
        column = phase_index.get(phase, len(phase_index))
        for index, node in enumerate(items):
            node["position"] = {"x": 80 + column * x_gap, "y": 80 + index * y_gap}


def build_graph(parameters: dict[str, Any] | None = None) -> dict[str, Any]:
    """Grafo conversacional. Cada pregunta termina en un `wait_event`."""
    params = {**DEFAULT_PARAMETERS, **(parameters or {})}
    wait_seconds = int(params.get("wait_timeout_seconds") or 86400)
    wait_config = {
        "preset": "message",
        "event_type": "conversation.message",
        "timeout_seconds": wait_seconds,
        "on_timeout": "expire",
        # La correlación evita que un mensaje de otra conversación despierte
        # este wait. El cliente debe enviar el mismo order_number al responder.
        "correlation": {"order_number": "{{instance.state.order.order_number}}"},
    }

    nodes = [
        _node(
            "cliente",
            "trigger_event",
            "Mensaje del cliente",
            {"event_type": "conversation.message"},
        ),
        _node(
            "guardar_cliente",
            "state_merge",
            "Identificar cliente",
            {
                "path": "order",
                "value": {
                    "customer_ref": "{{trigger.customer_ref}}",
                    "order_number": "{{trigger.order_number}}",
                },
            },
        ),
        _node(
            "buscar",
            "capability_call",
            "Buscar producto",
            {
                "capability": "bodega.product.search",
                "inputs": {
                    "query": "{{trigger.text}}",
                    "limit": "{{variables.max_matches}}",
                },
            },
            error_policy="continue",
        ),
        _node(
            "encontrado",
            "condition",
            "¿Producto encontrado?",
            {
                "field": "{{nodes.buscar.output.row_count}}",
                "operator": ">",
                "value": 0,
            },
            ports=["out", "then", "else"],
        ),
        _node(
            "sin_producto",
            "notify",
            "No encontré el producto",
            {
                "channel": "in_app",
                "title": "Producto no encontrado",
                "message": (
                    "No tengo «{{trigger.text}}» en el catálogo. "
                    "Puedes pedirme otro producto, por ejemplo: arroz, leche o aceite."
                ),
            },
        ),
        _node(
            "guardar_opciones",
            "state_set",
            "Guardar opciones",
            {"path": "order.matches", "value": "{{nodes.buscar.output.rows}}"},
        ),
        _node(
            "unico",
            "condition",
            "¿Una sola opción?",
            {
                "field": "{{nodes.buscar.output.row_count}}",
                "operator": "==",
                "value": 1,
            },
            ports=["out", "then", "else"],
        ),
        _node(
            "elegir_uno",
            "state_merge",
            "Elegir producto",
            {
                "path": "order",
                "value": {
                    "sku": "{{instance.state.order.matches.0.sku}}",
                    "name": "{{instance.state.order.matches.0.name}}",
                    "unit": "{{instance.state.order.matches.0.unit}}",
                    "price": "{{instance.state.order.matches.0.price}}",
                    "currency": "{{instance.state.order.matches.0.currency}}",
                },
            },
        ),
        _node(
            "pedir_opcion",
            "notify",
            "Preguntar cuál",
            {
                "channel": "in_app",
                "title": "Elige el producto",
                "message": (
                    "Tengo estas opciones:\n"
                    "1) {{instance.state.order.matches.0.name}} — "
                    "S/ {{instance.state.order.matches.0.price}}\n"
                    "2) {{instance.state.order.matches.1.name}} — "
                    "S/ {{instance.state.order.matches.1.price}}\n"
                    "Responde 1 o 2."
                ),
            },
        ),
        _node(
            "esperar_opcion",
            "wait_event",
            "WAIT: elección",
            dict(wait_config),
            ports=["out", "timeout"],
        ),
        _node(
            "opcion_uno",
            "condition",
            "¿Opción 1?",
            {"field": "{{trigger.text}}", "operator": "contains", "value": "1"},
            ports=["out", "then", "else"],
        ),
        _node(
            "elegir_dos",
            "state_merge",
            "Elegir opción 2",
            {
                "path": "order",
                "value": {
                    "sku": "{{instance.state.order.matches.1.sku}}",
                    "name": "{{instance.state.order.matches.1.name}}",
                    "unit": "{{instance.state.order.matches.1.unit}}",
                    "price": "{{instance.state.order.matches.1.price}}",
                    "currency": "{{instance.state.order.matches.1.currency}}",
                },
            },
        ),
        _node(
            "opcion_dos",
            "condition",
            "¿Opción 2?",
            {"field": "{{trigger.text}}", "operator": "contains", "value": "2"},
            ports=["out", "then", "else"],
        ),
        _node(
            "opcion_invalida",
            "notify",
            "Opción no entendida",
            {
                "channel": "in_app",
                "title": "No te entendí",
                "message": "Responde 1 o 2 para elegir el producto.",
            },
        ),
        _node(
            "repetir_opcion",
            "loop",
            "Volver a preguntar",
            {"target": "pedir_opcion", "max_iterations": 3},
        ),
        _node(
            "preguntar_cantidad",
            "notify",
            "Preguntar cantidad",
            {
                "channel": "in_app",
                "title": "Cantidad",
                "message": (
                    "¿Cuántas unidades de {{instance.state.order.name}} quieres? "
                    "Responde solo el número (ej. 2)."
                ),
            },
        ),
        _node(
            "esperar_cantidad",
            "wait_event",
            "WAIT: cantidad",
            dict(wait_config),
            ports=["out", "timeout"],
        ),
        _node(
            "guardar_cantidad",
            "state_set",
            "Guardar cantidad",
            {"path": "order.quantity", "value": "{{trigger.text}}"},
        ),
        _node(
            "precio",
            "data_query",
            "Precio y stock",
            {
                "capability": "bodega.product.get",
                "params": {"sku": "{{instance.state.order.sku}}"},
            },
        ),
        _node(
            "stock_ok",
            "condition",
            "¿Hay stock?",
            {
                "field": "{{nodes.precio.output.record.available}}",
                "operator": ">=",
                "value": "{{instance.state.order.quantity}}",
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
                    "Solo quedan {{nodes.precio.output.record.available}} de "
                    "{{instance.state.order.name}}. No reservé nada."
                ),
            },
        ),
        _node(
            "preguntar_entrega",
            "notify",
            "Preguntar entrega",
            {
                "channel": "in_app",
                "title": "Delivery o recojo",
                "message": "¿Delivery o recojo? Responde delivery o recojo.",
            },
        ),
        _node(
            "esperar_entrega",
            "wait_event",
            "WAIT: entrega",
            dict(wait_config),
            ports=["out", "timeout"],
        ),
        _node(
            "guardar_entrega",
            "state_set",
            "Guardar modalidad",
            {"path": "order.delivery_text", "value": "{{trigger.text}}"},
        ),
        _node(
            "es_delivery",
            "condition",
            "¿Delivery?",
            {
                "field": "{{instance.state.order.delivery_text}}",
                "operator": "contains",
                "value": "delivery",
            },
            ports=["out", "then", "else"],
        ),
        _node(
            "preguntar_direccion",
            "notify",
            "Preguntar dirección",
            {
                "channel": "in_app",
                "title": "Dirección de entrega",
                "message": "¿A qué dirección enviamos el pedido?",
            },
        ),
        _node(
            "esperar_direccion",
            "wait_event",
            "WAIT: dirección",
            dict(wait_config),
            ports=["out", "timeout"],
        ),
        _node(
            "guardar_direccion",
            "state_merge",
            "Guardar dirección",
            {
                "path": "order",
                "value": {
                    "delivery_mode": "delivery",
                    "address": "{{trigger.text}}",
                },
            },
        ),
        _node(
            "marcar_recojo",
            "state_merge",
            "Marcar recojo",
            {
                "path": "order",
                "value": {"delivery_mode": "recojo", "address": ""},
            },
        ),
        _node(
            "preguntar_confirmacion",
            "notify",
            "Pedir confirmación",
            {
                "channel": "in_app",
                "title": "Confirmar pedido",
                "message": (
                    "Resumen: {{instance.state.order.quantity}} x "
                    "{{instance.state.order.name}} a S/ {{instance.state.order.price}} c/u. "
                    "Entrega: {{instance.state.order.delivery_mode}} "
                    "{{instance.state.order.address}}. ¿Confirmas? Responde sí o no."
                ),
            },
        ),
        _node(
            "esperar_confirmacion",
            "wait_event",
            "WAIT: confirmación",
            dict(wait_config),
            ports=["out", "timeout"],
        ),
        _node(
            "confirmado",
            "condition",
            "¿Confirmado?",
            {
                "field": "{{trigger.text}}",
                "operator": "not_contains",
                "value": "no",
            },
            ports=["out", "then", "else"],
        ),
        _node(
            "cancelado",
            "notify",
            "Pedido cancelado",
            {
                "channel": "in_app",
                "title": "Pedido cancelado",
                "message": "Pedido cancelado. No reservé stock ni creé la venta.",
            },
        ),
        _node(
            "crear_pedido",
            "capability_call",
            "Crear pedido Bodega",
            {
                "capability": "bodega.order.create",
                "inputs": {
                    "order_number": "{{instance.state.order.order_number}}",
                    "customer_ref": "{{instance.state.order.customer_ref}}",
                    "currency": "{{variables.currency}}",
                    "items": [
                        {
                            "sku": "{{instance.state.order.sku}}",
                            "quantity": "{{instance.state.order.quantity}}",
                            "unit_price": "{{instance.state.order.price}}",
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
                            "sku": "{{instance.state.order.sku}}",
                            "quantity": "{{instance.state.order.quantity}}",
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
                    "{{nodes.crear_pedido.output.total}} "
                    "{{nodes.crear_pedido.output.currency}} · "
                    "{{instance.state.order.quantity}} x "
                    "{{instance.state.order.name}} · "
                    "{{instance.state.order.delivery_mode}}"
                ),
                "data": {
                    "order_number": "{{nodes.crear_pedido.output.order_number}}",
                    "customer_ref": "{{instance.state.order.customer_ref}}",
                    "sku": "{{instance.state.order.sku}}",
                    "quantity": "{{instance.state.order.quantity}}",
                    "total": "{{nodes.crear_pedido.output.total}}",
                    "currency": "{{nodes.crear_pedido.output.currency}}",
                    "delivery_mode": "{{instance.state.order.delivery_mode}}",
                    "address": "{{instance.state.order.address}}",
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
                "field": "{{instance.state.order.delivery_mode}}",
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
                    "Total S/ {{nodes.crear_pedido.output.total}}. "
                    "Sale a {{instance.state.order.address}}."
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
                    "Total S/ {{nodes.crear_pedido.output.total}}. "
                    "Puedes recogerlo en tienda."
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
                    "{{nodes.crear_pedido.output.total}} "
                    "{{nodes.crear_pedido.output.currency}} · "
                    "{{instance.state.order.customer_ref}} · "
                    "{{instance.state.order.delivery_mode}}"
                ),
            },
        ),
        _node("fin", "end", "Fin"),
        _node("fin_sin_producto", "end", "Fin sin producto"),
        _node("fin_sin_stock", "end", "Fin sin stock"),
        _node("fin_cancelado", "end", "Fin cancelado"),
    ]

    edges = [
        _edge("e1", "cliente", "guardar_cliente"),
        _edge("e2", "guardar_cliente", "buscar"),
        _edge("e3", "buscar", "encontrado"),
        _edge("e4", "encontrado", "guardar_opciones", from_port="then", label="sí"),
        _edge("e5", "encontrado", "sin_producto", from_port="else", label="no"),
        _edge("e6", "sin_producto", "fin_sin_producto"),
        _edge("e7", "guardar_opciones", "unico"),
        _edge("e8", "unico", "elegir_uno", from_port="then", label="una"),
        _edge("e9", "unico", "pedir_opcion", from_port="else", label="varias"),
        _edge("e10", "elegir_uno", "preguntar_cantidad"),
        _edge("e11", "pedir_opcion", "esperar_opcion"),
        _edge("e12", "esperar_opcion", "opcion_uno"),
        _edge("e13", "opcion_uno", "elegir_uno", from_port="then", label="1"),
        _edge("e14", "opcion_uno", "opcion_dos", from_port="else"),
        _edge("e15", "opcion_dos", "elegir_dos", from_port="then", label="2"),
        _edge("e16", "opcion_dos", "opcion_invalida", from_port="else", label="no"),
        _edge("e17", "elegir_dos", "preguntar_cantidad"),
        _edge("e18", "opcion_invalida", "repetir_opcion"),
        _edge("e19", "repetir_opcion", "pedir_opcion"),
        _edge("e20", "preguntar_cantidad", "esperar_cantidad"),
        _edge("e21", "esperar_cantidad", "guardar_cantidad"),
        _edge("e22", "guardar_cantidad", "precio"),
        _edge("e23", "precio", "stock_ok"),
        _edge("e24", "stock_ok", "preguntar_entrega", from_port="then", label="sí"),
        _edge("e25", "stock_ok", "sin_stock", from_port="else", label="no"),
        _edge("e26", "sin_stock", "fin_sin_stock"),
        _edge("e27", "preguntar_entrega", "esperar_entrega"),
        _edge("e28", "esperar_entrega", "guardar_entrega"),
        _edge("e29", "guardar_entrega", "es_delivery"),
        _edge("e30", "es_delivery", "preguntar_direccion", from_port="then", label="delivery"),
        _edge("e31", "es_delivery", "marcar_recojo", from_port="else", label="recojo"),
        _edge("e32", "preguntar_direccion", "esperar_direccion"),
        _edge("e33", "esperar_direccion", "guardar_direccion"),
        _edge("e34", "guardar_direccion", "preguntar_confirmacion"),
        _edge("e35", "marcar_recojo", "preguntar_confirmacion"),
        _edge("e36", "preguntar_confirmacion", "esperar_confirmacion"),
        _edge("e37", "esperar_confirmacion", "confirmado"),
        _edge("e38", "confirmado", "crear_pedido", from_port="then", label="sí"),
        _edge("e39", "confirmado", "cancelado", from_port="else", label="no"),
        _edge("e40", "cancelado", "fin_cancelado"),
        _edge("e41", "crear_pedido", "reservar"),
        _edge("e42", "reservar", "aprobacion"),
        _edge("e43", "aprobacion", "commit"),
        _edge("e44", "commit", "entrega_final"),
        _edge("e45", "entrega_final", "aviso_delivery", from_port="then", label="delivery"),
        _edge("e46", "entrega_final", "aviso_recojo", from_port="else", label="recojo"),
        _edge("e47", "aviso_delivery", "resultado"),
        _edge("e48", "aviso_recojo", "resultado"),
        _edge("e49", "resultado", "fin"),
    ]

    _decorate_nodes(nodes)
    _layout_phases(nodes)

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
            "phases": [{"id": phase, "label": PHASE_LABELS[phase]} for phase in PHASES],
            "conversation": {
                "trigger": "conversation.message",
                "waits": [
                    "esperar_opcion",
                    "esperar_cantidad",
                    "esperar_entrega",
                    "esperar_direccion",
                    "esperar_confirmacion",
                ],
            },
        },
    }


def template_row() -> dict[str, Any]:
    return {
        "slug": TEMPLATE_SLUG,
        "name": TEMPLATE_NAME,
        "description": TEMPLATE_DESCRIPTION,
        "category": TEMPLATE_CATEGORY,
        "trigger_type": "event",
        "trigger_config": {"event_type": "conversation.message"},
        "steps": [],
        "graph": build_graph(),
        "package": {
            "schema": "zent.workflow.package/v1",
            "package_version": PACKAGE_VERSION,
            "metadata": {
                "name": TEMPLATE_NAME,
                "description": TEMPLATE_DESCRIPTION,
                "category": TEMPLATE_CATEGORY,
                "applies_to": ["WORKFLOWS", "AGENTS"],
            },
            "dependencies": [
                {"kind": "capability", "ref": ref, "requirement": "required"}
                for ref in CAPABILITIES
            ]
            + [{"kind": "event", "ref": "conversation.message", "requirement": "required"}],
            "capabilities": [
                {"kind": "capability", "ref": ref, "requirement": "required"}
                for ref in CAPABILITIES
            ],
            "events": [{"ref": "conversation.message", "requirement": "required"}],
            "permissions": ["workflows:run", "workflow_approvals:approve"],
            "tests": [
                "cliente: tienes arroz? -> 1 -> 2 -> delivery -> dirección -> sí",
                "cliente: arroz -> 2 -> recojo -> sí",
                "cliente: producto inexistente -> fallback sin pedido",
                "cliente: no -> pedido cancelado sin reserva",
            ],
            "security": {"contains_secrets": False, "tenant_scoped": True},
        },
    }


def demo_payload(
    *,
    text: str = "tienes arroz?",
    customer_ref: str = "CUST-CONV",
    order_number: str | None = None,
) -> dict[str, Any]:
    return {
        "text": text,
        "customer_ref": customer_ref,
        "order_number": order_number or f"CONV-{uuid4().hex[:8].upper()}",
    }


def demo_conversation() -> list[str]:
    """Guion de la conversación que ejecuta el demo."""
    return [
        "tienes arroz?",
        "1",
        "2",
        "delivery",
        "Av. Demo 123",
        "si",
    ]
