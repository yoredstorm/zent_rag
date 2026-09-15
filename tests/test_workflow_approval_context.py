# =============================================================================
# Cognitive Workflows — Fase 6: aprobación con evidencia.
#
# El nodo human_approval guarda un snapshot acotado (decisión, evidencia,
# citas, artefactos, datos) y el revisor lo recibe vía /runs/{id}/approvals.
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.test_workflows import _create_org, _headers, _owner_session


def _node(nid: str, ntype: str, config: dict | None = None, **extra) -> dict:
    node: dict = {
        "id": nid,
        "type": ntype,
        "label": ntype,
        "config": config or {},
        "input_ports": [{"name": "in", "type": "json"}],
        "output_ports": [{"name": "out", "type": "json"}],
        "retry_policy": {"max_attempts": 1},
        "timeout_ms": 60_000,
        "error_policy": "fail",
    }
    node.update(extra)
    return node


def _edge(eid: str, frm: str, to: str, **extra) -> dict:
    edge: dict = {"id": eid, "from_node": frm, "from_port": "out", "to_node": to, "to_port": "in"}
    edge.update(extra)
    return edge


def _graph(nodes: list[dict], edges: list[dict], entrypoints: list[str]) -> dict:
    return {
        "workflow_version": 2,
        "nodes": nodes,
        "edges": edges,
        "variables": {},
        "entrypoints": entrypoints,
        "metadata": {},
    }


@pytest.mark.asyncio
async def test_approval_snapshot_and_decide(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "CW Approval")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    headers = _headers(org)

    graph = _graph(
        [
            _node("t", "trigger_webhook"),
            _node(
                "br",
                "business_result",
                {"title": "Resumen de riesgo", "section": "reports", "importance": "WARNING"},
            ),
            _node(
                "ha",
                "human_approval",
                {"action": "Aprobar pago al proveedor", "summary": "Riesgo alto"},
            ),
        ],
        [_edge("e1", "t", "br"), _edge("e2", "br", "ha")],
        ["t"],
    )
    created = await async_client.post(
        "/api/v1/workflows",
        headers={**headers, "Idempotency-Key": f"ap-{uuid4().hex}"},
        json={"name": "CW Approval", "trigger_type": "webhook", "graph": graph},
    )
    assert created.status_code == 200, created.text
    wid = created.json()["workflow_id"]

    run = await async_client.post(
        f"/api/v1/workflows/{wid}/run",
        headers={**headers, "Idempotency-Key": f"apr-{uuid4().hex}"},
        json={"payload": {"message": "pago"}},
    )
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["status"] == "pending_approval", body
    run_id = body["run_id"]

    approvals = await async_client.get(
        f"/api/v1/workflows/runs/{run_id}/approvals", headers=headers
    )
    assert approvals.status_code == 200, approvals.text
    items = approvals.json()["approvals"]
    assert items, approvals.text
    approval = items[0]
    assert approval["action"] == "Aprobar pago al proveedor"
    context = approval["context"]
    assert "security" not in context
    assert context["artifacts"], context
    assert context["artifacts"][0]["title"] == "Resumen de riesgo"

    decided = await async_client.post(
        f"/api/v1/workflows/runs/{run_id}/approvals/{approval['id']}/decide",
        headers={**headers, "Idempotency-Key": f"apd-{uuid4().hex}"},
        json={"decision": "approved", "comment": "ok"},
    )
    assert decided.status_code == 200, decided.text

    after = await async_client.get(
        f"/api/v1/workflows/runs/{run_id}/approvals", headers=headers
    )
    statuses = {item["id"]: item["status"] for item in after.json()["approvals"]}
    assert statuses[approval["id"]] == "approved"
