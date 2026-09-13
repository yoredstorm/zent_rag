# =============================================================================
# Readiness + Summary (commit 7) — checklist de negocio y resumen legible.
# =============================================================================
from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.test_workflow_graph import _edge, _graph, _node
from tests.test_workflows import _create_org, _headers, _owner_session


async def _org(client: AsyncClient, name: str) -> dict:
    org = await _create_org(client, name)
    org["session"] = await _owner_session(client, org["organization_id"])
    return org


def _notify_graph(recipients: list[dict] | None = None) -> dict:
    condition = _node(
        "cond",
        "condition",
        {"rules": {"kind": "condition", "field": "{{nodes.missing.output.stock}}", "operator": "<", "value": 10}},
        label="Stock bajo",
        output_ports=[
            {"name": "out", "type": "boolean"},
            {"name": "then", "type": "json"},
            {"name": "else", "type": "json"},
        ],
    )
    notify = _node(
        "notify",
        "notify",
        {"channel": "email", "title": "Stock bajo", "message": "m", "recipients": recipients or []},
        label="Avisar a compras",
    )
    llm = _node("ask", "llm", {"prompt": "Recomienda", "agent_id": "", "agent_name": ""}, label="Analizar")
    return _graph(
        nodes=[_node("t", "trigger_event", {"event_type": "inventory.updated"}), condition, llm, notify, _node("end", "end")],
        edges=[
            _edge("e1", "t", "cond"),
            _edge("e2", "cond", "ask", from_port="then"),
            _edge("e3", "cond", "end", from_port="else"),
            _edge("e4", "ask", "notify"),
            _edge("e5", "notify", "end"),
        ],
        entrypoints=["t"],
    )


@pytest.mark.asyncio
async def test_readiness_reports_business_checks(async_client: AsyncClient) -> None:
    org = await _org(async_client, "Readiness WF")
    h = _headers(org)
    created = await async_client.post(
        "/api/v1/workflows",
        headers=h,
        json={"name": "Stock", "trigger_type": "event", "graph": _notify_graph(), "workflow_version": 2},
    )
    assert created.status_code == 200, created.text
    wid = created.json()["workflow_id"]

    resp = await async_client.get(f"/api/v1/workflows/{wid}/readiness", headers=h)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    statuses = {c["key"]: c for c in body["checks"]}
    assert statuses["trigger"]["status"] == "ok"
    assert statuses["conditions"]["status"] == "error"
    assert "missing" in statuses["conditions"]["message"]
    assert statuses["agents"]["status"] == "warning"
    assert "agente" in statuses["agents"]["message"].lower()
    assert statuses["outputs"]["status"] == "warning"
    assert "avisar" in statuses["outputs"]["message"].lower()
    assert body["ready"] is False
    assert body["errors"] >= 1


@pytest.mark.asyncio
async def test_readiness_ok_for_complete_flow(async_client: AsyncClient) -> None:
    org = await _org(async_client, "Readiness OK")
    h = _headers(org)
    graph = _graph(
        nodes=[
            _node("t", "trigger_webhook"),
            _node("notify", "notify", {"channel": "in_app", "title": "Aviso", "message": "m"}, label="Avisar"),
            _node("end", "end"),
        ],
        edges=[_edge("e1", "t", "notify"), _edge("e2", "notify", "end")],
        entrypoints=["t"],
    )
    created = await async_client.post(
        "/api/v1/workflows",
        headers=h,
        json={"name": "Completo", "trigger_type": "webhook", "graph": graph, "workflow_version": 2},
    )
    wid = created.json()["workflow_id"]
    body = (
        await async_client.get(f"/api/v1/workflows/{wid}/readiness", headers=h)
    ).json()
    assert body["ready"] is True
    assert body["errors"] == 0


@pytest.mark.asyncio
async def test_summary_describes_workflow_in_business_language(async_client: AsyncClient) -> None:
    org = await _org(async_client, "Summary WF")
    h = _headers(org)
    created = await async_client.post(
        "/api/v1/workflows",
        headers=h,
        json={"name": "Stock", "trigger_type": "event", "graph": _notify_graph(), "workflow_version": 2},
    )
    wid = created.json()["workflow_id"]
    resp = await async_client.get(f"/api/v1/workflows/{wid}/summary", headers=h)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "inventory.updated" in body["text"]
    assert "correo" in body["text"]
    assert any(step.startswith("si ") for step in body["steps"])


@pytest.mark.asyncio
async def test_summary_and_readiness_work_for_legacy_steps(async_client: AsyncClient) -> None:
    org = await _org(async_client, "Legacy Summary")
    h = _headers(org)
    created = await async_client.post(
        "/api/v1/workflows",
        headers=h,
        json={
            "name": "Legacy",
            "trigger_type": "webhook",
            "steps": [{"type": "notify", "config": {"channel": "in_app", "title": "Hola", "message": "m"}}],
        },
    )
    assert created.status_code == 200, created.text
    wid = created.json()["workflow_id"]
    summary = (await async_client.get(f"/api/v1/workflows/{wid}/summary", headers=h)).json()
    assert "Zent" in summary["text"]
    readiness = (await async_client.get(f"/api/v1/workflows/{wid}/readiness", headers=h)).json()
    assert any(c["key"] == "trigger" for c in readiness["checks"])
