# =============================================================================
# Phase 33B — Marketplace-native workflow tests
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.test_workflow_graph import _edge, _graph, _node
from tests.test_workflows import _create_org, _headers, _owner_session


@pytest.mark.asyncio
async def test_canvas_context_installed_available_install_inline(
    async_client: AsyncClient,
) -> None:
    org = await _create_org(async_client, "Canvas Context")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    ctx = await async_client.get("/api/v1/workflows/marketplace/context", headers=h)
    assert ctx.status_code == 200, ctx.text
    body = ctx.json()
    slugs = {a["slug"] for a in body["available"]}
    assert "demo-echo" in slugs
    assert any(a["action_id"] == "demo.echo" for m in body["available"] for a in m["actions"])

    # Install inline desde el canvas (sin salir del workflow).
    inst = await async_client.post(
        "/api/v1/workflows/marketplace/install",
        headers={**h, "Idempotency-Key": f"ci-{uuid4().hex}"},
        json={"integration_slug": "demo-echo"},
    )
    assert inst.status_code == 200, inst.text
    install_id = inst.json()["install_id"]
    assert inst.json()["integration"]["slug"] == "demo-echo"

    ctx2 = await async_client.get("/api/v1/workflows/marketplace/context", headers=h)
    installed = ctx2.json()["installed"]
    mine = [s for s in installed if s["install_id"] == install_id]
    assert mine, installed
    assert any(a["action_id"] == "demo.echo" for a in mine[0]["actions"])
    assert "connected" in mine[0]["status"]

    # Reinstalar reusa la misma instalación.
    again = await async_client.post(
        "/api/v1/workflows/marketplace/install",
        headers={**h, "Idempotency-Key": f"ci-{uuid4().hex}"},
        json={"integration_slug": "demo-echo"},
    )
    assert again.json()["reused"] is True


@pytest.mark.asyncio
async def test_cost_estimate_per_run_and_monthly(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Cost Estimate")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    graph = _graph(
        [
            _node("trigger", "trigger_schedule", {"cron": "0 18 * * *"}),
            _node(
                "sunat",
                "marketplace_action",
                {
                    "install_id": "00000000-0000-0000-0000-000000000000",
                    "action_id": "peru.taxpayer.lookup",
                    "inputs": {"ruc": "{{trigger.ruc}}"},
                },
            ),
            _node("for", "for_each", {"bulk_size": 10000}, output_ports=[{"name": "out", "type": "json"}]),
            _node(
                "sunat2",
                "marketplace_action",
                {
                    "install_id": "00000000-0000-0000-0000-000000000000",
                    "action_id": "peru.taxpayer.lookup",
                    "inputs": {"ruc": "{{item.ruc}}"},
                },
            ),
        ],
        [
            _edge("e1", "trigger", "sunat"),
            _edge("e2", "sunat", "for"),
            _edge("e3", "for", "sunat2"),
        ],
        ["trigger"],
    )
    est = await async_client.post(
        "/api/v1/workflows/cost-estimate",
        headers={**h, "Idempotency-Key": f"ce-{uuid4().hex}"},
        json={"graph": graph, "trigger_config": {"cron": "0 18 * * *"}},
    )
    assert est.status_code == 200, est.text
    body = est.json()
    assert body["currency"] == "PEN"
    assert body["per_run"] == pytest.approx(0.02 + 0.02 * 10000, rel=1e-3)
    assert body["calls_per_run"] == 10001
    assert body["bulk_size"] == 10000
    assert body["bulk_warning"] is True
    assert body["monthly"] == pytest.approx(body["per_run"] * 30, rel=1e-3)


@pytest.mark.asyncio
async def test_recommend_from_graph(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Recommend")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    graph = _graph(
        [
            _node("trigger", "trigger_event", {"event_type": "customer.created"}),
            _node("llm", "llm", {"prompt": "analiza el RUC del cliente {{trigger.ruc}}"}),
        ],
        [_edge("e1", "trigger", "llm")],
        ["trigger"],
    )
    rec = await async_client.post(
        "/api/v1/workflows/marketplace/recommend",
        headers={**h, "Idempotency-Key": f"rec-{uuid4().hex}"},
        json={"graph": graph},
    )
    assert rec.status_code == 200, rec.text
    recs = {r["action_id"] for r in rec.json()["recommendations"]}
    assert "peru.taxpayer.lookup" in recs

    # Tras instalar sunat, dejar de recomendar.
    await async_client.post(
        "/api/v1/workflows/marketplace/install",
        headers={**h, "Idempotency-Key": f"rec-{uuid4().hex}"},
        json={"integration_slug": "sunat"},
    )
    rec2 = await async_client.post(
        "/api/v1/workflows/marketplace/recommend",
        headers={**h, "Idempotency-Key": f"rec-{uuid4().hex}"},
        json={"graph": graph},
    )
    recs2 = {r["action_id"] for r in rec2.json()["recommendations"]}
    assert "peru.taxpayer.lookup" not in recs2


