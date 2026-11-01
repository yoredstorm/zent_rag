"""Crea y ejecuta el workflow de precio P19 contra la DB externa demo."""
from __future__ import annotations

import json
import os
from uuid import uuid4

import httpx

BASE = os.environ.get("P19_PORTAL_API", "http://127.0.0.1:8000")
EMAIL = os.environ.get("P19_DEMO_EMAIL", "p19.demo@example.com")
PASSWORD = os.environ.get("P19_DEMO_PASSWORD", "P19Demo!2026")
WORKSPACE = os.environ.get(
    "P19_DEMO_WORKSPACE", "d28ec9d6-020f-4537-a715-dc4ff34e888d"
)


def main() -> None:
    with httpx.Client(base_url=BASE, timeout=60) as client:
        login = client.post(
            "/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD}
        )
        login.raise_for_status()
        session = login.json()
        headers = {
            "Authorization": f"Bearer {session['access_token']}",
            "X-Organization-Id": session["organization_id"],
            "X-Workspace-Id": WORKSPACE,
        }
        plans = client.get("/api/v1/workflows/data-query/plans", headers=headers)
        plans.raise_for_status()
        price = next(
            plan
            for plan in plans.json()["plans"]
            if plan["capability_ref"] == "p19.external.price"
        )
        graph = {
            "workflow_version": 2,
            "nodes": [
                {
                    "id": "t",
                    "type": "trigger_webhook",
                    "label": "Mensaje",
                    "config": {},
                    "input_ports": [],
                    "output_ports": [{"name": "out", "type": "json"}],
                },
                {
                    "id": "intent",
                    "type": "intent_route",
                    "label": "Identificar solicitud",
                    "config": {
                        "text": "{{trigger.message}}",
                        "confidence_min": 0.7,
                    },
                },
                {
                    "id": "price",
                    "type": "data_query",
                    "label": "Precio externo",
                    "config": {
                        "capability": "p19.external.price",
                        "binding_ref": price["binding_ref"],
                        "params": {"sku": "{{nodes.intent.output.entities.sku}}"},
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
                {"id": "e1", "from_node": "t", "from_port": "out", "to_node": "intent", "to_port": "in"},
                {"id": "e2", "from_node": "intent", "from_port": "out", "to_node": "price", "to_port": "in"},
                {"id": "e3", "from_node": "price", "from_port": "out", "to_node": "end", "to_port": "in"},
            ],
            "variables": {},
            "entrypoints": ["t"],
            "metadata": {},
        }
        created = client.post(
            "/api/v1/workflows",
            headers={**headers, "Idempotency-Key": f"p19-{uuid4().hex}"},
            json={
                "name": f"P19 Precio externo {uuid4().hex[:6]}",
                "description": "Precio real desde PostgreSQL externo",
                "trigger_type": "webhook",
                "trigger_config": {},
                "graph": graph,
            },
        )
        created.raise_for_status()
        workflow = created.json()
        print(json.dumps(workflow, ensure_ascii=False)[:1000])  # noqa: T201
        wf_id = workflow.get("id") or workflow.get("workflow_id") or (workflow.get("workflow") or {}).get("id")
        if not wf_id:
            raise SystemExit("workflow id missing")
        print("workflow_id=", wf_id)  # noqa: T201
        run = client.post(
            f"/api/v1/workflows/{wf_id}/run",
            headers={**headers, "Idempotency-Key": f"p19-run-{uuid4().hex}"},
            json={"payload": {"message": "precio del SKU ARR-001"}},
        )
        print("run_status=", run.status_code, run.text[:2000])  # noqa: T201
        run.raise_for_status()
        body = run.json()
        print(json.dumps(body, indent=2, ensure_ascii=False)[:4000])  # noqa: T201


if __name__ == "__main__":
    main()
