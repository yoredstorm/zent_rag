"""Crea y ejecuta el flujo bodega: pedido → aprobación → commit de stock."""

from __future__ import annotations

import json
import os
from uuid import uuid4

import httpx

BASE = os.environ.get("P19_PORTAL_API", "http://127.0.0.1:8000")
EMAIL = os.environ.get("P19_DEMO_EMAIL", "p19.demo@example.com")
PASSWORD = os.environ.get("P19_DEMO_PASSWORD", "P19Demo!2026")
WORKSPACE = os.environ.get("P19_DEMO_WORKSPACE", "d28ec9d6-020f-4537-a715-dc4ff34e888d")
ORDER = os.environ.get("P19_ORDER", "BOD-1001")
SKU = os.environ.get("P19_SKU", "BD-ARROZ-01")
QUANTITY = int(os.environ.get("P19_QUANTITY", "2"))


def main() -> None:
    with httpx.Client(base_url=BASE, timeout=60) as client:
        login = client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
        login.raise_for_status()
        session = login.json()
        headers = {
            "Authorization": f"Bearer {session['access_token']}",
            "X-Organization-Id": session["organization_id"],
            "X-Workspace-Id": WORKSPACE,
        }
        graph = {
            "workflow_version": 2,
            "nodes": [
                {
                    "id": "t",
                    "type": "trigger_webhook",
                    "label": "Pedido recibido",
                    "config": {},
                    "input_ports": [],
                    "output_ports": [{"name": "out", "type": "json"}],
                },
                {
                    "id": "hold",
                    "type": "state_set",
                    "label": "Guardar pedido",
                    "config": {
                        "path": "order",
                        "value": {
                            "order_number": "{{trigger.order_number}}",
                            "sku": "{{trigger.sku}}",
                            "quantity": "{{trigger.quantity}}",
                        },
                    },
                },
                {
                    "id": "approval",
                    "type": "human_approval",
                    "label": "Aprobar pedido",
                    "config": {
                        "action": f"Aprobar pedido {ORDER}",
                        "summary": (
                            "Pedido {{trigger.order_number}} · SKU {{trigger.sku}} · cantidad {{trigger.quantity}}"
                        ),
                        "data": {
                            "order_number": "{{trigger.order_number}}",
                            "sku": "{{trigger.sku}}",
                            "quantity": "{{trigger.quantity}}",
                        },
                        "expires_minutes": 60,
                    },
                },
                {
                    "id": "commit",
                    "type": "capability_call",
                    "label": "Descontar stock",
                    "config": {
                        "capability": "bodega.stock.commit",
                        "inputs": {
                            "order_number": "{{nodes.approval.output.data.order_number}}",
                            "sku": "{{nodes.approval.output.data.sku}}",
                            "quantity": "{{nodes.approval.output.data.quantity}}",
                            "idempotency_key": "{{nodes.approval.output.data.order_number}}-{{nodes.approval.output.data.sku}}",  # noqa: E501
                        },
                    },
                },
                {
                    "id": "notify",
                    "type": "notify",
                    "label": "Avisar al cliente",
                    "config": {
                        "channel": "in_app",
                        "title": "Pedido confirmado",
                        "message": "Pedido {{trigger.order_number}} confirmado y stock descontado.",
                    },
                },
                {
                    "id": "end",
                    "type": "end",
                    "label": "Fin",
                    "config": {},
                },
            ],
            "edges": [
                {"id": "e1", "from_node": "t", "from_port": "out", "to_node": "hold", "to_port": "in"},
                {"id": "e2", "from_node": "hold", "from_port": "out", "to_node": "approval", "to_port": "in"},
                {"id": "e3", "from_node": "approval", "from_port": "out", "to_node": "commit", "to_port": "in"},
                {"id": "e4", "from_node": "commit", "from_port": "out", "to_node": "notify", "to_port": "in"},
                {"id": "e5", "from_node": "notify", "from_port": "out", "to_node": "end", "to_port": "in"},
            ],
            "variables": {},
            "entrypoints": ["t"],
            "metadata": {},
        }
        created = client.post(
            "/api/v1/workflows",
            headers={**headers, "Idempotency-Key": f"bodega-{uuid4().hex}"},
            json={
                "name": f"Bodega pedido {uuid4().hex[:6]}",
                "description": "Aprobación del dueño y descuento de stock",
                "trigger_type": "webhook",
                "trigger_config": {},
                "graph": graph,
            },
        )
        created.raise_for_status()
        workflow = created.json()
        wf_id = workflow.get("workflow_id") or workflow.get("id")
        print("workflow_id=", wf_id)  # noqa: T201
        run = client.post(
            f"/api/v1/workflows/{wf_id}/run",
            headers={**headers, "Idempotency-Key": f"bodega-run-{uuid4().hex}"},
            json={
                "payload": {
                    "order_number": ORDER,
                    "sku": SKU,
                    "quantity": QUANTITY,
                }
            },
        )
        run.raise_for_status()
        body = run.json()
        print(json.dumps(body, indent=2, ensure_ascii=False)[:2500])  # noqa: T201
        run_id = (
            body.get("run_id")
            or (body.get("result") or {}).get("run_id")
            or ((body.get("context") or {}).get("identity") or {}).get("run_id")
        )
        if not run_id:
            raise SystemExit("run id missing")
        approvals = client.get(f"/api/v1/workflows/runs/{run_id}/approvals", headers=headers)
        approvals.raise_for_status()
        approval_list = approvals.json().get("approvals") or []
        print("approvals=", json.dumps(approval_list, ensure_ascii=False)[:1500])  # noqa: T201
        pending = next((item for item in approval_list if item.get("status") == "pending"), None)
        if pending is None:
            raise SystemExit("no pending approval")
        decided = client.post(
            f"/api/v1/workflows/runs/{run_id}/approvals/{pending['id']}/decide",
            headers={**headers, "Idempotency-Key": f"approve-{uuid4().hex}"},
            json={"decision": "approved", "comment": "Aprobado por dueño demo"},
        )
        decided.raise_for_status()
        print("decision=", json.dumps(decided.json(), ensure_ascii=False))  # noqa: T201


if __name__ == "__main__":
    main()
