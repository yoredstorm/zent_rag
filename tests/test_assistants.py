# =============================================================================
# Living Assistants — descripción "cuando", salud y endpoint de automatizaciones
# por agente (Integration Experience §21-§24, §30-§31).
# =============================================================================
from __future__ import annotations

import json
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from src.platform.workflows.assistants import (
    assistant_status,
    describe_when,
    summarize_workflow,
)
from tests.test_workflows import _create_org, _headers, _owner_session


def test_describe_when_in_business_language() -> None:
    assert describe_when("event", {"event_type": "sales.closed"}) == "Se cerró una venta"
    assert "todos los días" in describe_when("schedule", {"daily": {"time": "08:00"}}).lower()
    assert describe_when("webhook", {}) == "Cuando se reciba una señal externa"
    assert describe_when("manual", {}) == "Cuando se ejecute manualmente"
    assert describe_when("event", {}, watcher_event_type="inventory.stock.low") == "El stock bajó del mínimo"


def test_summarize_workflow() -> None:
    stats = summarize_workflow(
        [
            {"status": "succeeded", "started_at": "2026-09-13T10:00:00+00:00"},
            {"status": "failed", "started_at": "2026-09-12T10:00:00+00:00"},
            {"status": "simulated", "started_at": "2026-09-11T10:00:00+00:00"},
        ]
    )
    assert stats["runs"] == 3
    assert stats["ok_runs"] == 2
    assert stats["success_rate"] == 66.7
    assert stats["last_activity"] == "2026-09-13T10:00:00+00:00"
    assert summarize_workflow([])["success_rate"] is None


def test_assistant_status() -> None:
    assert assistant_status([]) == "idle"
    assert assistant_status([{"status": "active", "failed_runs": 0}]) == "healthy"
    assert assistant_status([{"status": "active", "failed_runs": 1}]) == "needs_attention"
    assert assistant_status([{"status": "paused"}, {"status": "paused"}]) == "paused"
    assert assistant_status([{"status": "error", "failed_runs": 0}]) == "needs_attention"


