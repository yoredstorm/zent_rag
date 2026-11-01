# =============================================================================
# P18.5-06 — El test conserva el input que realmente consumió.
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.test_workflow_published_snapshot import _marker_graph
from tests.test_workflows import _create_org, _headers, _owner_session


async def _workflow(client: AsyncClient, name: str) -> tuple[dict, str]:
    org = await _create_org(client, name)
    org["session"] = await _owner_session(client, org["organization_id"])
    created = await client.post(
        "/api/v1/workflows",
        headers={**_headers(org), "Idempotency-Key": f"p185-{uuid4().hex}"},
        json={
            "name": name,
            "trigger_type": "webhook",
            "graph": _marker_graph("A"),
            "workflow_version": 2,
        },
    )
    assert created.status_code == 200, created.text
    return org, created.json()["workflow_id"]


@pytest.mark.asyncio
async def test_test_report_snapshots_scenario_input(async_client: AsyncClient) -> None:
    org, workflow_id = await _workflow(async_client, "P18.5 payload snapshot")
    response = await async_client.post(
        f"/api/v1/workflows/{workflow_id}/test",
        headers={**_headers(org), "Idempotency-Key": f"p185-{uuid4().hex}"},
        json={
            "requested_level": "simulation",
            "scenario": {
                "scenario_id": "studio",
                "messages": ['{"message":"hola","order_id":"A-1"}'],
            },
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    snapshot = body["input_snapshot"]
    assert snapshot["kind"] == "scenario.messages"
    assert snapshot["contract"] == "test_text_vs_run_payload"
    assert snapshot["message_count"] == 1
    assert '{"message":"hola"' in snapshot["messages_preview"][0]
    assert "texto" in snapshot["note"].lower()
    assert body["scenario"]["messages"] == snapshot["scenario"]["messages"]


@pytest.mark.asyncio
async def test_invalid_scenario_messages_return_400(async_client: AsyncClient) -> None:
    org, workflow_id = await _workflow(async_client, "P18.5 payload invalid")
    response = await async_client.post(
        f"/api/v1/workflows/{workflow_id}/test",
        headers={**_headers(org), "Idempotency-Key": f"p185-{uuid4().hex}"},
        json={
            "requested_level": "simulation",
            "scenario": {"scenario_id": "studio", "messages": [{"no": "texto"}]},
        },
    )
    assert response.status_code == 400, response.text
    assert "messages" in response.text
