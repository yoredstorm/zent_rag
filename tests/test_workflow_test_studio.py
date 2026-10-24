from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from src.platform.workflows.test_report import draft_to_scenario, publication_blockers
from src.platform.workflows.test_studio import decide_test_level, report_hashes
from tests.test_workflows import _create_org, _headers, _owner_session


def _graph() -> dict:
    return {
        "workflow_version": 2,
        "nodes": [
            {"id": "t", "type": "trigger_webhook", "label": "Inicio", "config": {}},
            {"id": "end", "type": "end", "label": "Fin", "config": {}},
        ],
        "edges": [
            {
                "id": "e1",
                "from_node": "t",
                "from_port": "out",
                "to_node": "end",
                "to_port": "in",
            }
        ],
        "entrypoints": ["t"],
        "metadata": {
            "mission": {"goal": "Probar"},
            "semantic_plan_hash": "plan-1",
            "bindings": {"products": "binding-1"},
        },
    }


async def _org(client: AsyncClient, name: str) -> dict:
    org = await _create_org(client, name)
    org["session"] = await _owner_session(client, org["organization_id"])
    return org


async def _workspace(client: AsyncClient, org: dict) -> dict:
    listing = await client.get("/api/v1/workspaces", headers=_headers(org))
    assert listing.status_code == 200, listing.text
    return next(w for w in listing.json()["workspaces"] if w["slug"] == "default")


async def _workflow(client: AsyncClient, org: dict, ws: dict) -> str:
    created = await client.post(
        "/api/v1/workflows",
        headers={
            **_headers(org),
            "X-Workspace-Id": ws["id"],
            "Idempotency-Key": f"p08-{uuid4().hex}",
        },
        json={
            "name": "Test Studio P08",
            "trigger_type": "webhook",
            "workspace_id": ws["id"],
            "graph": _graph(),
        },
    )
    assert created.status_code == 200, created.text
    return created.json()["workflow_id"]


def test_provider_and_sandbox_are_capped_not_faked() -> None:
    provider = decide_test_level("provider")
    assert provider.effective == "simulation"
    assert provider.capped_reason == "provider_adapter_unavailable"
    sandbox = decide_test_level("sandbox")
    assert sandbox.effective == "simulation"
    assert sandbox.capped_reason == "sandbox_adapter_unavailable"
    preview = decide_test_level("preview")
    assert preview.effective == "preview"
    with pytest.raises(ValueError):
        decide_test_level("production")


def test_scenario_builder_accepts_human_fields_without_json() -> None:
    scenario = draft_to_scenario(
        {
            "name": "Pago repetido",
            "messages": ["Quiero pagar"],
            "events": [{"event_type": "payment.succeeded", "idempotency_key": "pay-1"}],
            "responses": [{"capability_ref": "payments.checkout.create", "output": {"ok": True}}],
            "forbidden_effects": ["payments.checkout.create:duplicate"],
        }
    )
    assert scenario.initial_inputs == {"message": "Quiero pagar"}
    assert scenario.events[0].event_type == "payment.succeeded"
    assert scenario.responses[0].capability_ref == "payments.checkout.create"
    assert scenario.forbidden_effects == ["payments.checkout.create:duplicate"]


def test_hashes_are_stable_and_change_with_graph() -> None:
    workflow = {"graph": _graph()}
    first = report_hashes(workflow, _graph())
    second = report_hashes(workflow, _graph())
    assert first == second
    changed = _graph()
    changed["nodes"][1]["label"] = "Fin cambiado"
    assert report_hashes(workflow, changed)["graph_hash"] != first["graph_hash"]
    certificate = {
        "graph_hash": first["graph_hash"],
        "level": "provider",
        "state": "READY_TO_PUBLISH",
        "publishable": True,
        "unverified": 0,
        "capability_snapshot_hash": "snap",
    }
    blockers = publication_blockers(
        changed,
        certificate,
        semantic_plan_hash="plan-1",
        production_enabled=True,
    )
    assert any(item["code"] == "certificate_stale" for item in blockers)


@pytest.mark.asyncio
async def test_test_levels_and_persisted_report(async_client: AsyncClient) -> None:
    org = await _org(async_client, "P08 Test Studio")
    ws = await _workspace(async_client, org)
    workflow_id = await _workflow(async_client, org, ws)

    preview = await async_client.post(
        f"/api/v1/workflows/{workflow_id}/test",
        headers=_headers(org),
        json={
            "requested_level": "preview",
            "scenario": {"messages": ["hola"]},
        },
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["result"] == "PREVIEW"
    assert preview.json()["provider_verified"] is False

    simulated = await async_client.post(
        f"/api/v1/workflows/{workflow_id}/test",
        headers=_headers(org),
        json={
            "requested_level": "simulation",
            "scenario": {"messages": ["hola"], "max_segments": 3},
        },
    )
    assert simulated.status_code == 200, simulated.text
    body = simulated.json()
    assert body["effective_level"] == "simulation"
    assert body["provider_verified"] is False
    assert body["report_id"]
    assert len(body["hashes"]["graph_hash"]) == 64
    assert body["hashes"]["plan_hash"] == "plan-1"

    provider = await async_client.post(
        f"/api/v1/workflows/{workflow_id}/test",
        headers=_headers(org),
        json={
            "requested_level": "provider",
            "scenario": {"messages": ["paga"]},
        },
    )
    assert provider.status_code == 200, provider.text
    assert provider.json()["effective_level"] == "simulation"
    assert provider.json()["result"] == "UNVERIFIED"
    assert provider.json()["capped_reason"] == "provider_adapter_unavailable"

    listed = await async_client.get(
        f"/api/v1/workflows/{workflow_id}/test-reports", headers=_headers(org)
    )
    assert listed.status_code == 200, listed.text
    assert len(listed.json()["items"]) == 3
    assert all(item["hashes"]["graph_hash"] for item in listed.json()["items"])


@pytest.mark.asyncio
async def test_test_endpoint_is_workspace_scoped(async_client: AsyncClient) -> None:
    org = await _org(async_client, "P08 Workspace")
    ws_a = await _workspace(async_client, org)
    workflow_id = await _workflow(async_client, org, ws_a)
    created = await async_client.post(
        "/api/v1/workspaces", headers=_headers(org), json={"name": "Test B"}
    )
    assert created.status_code == 201, created.text
    ws_b = created.json()
    response = await async_client.post(
        f"/api/v1/workflows/{workflow_id}/test",
        headers={**_headers(org), "X-Workspace-Id": ws_b["id"]},
        json={"requested_level": "simulation", "scenario": {"messages": ["hola"]}},
    )
    assert response.status_code == 404