@pytest.mark.asyncio
async def test_agent_automations_unknown_agent_returns_404(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Assistants 404")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    resp = await async_client.get(
        f"/api/v1/agents/{uuid4()}/automations", headers=_headers(org)
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_agent_automations_requires_valid_uuid(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Assistants UUID")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    resp = await async_client.get("/api/v1/agents/not-a-uuid/automations", headers=_headers(org))
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Assistant Home + Activity Feed + Inbox (§22, §27-§29)
# ---------------------------------------------------------------------------
async def _seed_assistant(client: AsyncClient, org: dict, agent_id: str) -> dict:
    """Workflow (llm→agente) + run + steps para el feed de actividad."""
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    graph = {
        "nodes": [
            {"id": "n1", "type": "llm", "version": 1, "config": {"agent_id": agent_id, "prompt": "Analiza"}},
        ],
        "edges": [],
        "entrypoints": ["n1"],
    }
    session = await get_async_session()
    try:
        wf_id = (
            await session.execute(
                text(
                    "INSERT INTO workflows (name, organization_id, status, trigger_type, "
                    "trigger_config, graph, workflow_version, graph_source) "
                    "VALUES ('Stock bajo', :oid, 'active', 'event', '{}'::jsonb, "
                    "CAST(:graph AS jsonb), 2, 'v2') RETURNING id"
                ),
                {"oid": org["organization_id"], "graph": json.dumps(graph)},
            )
        ).scalar()
        run_id = (
            await session.execute(
                text(
                    "INSERT INTO workflow_runs (workflow_id, organization_id, trigger, status, "
                    "started_at, completed_at, duration_ms, correlation_id) "
                    "VALUES (:wid, :oid, 'event', 'succeeded', NOW() - interval '2 minutes', "
                    "NOW() - interval '2 minutes' + interval '4 seconds', 4000, 'corr-test-1') RETURNING id"
                ),
                {"wid": wf_id, "oid": org["organization_id"]},
            )
        ).scalar()
        await session.execute(
            text(
                "INSERT INTO workflow_run_steps "
                "(run_id, step_index, step_type, node_id, node_type, status, input, output, "
                "duration_ms, started_at, completed_at) VALUES "
                "(:rid, 0, 'llm', 'n1', 'llm', 'succeeded', '{}'::jsonb, "
                "CAST(:out AS jsonb), 3200, NOW() - interval '2 minutes', NOW() - interval '2 minutes'), "
                "(:rid, 1, 'notify', 'n2', 'notify', 'succeeded', "
                "CAST('{\"title\": \"Stock bajo\"}' AS jsonb), '{}'::jsonb, 120, "
                "NOW() - interval '2 minutes', NOW() - interval '2 minutes')"
            ),
            {
                "rid": run_id,
                "out": json.dumps({"text": "Recomiendo reponer 40 unidades de Laptop A."}),
            },
        )
        await session.commit()
    finally:
        await session.close()
    return {"workflow_id": str(wf_id), "run_id": str(run_id)}


@pytest.mark.asyncio
async def test_assistants_home_and_activity_feed(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Assistant Home")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    created = await async_client.post(
        "/api/v1/agents",
        headers=h,
        json={"name": "Asistente de Inventario", "description": "Vigila el stock"},
    )
    assert created.status_code == 201, created.text
    agent_id = created.json()["id"]
    seeded = await _seed_assistant(async_client, org, agent_id)

    home = await async_client.get("/api/v1/agents/assistants", headers=h)
    assert home.status_code == 200, home.text
    assistant = next(a for a in home.json()["assistants"] if a["id"] == agent_id)
    assert assistant["automations"] == 1
    assert assistant["active"] == 1
    assert assistant["health"] == "healthy"
    assert any("evento" in watch.lower() or "venta" in watch.lower() for watch in assistant["watches"])

    detail = await async_client.get(f"/api/v1/agents/{agent_id}/automations", headers=h)
    body = detail.json()
    assert body["automations"][0]["workflow_id"] == seeded["workflow_id"]
    assert body["automations"][0]["when"]

    activity = await async_client.get(f"/api/v1/agents/{agent_id}/activity", headers=h)
    assert activity.status_code == 200, activity.text
    feed = activity.json()
    titles = [item["title"] for item in feed["items"]]
    assert any("Se inició" in title for title in titles)
    assert any("El agente analizó" in title for title in titles)
    assert any("notificación" in item["kind"] for item in feed["items"])
    llm_item = next(item for item in feed["items"] if item["kind"] == "análisis")
    assert "reponer 40 unidades" in (llm_item["detail"] or "")
    assert llm_item["tech"]["run_id"] == seeded["run_id"]
    assert llm_item["tech"]["correlation_id"] == "corr-test-1"

    unknown = await async_client.get(f"/api/v1/agents/{uuid4()}/activity", headers=h)
    assert unknown.status_code == 404


@pytest.mark.asyncio
async def test_inbox_acknowledge_hides_resolved_result(async_client: AsyncClient) -> None:
    from src.platform.intelligence.results import BusinessResult, save_result

    org = await _create_org(async_client, "Assistant Inbox")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)
    saved = await save_result(
        UUID(org["organization_id"]),
        BusinessResult(
            title="Stock crítico",
            summary="SKU-123 con 8 unidades",
            section="needs_attention",
            importance="CRITICAL",
            recommendations=["Solicitar 40 unidades"],
            source="test",
        ),
        notify=False,
    )

    inbox = await async_client.get("/api/v1/intelligence/results", headers=h)
    assert inbox.status_code == 200, inbox.text
    assert any(r["id"] == saved["result_id"] for r in inbox.json()["results"])

    ack = await async_client.post(
        f"/api/v1/intelligence/results/{saved['result_id']}/acknowledge", headers=h
    )
    assert ack.status_code == 200, ack.text
    assert ack.json()["acknowledged_at"]

    after = await async_client.get("/api/v1/intelligence/results", headers=h)
    assert all(r["id"] != saved["result_id"] for r in after.json()["results"])
    visible = await async_client.get(
        "/api/v1/intelligence/results", headers=h, params={"include_acknowledged": "true"}
    )
    resolved = next(r for r in visible.json()["results"] if r["id"] == saved["result_id"])
    assert resolved["acknowledged_at"]
