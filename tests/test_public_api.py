# =============================================================================
# Public API (PROMPT 06) — query por slug, output schema, logs, key hardening
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient


async def _create_org(client: AsyncClient, name: str) -> dict:
    resp = await client.post(
        "/api/v1/billing/subscription/create-trial",
        json={
            "company_name": name,
            "email": f"pub-{uuid4().hex[:8]}@example.com",
            "country": "CL",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


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


async def _deploy_agent(client: AsyncClient, h: dict, name: str) -> tuple[dict, dict]:
    agent = (
        await client.post(
            "/api/v1/agents",
            headers=h,
            json={
                "name": name,
                "system_prompt": "Responde SOLO con JSON.",
                "model": "gpt-4o-mini",
                "tools": [],
                "config": {
                    "output_schema": {"product": "string", "stock": "integer"}
                },
            },
        )
    ).json()
    version = (
        await client.post(f"/api/v1/agents/{agent['id']}/versions", headers=h, json={})
    ).json()
    await client.post(
        f"/api/v1/agents/{agent['id']}/versions/{version['id']}/promote",
        headers=h,
        json={"status": "ready"},
    )
    envs = (await client.get("/api/v1/environments", headers=h)).json()["environments"]
    prod = next(e for e in envs if e["slug"] == "production")
    deployment = await client.post(
        "/api/v1/deployments",
        headers=h,
        json={
            "agent_id": agent["id"],
            "agent_version_id": version["id"],
            "environment_id": prod["id"],
        },
    )
    assert deployment.status_code == 201, deployment.text
    return agent, deployment.json()


@pytest.mark.asyncio
async def test_public_query_runs_and_logs(async_client: AsyncClient) -> None:
    from src.agents.runtime.agent_runtime import AgentRunResult
    from src.api.deps import get_agent_runtime
    from src.api.main import app

    class _FakeRuntime:
        async def run(self, request):
            return AgentRunResult(
                run_id=uuid4(),
                agent_id=request.agent.id,
                organization_id=request.agent.organization_id,
                status="completed",
                answer='{"product": "ABC", "stock": 42}',
                message=request.message,
                user_id=request.user_id,
                role=request.role,
                total_latency_ms=42.0,
                total_tokens=120,
                cost=0.001,
            )

    fake = _FakeRuntime()
    app.dependency_overrides[get_agent_runtime] = lambda: fake

    org = await _create_org(async_client, "Public Org")
    org["session"] = await _owner_session(org["organization_id"])
    h = _headers(org)
    agent, deployment = await _deploy_agent(async_client, h, "Public Agent")

    resp = await async_client.post(
        f"/api/v1/deployments/{deployment['slug']}/query",
        headers=h,
        json={"input": "¿Cuánto stock queda del producto ABC?"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["request_id"]
    assert isinstance(body["answer"], str)
    assert body["latency_ms"] is not None
    assert body["data"] is not None  # output_schema validado
    assert "stock" in body["data"]

    logs = await async_client.get("/api/v1/deployments/logs", headers=h)
    assert logs.status_code == 200, logs.text
    assert logs.json()["count"] >= 1
    latest = logs.json()["logs"][0]
    assert latest["endpoint"] == f"/api/v1/deployments/{deployment['slug']}/query"
    assert latest["status"] == 200
    assert latest["request_id"] == body["request_id"]

    # Aislamiento: otro tenant no ve los logs.
    org_b = await _create_org(async_client, "Public B")
    org_b["session"] = await _owner_session(org_b["organization_id"])
    resp = await async_client.get(
        "/api/v1/deployments/logs", headers=_headers(org_b)
    )
    assert resp.status_code == 200
    assert resp.json()["count"] == 0

    # Query a un deployment inexistente → 404.
    resp = await async_client.post(
        "/api/v1/deployments/not-exists/query", headers=h, json={"input": "x"}
    )
    assert resp.status_code == 404


class TestOutputSchema:
    def test_validates_object(self) -> None:
        from src.platform.deployments.output_schema import validate_json_answer

        schema = {"type": "object", "required": ["product", "stock"],
                  "properties": {"product": {"type": "string"}, "stock": {"type": "integer"}}}
        data, errors = validate_json_answer('{"product": "ABC", "stock": 42}', schema)
        assert errors == []
        assert data == {"product": "ABC", "stock": 42}

    def test_reports_missing_required(self) -> None:
        from src.platform.deployments.output_schema import validate_json_answer

        schema = {"type": "object", "required": ["stock"],
                  "properties": {"stock": {"type": "integer"}}}
        _data, errors = validate_json_answer('{"product": "ABC"}', schema)
        assert any("stock" in e for e in errors)

    def test_reports_type_mismatch(self) -> None:
        from src.platform.deployments.output_schema import validate_json_answer

        schema = {"type": "object",
                  "properties": {"stock": {"type": "integer"}}}
        _data, errors = validate_json_answer('{"stock": "mucho"}', schema)
        assert any("integer" in e for e in errors)

    def test_invalid_json(self) -> None:
        from src.platform.deployments.output_schema import validate_json_answer

        _data, errors = validate_json_answer("no es json", {})
        assert errors and "JSON" in errors[0]

    def test_array_items(self) -> None:
        from src.platform.deployments.output_schema import validate_json_answer

        schema = {"type": "array", "items": {"type": "string"}}
        data, errors = validate_json_answer('["a", "b"]', schema)
        assert errors == []
        assert data == ["a", "b"]
        _data, errors = validate_json_answer('["a", 3]', schema)
        assert len(errors) == 1


@pytest.mark.asyncio
async def test_key_limits_enforced(async_client: AsyncClient) -> None:
    """IP allowlist y rate limit por API key."""
    from src.infrastructure.postgres.relational_db import (
        PostgresApiKeyRepository,
        PostgresBillingRepository,
    )
    from src.platform.billing.service import BillingService

    org = await _create_org(async_client, "KeyLimits Org")
    org["session"] = await _owner_session(org["organization_id"])
    h = _headers(org)
    _agent, deployment = await _deploy_agent(async_client, h, "KeyLimits Agent")

    billing = BillingService(PostgresBillingRepository(), PostgresApiKeyRepository())
    token = await billing.create_api_key(
        UUID(org["organization_id"]),
        name="limited",
        scopes=["agents:execute"],
        created_by=None,
    )
    key_id = (
        await PostgresApiKeyRepository().list_keys(UUID(org["organization_id"]))
    )[0].id
    # Ajustar la key recién creada: allowlist de una IP imposible + rate limit 1.
    update = await async_client.put(
        f"/api/v1/organizations/api-keys/{key_id}",
        headers=h,
        json={"ip_allowlist": ["203.0.113.9"], "rate_limit_per_minute": 1},
    )
    assert update.status_code == 200, update.text

    limited_headers = {
        "Authorization": f"Bearer {token}",
        "X-Organization-Id": org["organization_id"],
    }
    # IP fuera de la allowlist → 403.
    resp = await async_client.get("/api/v1/deployments", headers=limited_headers)
    assert resp.status_code == 403, resp.text
    assert resp.json()["error_code"] == "ip_not_allowed"

    # Permitir la IP del test (testclient) y probar rate limit sobre el
    # endpoint público (único accesible con el scope agents:execute).
    from src.agents.runtime.agent_runtime import AgentRunResult
    from src.api.deps import get_agent_runtime
    from src.api.main import app

    class _FakeRuntime:
        async def run(self, request):
            return AgentRunResult(
                run_id=uuid4(),
                agent_id=request.agent.id,
                organization_id=request.agent.organization_id,
                status="completed",
                answer='{"product": "ABC", "stock": 42}',
                message=request.message,
                total_latency_ms=5.0,
                total_tokens=10,
                cost=0.0001,
            )

    app.dependency_overrides[get_agent_runtime] = lambda: _FakeRuntime()

    update2 = await async_client.put(
        f"/api/v1/organizations/api-keys/{key_id}",
        headers=h,
        json={"ip_allowlist": [], "rate_limit_per_minute": 1},
    )
    assert update2.status_code == 200, update2.text
    query_path = f"/api/v1/deployments/{deployment['slug']}/query"
    first = await async_client.post(
        query_path, headers=limited_headers, json={"input": "stock"}
    )
    assert first.status_code == 200, first.text
    second = await async_client.post(
        query_path, headers=limited_headers, json={"input": "stock"}
    )
    assert second.status_code == 429, second.text

    # Otro tenant no puede actualizar la key.
    org_b = await _create_org(async_client, "KeyLimits B")
    org_b["session"] = await _owner_session(org_b["organization_id"])
    resp = await async_client.put(
        f"/api/v1/organizations/api-keys/{key_id}",
        headers=_headers(org_b),
        json={"name": "hack"},
    )
    assert resp.status_code == 404
