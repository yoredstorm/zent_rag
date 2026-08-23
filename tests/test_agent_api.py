# =============================================================================
# Agent API — endpoints /agents/{id}/run + traces
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from src.agents.runtime.agent_runtime import AgentRunResult


class _FakeRuntime:
    def __init__(self, result: AgentRunResult | None = None) -> None:
        self.result = result
        self.last_request = None

    async def run(self, request):
        self.last_request = request
        if self.result is not None:
            return self.result
        return AgentRunResult(
            run_id=uuid4(),
            agent_id=request.agent.id,
            organization_id=request.agent.organization_id,
            status="completed",
            answer="Respuesta del agente",
            message=request.message,
            user_id=request.user_id,
            role=request.role,
            steps=[{"type": "final", "answer": "Respuesta del agente"}],
            total_latency_ms=12.0,
            total_tokens=30,
            cost=0.00003,
        )


async def _create_org(client: AsyncClient, name: str) -> dict:
    response = await client.post(
        "/api/v1/billing/subscription/create-trial",
        json={
            "company_name": name,
            "email": f"ag-{uuid4().hex[:8]}@example.com",
            "country": "CL",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _owner_session(organization_id: str) -> str:
    from src.infrastructure.postgres.relational_db import PostgresUserRepository
    from src.platform.auth.session import encrypt_session

    user = await PostgresUserRepository().get_by_external_id(
        UUID(organization_id), "default-admin"
    )
    assert user is not None
    return encrypt_session(user.id, UUID(organization_id))


def _headers(org: dict) -> dict:
    return {
        "Authorization": f"Bearer {org['session']}",
        "X-Organization-Id": org["organization_id"],
    }


@pytest.mark.asyncio
async def test_run_agent_returns_answer(async_client: AsyncClient) -> None:
    from src.api.deps import get_agent_runtime
    from src.api.main import app

    org = await _create_org(async_client, "Agent API Org")
    org["session"] = await _owner_session(org["organization_id"])
    headers = _headers(org)

    fake = _FakeRuntime()
    app.dependency_overrides[get_agent_runtime] = lambda: fake

    create = await async_client.post(
        "/api/v1/agents",
        json={"name": f"agent-{uuid4().hex[:8]}", "tools": ["search_knowledge"]},
        headers=headers,
    )
    assert create.status_code == 201, create.text
    agent_id = create.json()["id"]

    try:
        resp = await async_client.post(
            f"/api/v1/agents/{agent_id}/run",
            json={"message": "¿Hay stock del producto X?"},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "completed"
        assert "Respuesta del agente" in data["answer"]
        assert data["steps"]
        assert data["total_tokens"] == 30
        assert fake.last_request.agent.organization_id is not None
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_run_agent_requires_auth(async_client: AsyncClient) -> None:
    from src.api.deps import get_agent_runtime
    from src.api.main import app

    app.dependency_overrides[get_agent_runtime] = lambda: _FakeRuntime()
    try:
        resp = await async_client.post(
            f"/api/v1/agents/{uuid4()}/run",
            json={"message": "hola"},
        )
        assert resp.status_code == 401, resp.text
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_run_agent_unknown_agent_404(async_client: AsyncClient) -> None:
    from src.api.deps import get_agent_runtime
    from src.api.main import app

    org = await _create_org(async_client, "Agent API Org 2")
    org["session"] = await _owner_session(org["organization_id"])

    app.dependency_overrides[get_agent_runtime] = lambda: _FakeRuntime()
    try:
        resp = await async_client.post(
            f"/api/v1/agents/{uuid4()}/run",
            json={"message": "hola"},
            headers=_headers(org),
        )
        assert resp.status_code == 404, resp.text
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_run_agent_inactive_409(async_client: AsyncClient) -> None:
    from src.api.deps import get_agent_runtime
    from src.api.main import app

    org = await _create_org(async_client, "Agent API Org 3")
    org["session"] = await _owner_session(org["organization_id"])
    headers = _headers(org)

    app.dependency_overrides[get_agent_runtime] = lambda: _FakeRuntime()
    try:
        create = await async_client.post(
            "/api/v1/agents",
            json={"name": f"inactive-{uuid4().hex[:8]}", "tools": []},
            headers=headers,
        )
        assert create.status_code == 201, create.text
        agent_id = create.json()["id"]
        update = await async_client.put(
            f"/api/v1/agents/{agent_id}",
            json={"is_active": False},
            headers=headers,
        )
        assert update.status_code == 200, update.text

        resp = await async_client.post(
            f"/api/v1/agents/{agent_id}/run",
            json={"message": "hola"},
            headers=headers,
        )
        assert resp.status_code == 409, resp.text
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_trace_store_real_db() -> None:
    from src.core.config import get_settings

    settings = get_settings()
    if settings.ENVIRONMENT != "development":
        pytest.skip("Requiere Postgres real (stack docker)")

    from src.agents.runtime.trace_store import (
        ensure_agent_runs_table,
        get_run,
        list_runs,
        save_run,
    )

    org = uuid4()
    agent_id = uuid4()
    result = AgentRunResult(
        run_id=uuid4(),
        agent_id=agent_id,
        organization_id=org,
        status="completed",
        answer="ok",
        message="hola",
        user_id=uuid4(),
        role="admin",
        steps=[{"type": "tool_call", "tool": "echo", "output": "echo: x"}],
        total_latency_ms=5.0,
        total_tokens=20,
        cost=0.00002,
    )
    await ensure_agent_runs_table()
    await save_run(result)

    run = await get_run(org, result.run_id)
    assert run is not None
    assert run["status"] == "completed"
    assert run["steps"][0]["tool"] == "echo"
    assert run["total_tokens"] == 20

    runs = await list_runs(org, agent_id=agent_id, limit=10)
    assert any(r["id"] == str(result.run_id) for r in runs)

    blob = str(run)
    assert "password" not in blob.lower()
