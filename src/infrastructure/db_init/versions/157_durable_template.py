"""Template durable de ejemplo: pedido conversacional con WAIT real.

Revision ID: 157
Revises: 156

Aditiva. Un solo sistema de plantillas: `graph` (IR v2) + `package` declaran
el flujo durable; `steps` queda vacío (compatibilidad legacy intacta).
"""
from __future__ import annotations

import json

from alembic import op
from sqlalchemy import text

revision: str = "157"
down_revision: str = "156"
branch_labels = None
depends_on = None


def _node(
    nid: str,
    ntype: str,
    label: str,
    config: dict,
    ports: list[str] | None = None,
    *,
    error_policy: str = "fail",
) -> dict:
    out_ports = ports or ["out"]
    return {
        "id": nid,
        "type": ntype,
        "label": label,
        "config": config,
        "input_ports": [{"name": "in", "type": "json"}],
        "output_ports": [{"name": name, "type": "json"} for name in out_ports],
        "retry_policy": {"max_attempts": 1},
        "timeout_ms": 60000,
        "error_policy": error_policy,
    }


def _edge(eid: str, frm: str, to: str, *, from_port: str = "out") -> dict:
    return {"id": eid, "from_node": frm, "from_port": from_port, "to_node": to, "to_port": "in"}


def _graph() -> dict:
    return {
        "workflow_version": 2,
        "nodes": [
            _node("t1", "trigger_event", "Mensaje del cliente", {"event_type": "conversation.message"}),
            _node(
                "buscar",
                "capability_call",
                "Buscar producto",
                {"capability": "catalog.products.search", "inputs": {"query": "{{trigger.text}}"}},
                error_policy="continue",
            ),
            _node(
                "carrito",
                "state_append",
                "Agregar al carrito",
                {"path": "cart.items", "value": "{{nodes.buscar.output.rows}}"},
                error_policy="continue",
            ),
            _node(
                "responder",
                "notify",
                "Responder al cliente",
                {
                    "channel": "in_app",
                    "title": "Pedido en proceso",
                    "message": "Busqué el producto y lo agregué a tu carrito. ¿Algo más?",
                },
            ),
            _node(
                "esperar",
                "wait_event",
                "Esperar respuesta del cliente",
                {"preset": "message", "timeout_seconds": 86400, "on_timeout": "expire"},
                ports=["out", "timeout"],
            ),
            _node(
                "confirmar",
                "state_set",
                "Confirmar pedido",
                {"path": "order.confirmed", "value": True},
            ),
            _node("fin", "end", "Fin", {}),
        ],
        "edges": [
            _edge("e1", "t1", "buscar"),
            _edge("e2", "buscar", "carrito"),
            _edge("e3", "carrito", "responder"),
            _edge("e4", "responder", "esperar"),
            _edge("e5", "esperar", "confirmar"),
            _edge("e6", "confirmar", "fin"),
        ],
        "variables": {},
        "entrypoints": ["t1"],
        "metadata": {"durable_example": True},
    }


def upgrade() -> None:
    package = {
        "schema": "zent.workflow.package/v1",
        "package_version": "1.0.0",
        "metadata": {
            "name": "Pedido conversacional",
            "description": (
                "Toma un pedido por conversación: busca el producto, actualiza el "
                "carrito durable, responde y espera el siguiente mensaje del cliente."
            ),
        },
        "dependencies": [
            {"kind": "capability", "ref": "catalog.products.search", "requirement": "required"},
        ],
        "capabilities": [
            {"ref": "catalog.products.search", "requirement": "required"},
        ],
        "events": [{"ref": "conversation.message", "requirement": "required"}],
    }
    op.execute(
        text(
            """
            INSERT INTO workflow_templates
                (slug, name, description, category, trigger_type, steps, trigger_config, package, graph)
            VALUES (
                'pedido_conversacional',
                'Pedido conversacional',
                'Proceso durable: busca el producto, actualiza el carrito y espera el siguiente mensaje del cliente.',
                'ventas',
                'event',
                '[]'::jsonb,
                '{"event_type": "conversation.message"}'::jsonb,
                CAST(:package AS jsonb),
                CAST(:graph AS jsonb)
            )
            ON CONFLICT (slug) DO UPDATE SET
                name = EXCLUDED.name,
                description = EXCLUDED.description,
                category = EXCLUDED.category,
                trigger_type = EXCLUDED.trigger_type,
                trigger_config = EXCLUDED.trigger_config,
                package = EXCLUDED.package,
                graph = EXCLUDED.graph
            """
        ).bindparams(
            package=json.dumps(package, ensure_ascii=False),
            graph=json.dumps(_graph(), ensure_ascii=False),
        )
    )


def downgrade() -> None:
    op.execute("DELETE FROM workflow_templates WHERE slug = 'pedido_conversacional'")
