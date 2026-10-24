# =============================================================================
# P03 — Solution Compiler: misión → blueprint → recursos reales.
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from tests.test_workflows import _create_org, _headers, _owner_session


async def _org(client: AsyncClient, name: str) -> dict:
    org = await _create_org(client, name)
    org["session"] = await _owner_session(client, org["organization_id"])
    return org


async def _compile(client: AsyncClient, org: dict, body: dict) -> dict:
    response = await client.post(
        "/api/v1/studio/solutions/compile",
        headers=_headers(org),
        json=body,
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _materialize(
    client: AsyncClient, org: dict, body: dict, *, key: str | None = None
) -> dict:
    payload = {
        **body,
        "confirm": True,
        "idempotency_key": key or f"p03-{uuid4().hex}",
    }
    response = await client.post(
        "/api/v1/studio/solutions/materialize",
        headers=_headers(org),
        json=payload,
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _counts(org: dict) -> dict[str, int]:
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        out = {}
        for label, sql in (
            ("roles", "SELECT count(*) FROM role_profiles WHERE organization_id = :oid"),
            ("agents", "SELECT count(*) FROM agents WHERE organization_id = :oid"),
            ("workflows", "SELECT count(*) FROM workflows WHERE organization_id = :oid"),
            (
                "materializations",
                "SELECT count(*) FROM studio_solution_materializations WHERE organization_id = :oid",
            ),
        ):
            row = (
                await session.execute(text(sql), {"oid": UUID(org["organization_id"])})
            ).fetchone()
            out[label] = int(row[0] or 0)
        return out
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_compile_mentor_is_pure_and_logical(async_client: AsyncClient) -> None:
    org = await _org(async_client, "P03 Compile Mentor")
    before = await _counts(org)

    compiled = await _compile(
        async_client,
        org,
        {"brief": "Quiero un mentor de Python con progreso y ejercicios"},
    )

    assert compiled["status"] == "READY_TO_MATERIALIZE"
    assert compiled["template_id"] == "mentor"
    assert compiled["blueprint"]["roles"][0]["role_ref"] == "mentor"
    assert compiled["blueprint"]["agents"][0]["agent_ref"] == "mentor_agent"
    assert compiled["blueprint"]["workflows"][0]["workflow_ref"] == "mentor_flow"
    assert "record_id" not in compiled["blueprint"]["agents"][0]
    assert "agent_id" not in compiled["graph_preview"]["nodes"][1]["config"]
    assert compiled["scenarios"]
    assert await _counts(org) == before


@pytest.mark.asyncio
async def test_materialize_mentor_creates_executable_draft(
    async_client: AsyncClient,
) -> None:
    org = await _org(async_client, "P03 Materialize Mentor")
    body = {"brief": "Quiero un mentor de Python con progreso y ejercicios"}
    key = f"mentor-{uuid4().hex}"

    materialized = await _materialize(async_client, org, body, key=key)

    assert materialized["status"] == "READY", materialized
    artifacts = materialized["artifacts"]
    workflow_id = artifacts["workflow"]["id"]
    agent_id = artifacts["agent"]["id"]
    role_id = artifacts["role"]["id"]
    assert artifacts["workflow"]["created"] is True
    assert artifacts["agent"]["created"] is True

    workflow = await async_client.get(
        f"/api/v1/workflows/{workflow_id}", headers=_headers(org)
    )
    assert workflow.status_code == 200, workflow.text
    assert workflow.json()["status"] == "draft"
    llm_nodes = [
        node for node in workflow.json()["graph"]["nodes"] if node["type"] == "llm"
    ]
    assert llm_nodes
    assert all(node["config"].get("agent_id") == agent_id for node in llm_nodes)

    again = await _materialize(async_client, org, body, key=key)
    assert again["artifacts"]["workflow"]["id"] == workflow_id
    assert again["artifacts"]["agent"]["id"] == agent_id
    assert again["artifacts"]["role"]["id"] == role_id
    assert (await _counts(org))["workflows"] == 1
    assert (await _counts(org))["agents"] == 1

    agent = next(
        item
        for item in (
            await async_client.get("/api/v1/agents", headers=_headers(org))
        ).json()["agents"]
        if item["id"] == agent_id
    )
    assert agent["status"] in ("ready", "configured", "deployed")
    linked = await async_client.get(
        f"/api/v1/studio/agents/{agent_id}/role", headers=_headers(org)
    )
    assert linked.status_code == 200, linked.text
    assert linked.json()["role"]["record_id"] == role_id


@pytest.mark.asyncio
async def test_materialized_instance_pins_role_version(
    async_client: AsyncClient,
) -> None:
    org = await _org(async_client, "P05 Pin Role")
    materialized = await _materialize(
        async_client,
        org,
        {"brief": "Quiero un mentor de Python con progreso"},
        key=f"pin-{uuid4().hex}",
    )
    assert materialized["status"] == "READY"
    workflow_id = materialized["artifacts"]["workflow"]["id"]
    role_id = materialized["artifacts"]["role"]["id"]
    started = await async_client.post(
        f"/api/v1/workflows/{workflow_id}/instances",
        headers={**_headers(org), "Idempotency-Key": f"pin-{uuid4().hex}"},
        json={"payload": {"message": "hola"}},
    )
    assert started.status_code == 200, started.text
    snapshot = started.json()["instance"]["definition_snapshot"]
    policy = snapshot.get("policy_snapshot") or {}
    assert policy["agents"]
    assert policy["agents"][0]["role"]["record_id"] == role_id


@pytest.mark.asyncio
async def test_materialize_requires_explicit_confirmation(
    async_client: AsyncClient,
) -> None:
    org = await _org(async_client, "P03 Confirm")
    response = await async_client.post(
        "/api/v1/studio/solutions/materialize",
        headers=_headers(org),
        json={
            "brief": "Quiero un mentor de Python",
            "confirm": False,
            "idempotency_key": f"noconfirm-{uuid4().hex}",
        },
    )
    assert response.status_code == 400
    assert "confirmación" in response.text.lower()


@pytest.mark.asyncio
async def test_sales_without_real_binding_needs_configuration(
    async_client: AsyncClient,
) -> None:
    org = await _org(async_client, "P03 Sales Missing")
    body = {"brief": "Quiero vender arroz de un catálogo Postgres"}
    compiled = await _compile(async_client, org, body)

    assert compiled["template_id"] == "sales_advisor"
    assert compiled["status"] == "NEEDS_CONFIGURATION"
    assert any(item["code"] == "capability_missing" for item in compiled["blockers"])

    materialized = await _materialize(async_client, org, body)
    assert materialized["status"] == "NEEDS_CONFIGURATION"
    assert not materialized["artifacts"].get("workflow")
    assert any(item["code"] == "capability_missing" for item in materialized["blockers"])


@pytest.mark.asyncio
async def test_sales_with_real_binding_materializes_workflow(
    async_client: AsyncClient,
) -> None:
    org = await _org(async_client, "P03 Sales Binding")
    binding = await async_client.put(
        "/api/v1/workflows/capability-bindings/catalog.products.search",
        headers={**_headers(org), "Idempotency-Key": f"binding-{uuid4().hex}"},
        json={
            "provider_kind": "managed_db",
            "config": {"table": "zent_products", "columns": ["sku", "name", "price"], "limit": 5},
        },
    )
    assert binding.status_code == 200, binding.text

    body = {"brief": "Quiero vender arroz de un catálogo Postgres"}
    compiled = await _compile(async_client, org, body)
    assert compiled["status"] == "READY_TO_MATERIALIZE", compiled["blockers"]
    materialized = await _materialize(async_client, org, body)
    assert materialized["status"] == "READY"
    workflow_id = materialized["artifacts"]["workflow"]["id"]
    workflow = await async_client.get(
        f"/api/v1/workflows/{workflow_id}", headers=_headers(org)
    )
    assert any(
        node["type"] == "capability_call"
        for node in workflow.json()["graph"]["nodes"]
    )


@pytest.mark.asyncio
async def test_audit_with_two_sources_materializes_approval_flow(
    async_client: AsyncClient,
) -> None:
    org = await _org(async_client, "P03 Audit Ready")
    kb_ids = []
    for index in range(2):
        kb = await async_client.post(
            "/api/v1/knowledge-bases",
            headers=_headers(org),
            json={"name": f"Fuente auditoría {index} {uuid4().hex[:6]}"},
        )
        assert kb.status_code == 201, kb.text
        kb_ids.append(kb.json()["id"])

    body = {
        "brief": "Quiero auditar dos fuentes y exigir aprobación",
        "source_refs": kb_ids,
    }
    compiled = await _compile(async_client, org, body)
    assert compiled["status"] == "READY_TO_MATERIALIZE", compiled["blockers"]
    materialized = await _materialize(async_client, org, body)
    assert materialized["status"] == "READY"
    workflow_id = materialized["artifacts"]["workflow"]["id"]
    workflow = await async_client.get(
        f"/api/v1/workflows/{workflow_id}", headers=_headers(org)
    )
    types = [node["type"] for node in workflow.json()["graph"]["nodes"]]
    assert types.count("kb_query") == 2
    assert "human_approval" in types


@pytest.mark.asyncio
async def test_audit_requires_two_authorized_sources(
    async_client: AsyncClient,
) -> None:
    org = await _org(async_client, "P03 Audit Sources")
    body = {"brief": "Quiero auditar dos fuentes y exigir aprobación"}
    compiled = await _compile(async_client, org, body)

    assert compiled["template_id"] == "auditor"
    assert compiled["status"] == "NEEDS_CONFIGURATION"
    assert any(item["code"] == "sources_required" for item in compiled["blockers"])

    materialized = await _materialize(async_client, org, body)
    assert materialized["status"] == "NEEDS_CONFIGURATION"
    assert not materialized["artifacts"].get("workflow")


@pytest.mark.asyncio
async def test_tenant_b_cannot_reuse_physical_agent(async_client: AsyncClient) -> None:
    org_a = await _org(async_client, "P03 Tenant A")
    org_b = await _org(async_client, "P03 Tenant B")
    body = {"brief": "Quiero un mentor de Python con progreso"}

    a = await _materialize(async_client, org_a, body, key=f"a-{uuid4().hex}")
    a_agent = a["artifacts"]["agent"]["id"]

    cross = await _compile(
        async_client,
        org_b,
        {**body, "existing_agent_id": a_agent},
    )
    assert any(item["code"] == "agent_unavailable" for item in cross["blockers"])

    b = await _materialize(
        async_client,
        org_b,
        {**body, "existing_agent_id": a_agent},
        key=f"b-{uuid4().hex}",
    )
    if b["artifacts"].get("agent"):
        assert b["artifacts"]["agent"]["id"] != a_agent
    assert b["status"] in ("NEEDS_CONFIGURATION", "READY")


@pytest.mark.asyncio
async def test_rollback_removes_only_new_unused_resources(
    async_client: AsyncClient,
) -> None:
    org = await _org(async_client, "P03 Rollback")
    materialized = await _materialize(
        async_client,
        org,
        {"brief": "Quiero un mentor de Python con progreso"},
        key=f"rollback-{uuid4().hex}",
    )
    solution_id = materialized["solution_id"]
    workflow_id = materialized["artifacts"]["workflow"]["id"]

    rolled = await async_client.post(
        f"/api/v1/studio/solutions/{solution_id}/materialization/rollback",
        headers=_headers(org),
    )
    assert rolled.status_code == 200, rolled.text
    assert "workflow" in rolled.json()["deleted"]

    gone = await async_client.get(
        f"/api/v1/workflows/{workflow_id}", headers=_headers(org)
    )
    assert gone.status_code == 404
    status = await async_client.get(
        f"/api/v1/studio/solutions/{solution_id}/materialization",
        headers=_headers(org),
    )
    assert status.json()["status"] == "ROLLED_BACK"
