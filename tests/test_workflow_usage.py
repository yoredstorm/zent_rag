# =============================================================================
# Cognitive Workflows — metering de runs en usage_events.
#
# Evento `workflow_run` idempotente por request_id=run_id; el costo real de
# agentes ya lo registra AgentRuntime, aquí solo se anexa cost_ms en tags para
# evitar doble conteo monetario.
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
async def test_workflow_run_records_usage_event(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    org = await _create_org(async_client, "Usage Workflow")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    headers = _headers(org)

    from src.core.config import get_settings

    monkeypatch.setattr(get_settings(), "USAGE_ENGINE_ENABLED", True)

    graph = _graph(
        [
            _node("t", "trigger_webhook"),
            _node("v", "set_variable", {"name": "umbral", "value": "10"}),
        ],
        [_edge("e1", "t", "v")],
        ["t"],
    )
    created = await async_client.post(
        "/api/v1/workflows",
        headers={**headers, "Idempotency-Key": f"us-{uuid4().hex}"},
        json={"name": "Usage Workflow", "trigger_type": "webhook", "graph": graph},
    )
    assert created.status_code == 200, created.text
    run = await async_client.post(
        f"/api/v1/workflows/{created.json()['workflow_id']}/run",
        headers={**headers, "Idempotency-Key": f"usr-{uuid4().hex}"},
        json={"payload": {}, "simulate": True},
    )
    assert run.status_code == 200, run.text
    run_id = run.json()["run_id"]

    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT event_type, status, organization_id, cost_tags, routing "
                    "FROM usage_events WHERE request_id = :rid AND event_type = 'workflow_run'"
                ),
                {"rid": run_id},
            )
        ).fetchone()
    finally:
        await session.close()
    assert row is not None
    assert row.status in ("simulated", "succeeded")
    assert str(row.organization_id) == org["organization_id"]
    assert "cost_ms" in dict(row.cost_tags or {})
    assert dict(row.routing or {})["workflow_id"] == created.json()["workflow_id"]