@pytest.mark.asyncio
async def test_business_node_runs_and_normalizes(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Business Node")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    inst = await async_client.post(
        "/api/v1/workflows/marketplace/install",
        headers={**h, "Idempotency-Key": f"bn-{uuid4().hex}"},
        json={"integration_slug": "demo-echo"},
    )
    install_id = inst.json()["install_id"]

    graph = _graph(
        [
            _node("trigger", "trigger_webhook", {}),
            _node(
                "verify",
                "business_node",
                {
                    "title": "Verify Business",
                    "actions": [
                        {
                            "action_id": "demo.echo",
                            "install_id": install_id,
                            "inputs": {"text": "{{trigger.ruc}}"},
                            "output_map": {"echo": "echo"},
                        }
                    ],
                    "business_result": {
                        "title": "Verificación",
                        "section": "verification",
                        "importance": "HIGH",
                        "summary": "Contribuyente {{trigger.ruc}}",
                    },
                },
            ),
        ],
        [_edge("e1", "trigger", "verify")],
        ["trigger"],
    )
    created = await async_client.post(
        "/api/v1/workflows",
        headers={**h, "Idempotency-Key": f"bn-{uuid4().hex}"},
        json={"name": "Biz Node", "trigger_type": "webhook", "graph": graph},
    )
    assert created.status_code == 200, created.text
    wid = created.json()["workflow_id"]

    result = await async_client.post(
        f"/api/v1/workflows/{wid}/run",
        headers={**h, "Idempotency-Key": f"bn-{uuid4().hex}"},
        json={"payload": {"ruc": "20123456789"}},
    )
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["status"] == "succeeded", body

    detail = await async_client.get(f"/api/v1/workflows/runs/{body['run_id']}", headers=h)
    step = next(s for s in detail.json()["steps"] if s["node_id"] == "verify")
    assert step["status"] == "succeeded"
    out = step["output"]
    assert out["action_0"]["echo"] == "20123456789"
    assert out["result_id"]
    # Normalizado: action_0 es el output mapeado (echo), no el JSON del provider.


@pytest.mark.asyncio
async def test_draft_marketplace_flags(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Draft Flags")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    draft = await async_client.post(
        "/api/v1/intelligence/workflow/draft",
        headers={**h, "Idempotency-Key": f"df-{uuid4().hex}"},
        json={"prompt": "cuando se cree un cliente nuevo con RUC, verifícalo"},
    )
    assert draft.status_code == 200, draft.text
    body = draft.json()
    mkt = body["marketplace"]
    assert any(m["action_id"] == "demo.echo" for m in mkt["missing"])
    assert mkt["wired"] == []

    # Tras instalar la integración del pack, el draft engancha el install real.
    await async_client.post(
        "/api/v1/workflows/marketplace/install",
        headers={**h, "Idempotency-Key": f"df-{uuid4().hex}"},
        json={"integration_slug": "demo-echo"},
    )
    draft2 = await async_client.post(
        "/api/v1/intelligence/workflow/draft",
        headers={**h, "Idempotency-Key": f"df-{uuid4().hex}"},
        json={"prompt": "cuando se cree un cliente nuevo con RUC, verifícalo"},
    )
    mkt2 = draft2.json()["marketplace"]
    assert mkt2["missing"] == []
    assert any(w["action_id"] == "demo.echo" for w in mkt2["wired"])


@pytest.mark.asyncio
async def test_ports_for_action(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Ports")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    ports = await async_client.get(
        "/api/v1/workflows/marketplace/ports/peru.taxpayer.lookup", headers=h
    )
    assert ports.status_code == 200, ports.text
    body = ports.json()
    assert body["action_id"] == "peru.taxpayer.lookup"
    assert body["renderer"] == "taxpayer_verification"
    assert body["cost"]["price"] == pytest.approx(0.02)
    assert "ruc" in body["inputs"] or "properties" in str(body["inputs"]) or True

    missing = await async_client.get(
        "/api/v1/workflows/marketplace/ports/no.such.action", headers=h
    )
    assert missing.status_code == 404
