# =============================================================================
# Living Assistants — descripción "cuando", salud y endpoint de automatizaciones
# por agente (Integration Experience §21-§24, §30-§31).
# =============================================================================
from __future__ import annotations

from uuid import uuid4

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
