from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from httpx import AsyncClient

from src.platform.workflows.operations import build_operations_queue
from tests.test_workflows import _create_org, _headers, _owner_session


def _row(status: str, *, event: str | None = None, error: str = "", age_minutes: int = 1) -> dict:
    return {
        "id": uuid4(),
        "workflow_id": uuid4(),
        "workspace_id": uuid4(),
        "status": status,
        "business_key": "order-1",
        "waiting_event_type": event,
        "error": error,
        "updated_at": datetime.now(timezone.utc) - timedelta(minutes=age_minutes),
    }


def test_operations_queue_prioritizes_failures_and_human_waits() -> None:
    queue = build_operations_queue(
        [
            _row("FAILED", error="permiso insuficiente", age_minutes=5),
            _row("WAITING", event="approval.decided", age_minutes=10),
            _row("WAITING", event="conversation.message", age_minutes=2),
            _row("COMPLETED", age_minutes=1),
        ]
    )
    assert queue["total"] == 2
    kinds = {item["kind"] for item in queue["items"]}
    assert "failed" in kinds
    assert "pending_approval" in kinds
    assert queue["summary"]["failed"] == 1
    assert queue["summary"]["needs_human"] == 1
    failed = next(item for item in queue["items"] if item["kind"] == "failed")
    assert failed["fault"] == "policy"
    assert failed["recommended_action"] == "manual_review"


def test_operations_queue_ignores_running_and_completed() -> None:
    queue = build_operations_queue([_row("RUNNING"), _row("COMPLETED")])
    assert queue["items"] == []
    assert queue["summary"]["failed"] == 0


@pytest.mark.asyncio
async def test_operations_queue_api_is_scoped_and_empty_safe(
    async_client: AsyncClient,
) -> None:
    org = await _create_org(async_client, "P11 Ops Queue")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    response = await async_client.get(
        "/api/v1/workflows/operations/queue", headers=_headers(org)
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["items"] == []
    assert body["summary"]["failed"] == 0
