# =============================================================================
# FASE 03 (S18) — Delegated permissions: intersección caller ∩ agente ∩ tool
# =============================================================================
"""Negative tests: un agente NUNCA hereda privilegios ilimitados del caller."""
from uuid import UUID, uuid4

import pytest

from src.platform.agents.permissions import (
    get_agent_permissions,
    set_agent_permissions,
)


@pytest.mark.asyncio
async def test_agent_without_grants_is_compat(dev_api_token, async_client):
    """Sin grants explícitos → None (compat: usa permisos del caller)."""
    org = UUID("00000000-0000-0000-0000-000000000001")
    perms = await get_agent_permissions(uuid4())
    assert perms is None


@pytest.mark.asyncio
async def test_agent_permissions_crud(dev_api_token, async_client):
    from src.infrastructure.postgres.relational_db import PostgresAgentRepository

    repo = PostgresAgentRepository()
    org = UUID("00000000-0000-0000-0000-000000000001")
    agent = await repo.create_agent(org, f"perm-agent-{uuid4().hex[:6]}")
    await set_agent_permissions(org, agent.id, ["rag:read", "agents:read"])

    perms = await get_agent_permissions(agent.id)
    assert perms is not None
    assert "rag:read" in perms
    assert "agents:read" in perms
    # vacío = deny-all explícito (sentinel, no None)
    await set_agent_permissions(org, agent.id, [])
    got = await get_agent_permissions(agent.id)
    assert got is not None
    assert "__zent_deny_all__" in got


@pytest.mark.asyncio
async def test_agent_permissions_api_negative(dev_api_token, async_client):
    """El agente con grants restringidos NO puede ejecutar tools fuera de su grant."""
    from sqlalchemy import text

    from src.agents.tools.base import Tool, ToolContext, ToolResult
    from src.agents.tools.registry import tool_allowed
    from src.infrastructure.postgres.session import get_async_session

    class _StubTool(Tool):
        def __init__(self, name: str, permission: str) -> None:
            self.name = name
            self.permission = permission

        async def execute(self, ctx, args) -> ToolResult:
            return ToolResult(output="ok")

    org = UUID("00000000-0000-0000-0000-000000000001")
    from src.infrastructure.postgres.relational_db import PostgresAgentRepository

    agent = await PostgresAgentRepository().create_agent(org, f"neg-{uuid4().hex[:6]}")
    agent_id = agent.id
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO agent_permissions (agent_id, permission) "
                "VALUES (:aid, 'rag:read')"
            ),
            {"aid": agent_id},
        )
        await session.commit()
    finally:
        await session.close()

    # Caller tiene rag:read + agents:execute; agente solo rag:read.
    ctx = ToolContext(
        tenant_id=org,
        user_id=uuid4(),
        role="admin",
        permissions=frozenset({"rag:read", "agents:execute"}),
        agent_permissions=await get_agent_permissions(agent_id),
    )

    read_tool = _StubTool("search_knowledge", "rag:read")
    execute_tool = _StubTool("execute_agent", "agents:execute")

    assert tool_allowed(read_tool, ["search_knowledge"], ctx) is True
    # Aunque el caller tenga agents:execute, el agente no → DENY (nunca hereda).
    assert tool_allowed(execute_tool, ["execute_agent"], ctx) is False

    # Sin grants (compat) → el caller decide.
    compat_ctx = ToolContext(
        tenant_id=org,
        user_id=uuid4(),
        role="admin",
        permissions=frozenset({"rag:read", "agents:execute"}),
    )
    assert tool_allowed(execute_tool, ["execute_agent"], compat_ctx) is True
