from uuid import uuid4

import pytest

from src.platform.workflows.planner_tools import PlannerToolContext, dispatch_tool
from tests.test_workflow_planner_agentic import _snapshot


@pytest.mark.asyncio
async def test_repeated_capability_search_is_served_from_session_cache() -> None:
    snapshot = _snapshot()
    ctx = PlannerToolContext(
        organization_id=uuid4(),
        workspace_id=None,
        snapshot=snapshot,
        permissions=frozenset({"workflows:read"}),
    )
    args = {"query": "productos", "limit": 3}

    first = await dispatch_tool("capability.search", args, ctx, session_id="s1")
    second = await dispatch_tool("capability.search", args, ctx, session_id="s1")

    assert first["observation"]["cached"] is False
    assert second["observation"]["cached"] is True
    assert first["observation"]["result_hash"] == second["observation"]["result_hash"]
    assert len(ctx.cache) == 1
    assert ctx.cache_hits == 1
