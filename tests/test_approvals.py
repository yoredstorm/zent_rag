# =============================================================================
# FASE 03 (S14) — Human-in-the-loop: gate de aprobación en el runtime
# =============================================================================
"""Tools flaggeadas pausan el run en 'awaiting_approval' hasta decisión humana."""
from uuid import UUID, uuid4

import pytest

from src.platform.approvals.service import (
    approval_required_tools,
    decide_approval,
    has_recent_approval,
    list_approvals,
    request_approval,
)


def test_approval_required_tools_parses_config():
    assert approval_required_tools({"approval_required": ["call_api", "query_database"]}) == [
        "call_api",
        "query_database",
    ]
    assert approval_required_tools({}) == []
    assert approval_required_tools(None) == []


@pytest.mark.asyncio
async def test_approval_request_and_decide_flow():
    org = UUID("00000000-0000-0000-0000-000000000001")
    from src.infrastructure.postgres.relational_db import PostgresAgentRepository

    agent = await PostgresAgentRepository().create_agent(org, f"appr-{uuid4().hex[:6]}")
    agent_id = agent.id
    run_id = uuid4()

    assert await has_recent_approval(org, agent_id, "call_api") is False

    await request_approval(org, agent_id, run_id, "call_api", "aprobar api write")
    approvals = await list_approvals(org, status="pending")
    assert any(a["tool"] == "call_api" and a["status"] == "pending" for a in approvals)

    pending = next(a for a in approvals if a["tool"] == "call_api")
    assert await decide_approval(org, UUID(pending["id"]), approved=True, decided_by=uuid4()) is True
    # Re-aprobar la misma no se puede (ya no está pending).
    assert await decide_approval(org, UUID(pending["id"]), approved=True, decided_by=uuid4()) is False

    assert await has_recent_approval(org, agent_id, "call_api") is True
    # La aprobación se marca como usada → segunda vez no hay.
    assert await has_recent_approval(org, agent_id, "call_api") is False


@pytest.mark.asyncio
async def test_approval_reject():
    org = UUID("00000000-0000-0000-0000-000000000001")
    from src.infrastructure.postgres.relational_db import PostgresAgentRepository

    agent = await PostgresAgentRepository().create_agent(org, f"appr-{uuid4().hex[:6]}")
    agent_id = agent.id
    run_id = uuid4()
    await request_approval(org, agent_id, run_id, "query_database", "sql sensible")
    approvals = await list_approvals(org, status="pending")
    pending = next(a for a in approvals if a["tool"] == "query_database")
    assert await decide_approval(org, UUID(pending["id"]), approved=False, decided_by=None) is True
    assert await has_recent_approval(org, agent_id, "query_database") is False
