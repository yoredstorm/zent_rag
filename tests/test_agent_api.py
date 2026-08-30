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


@pytest.mark.asyncio
async def test_create_returns_parsed_config(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Agent Config Org")
    org["session"] = await _owner_session(org["organization_id"])
    headers = _headers(org)

    create = await async_client.post(
        "/api/v1/agents",
        json={
            "name": f"pharmacy-{uuid4().hex[:8]}",
            "tools": ["search_knowledge"],
            "model": "gpt-4o-mini",
            "system_prompt": "Eres un asistente de farmacia.",
            "config": {
                "purpose": "Consultar stock y productos",
                "temperature": 0.2,
                "tone": "professional",
                "knowledge_base_ids": [],
                "limits": {"max_steps": 6, "max_tokens": 4000, "max_cost_usd": 0.5},
                "security": {"sql_enabled": False, "api_calls_enabled": False},
            },
        },
        headers=headers,
    )
    assert create.status_code == 201, create.text
    body = create.json()
    assert "config" in body
    assert body["config"]["purpose"] == "Consultar stock y productos"
    assert body["config"]["temperature"] == 0.2
    assert body["config"]["tone"] == "professional"
    assert body["config"]["limits"]["max_steps"] == 6
    assert body["config"]["security"]["sql_enabled"] is False

    fetched = await async_client.get(f"/api/v1/agents/{body['id']}", headers=headers)
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["config"]["temperature"] == 0.2
    assert fetched.json()["tools"] == ["search_knowledge"]


@pytest.mark.asyncio
async def test_update_tools_without_sql_run_does_not_execute_sql(
    async_client: AsyncClient,
) -> None:
    from src.api.deps import get_agent_runtime
    from src.api.main import app

    org = await _create_org(async_client, "Agent No SQL Org")
    org["session"] = await _owner_session(org["organization_id"])
    headers = _headers(org)

    create = await async_client.post(
        "/api/v1/agents",
        json={"name": f"rag-only-{uuid4().hex[:8]}", "tools": ["search_knowledge", "query_database"]},
        headers=headers,
    )
    assert create.status_code == 201, create.text
    agent_id = create.json()["id"]

    update = await async_client.put(
        f"/api/v1/agents/{agent_id}",
        json={"tools": ["search_knowledge"]},
        headers=headers,
    )
    assert update.status_code == 200, update.text
    assert update.json()["tools"] == ["search_knowledge"]
    assert "query_database" not in update.json()["tools"]

    fake = _FakeRuntime()
    app.dependency_overrides[get_agent_runtime] = lambda: fake
    try:
        resp = await async_client.post(
            f"/api/v1/agents/{agent_id}/run",
            json={"message": "lista stock"},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        assert fake.last_request is not None
        assert fake.last_request.agent.tools == ["search_knowledge"]
        assert "query_database" not in fake.last_request.agent.tools
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_update_rejects_foreign_knowledge_base_ids(
    async_client: AsyncClient,
) -> None:
    org_a = await _create_org(async_client, "Agent KB Org A")
    org_a["session"] = await _owner_session(org_a["organization_id"])
    org_b = await _create_org(async_client, "Agent KB Org B")
    org_b["session"] = await _owner_session(org_b["organization_id"])

    kb = await async_client.post(
        "/api/v1/knowledge-bases",
        json={"name": f"foreign-kb-{uuid4().hex[:8]}"},
        headers=_headers(org_a),
    )
    assert kb.status_code == 201, kb.text
    foreign_kb = kb.json()["id"]

    create = await async_client.post(
        "/api/v1/agents",
        json={"name": f"agent-b-{uuid4().hex[:8]}", "tools": ["search_knowledge"]},
        headers=_headers(org_b),
    )
    assert create.status_code == 201, create.text
    agent_id = create.json()["id"]

    update = await async_client.put(
        f"/api/v1/agents/{agent_id}",
        json={"config": {"knowledge_base_ids": [foreign_kb]}},
        headers=_headers(org_b),
    )
    assert update.status_code in (400, 404), update.text


@pytest.mark.asyncio
async def test_temperature_from_config_passed_to_llm(
    async_client: AsyncClient,
) -> None:
    from src.api.deps import get_agent_runtime
    from src.api.main import app

    org = await _create_org(async_client, "Agent Temp Org")
    org["session"] = await _owner_session(org["organization_id"])
    headers = _headers(org)

    create = await async_client.post(
        "/api/v1/agents",
        json={
            "name": f"temp-{uuid4().hex[:8]}",
            "tools": ["search_knowledge"],
            "config": {"temperature": 0.2},
        },
        headers=headers,
    )
    assert create.status_code == 201, create.text
    agent_id = create.json()["id"]
    assert create.json()["config"]["temperature"] == 0.2

    fake = _FakeRuntime()
    app.dependency_overrides[get_agent_runtime] = lambda: fake
    try:
        resp = await async_client.post(
            f"/api/v1/agents/{agent_id}/run",
            json={"message": "hola"},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        assert fake.last_request.agent.config_json["temperature"] == 0.2
    finally:
        app.dependency_overrides.clear()
