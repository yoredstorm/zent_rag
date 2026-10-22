# =============================================================================
# Universal roles — contract, lifecycle, safety, N:M and runtime constraints.
# =============================================================================
from __future__ import annotations

import re
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from src.core.domain.entities import Agent, AgentStatus
from src.platform.studio.contracts import RoleProfileV1, SolutionV1, scan_contract_secrets
from src.platform.studio.policy import capability_decision, effective_permissions
from src.platform.studio.roles import (
    apply_role_to_agent,
    autonomy_allows_tool,
    filter_agent_tools,
    propose_role,
)
from src.platform.studio.templates import list_role_templates, role_template


async def _new_owner_headers(async_client: AsyncClient, name: str) -> dict[str, str]:
    from tests.test_workflows import _create_org, _headers, _owner_session

    org = await _create_org(async_client, f"{name} {uuid4().hex[:6]}")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    return _headers(org)


def _role_payload(template_id: str = "mentor", *, role_id: str | None = None, status: str = "draft"):
    role = role_template(template_id)
    assert role is not None
    payload = role.model_dump(by_alias=True)
    payload["role_id"] = role_id or f"{template_id}_{uuid4().hex[:8]}"
    payload["status"] = status
    return payload


def test_role_contract_accepts_display_name_and_string_tone() -> None:
    payload = _role_payload()
    payload.pop("name")
    payload["display_name"] = "Mentor de producto"
    payload["tone"] = "cercano"
    role = RoleProfileV1.model_validate(payload)
    assert role.name == role.display_name == "Mentor de producto"
    assert role.tone == ["cercano"]


def test_role_contract_rejects_secrets_and_nonportable_ids() -> None:
    payload = _role_payload()
    payload["knowledge_scope"]["notes"] = "postgres://user:pass@db.internal/app"
    with pytest.raises(ValidationError):
        RoleProfileV1.model_validate(payload)

    payload = _role_payload()
    payload["knowledge_scope"]["organization_id"] = str(uuid4())
    with pytest.raises(ValidationError):
        RoleProfileV1.model_validate(payload)

    payload = _role_payload()
    payload["knowledge_scope"]["provider_id"] = "provider-private"
    with pytest.raises(ValidationError):
        RoleProfileV1.model_validate(payload)


def test_wellness_is_not_a_licensed_psychologist() -> None:
    role = role_template("wellness_companion")
    assert role is not None
    assert role.autonomy_level == "answer_only"
    assert role.risk_class == "regulated"
    assert role.safety.no_medical_diagnosis is True
    assert role.safety.no_psychotherapy_claim is True
    assert role.safety.crisis_escalation is True
    assert role.human_handoff.destination == "emergency"
    text = role.model_dump_json().lower()
    assert "psicólogo licenciado" not in text
    assert "psicologo licenciado" not in text


def test_templates_have_no_providers_prices_or_db_schemas() -> None:
    forbidden = re.compile(
        r"openai|anthropic|postgres|mysql|mongodb|redis|CREATE TABLE|\\$\\d|precio de|price"
    )
    for template in list_role_templates():
        dumped = str(template).lower()
        assert not forbidden.search(dumped), template["role_id"]
        assert template["schema"] == "zent.role/v1"


def test_role_capabilities_are_constraints_not_grants() -> None:
    role = role_template("auditor")
    assert role is not None
    # The role allows reading, but the actor still needs the actual permission.
    denied = capability_decision(
        role,
        capability_ref="query_business_data",
        actor_permissions={"agents:read"},
        required_permissions=["admin:sql"],
        read_only=True,
    )
    assert denied.allowed is False
    assert "admin:sql" in denied.reasons[0]

    allowed = capability_decision(
        role,
        capability_ref="query_business_data",
        actor_permissions={"admin:sql"},
        required_permissions=["admin:sql"],
        read_only=True,
    )
    assert allowed.allowed is True
    assert allowed.requires_approval is False

    write_denied = capability_decision(
        role,
        capability_ref="query_business_data",
        actor_permissions={"admin:sql"},
        required_permissions=["admin:sql"],
        read_only=False,
    )
    assert write_denied.allowed is False
    assert "no ejecuta escrituras" in write_denied.reasons[0]

    reversible = role.model_copy(update={"autonomy_level": "execute_reversible"})
    write = capability_decision(
        reversible,
        capability_ref="query_business_data",
        actor_permissions={"admin:sql"},
        required_permissions=["admin:sql"],
        read_only=False,
    )
    assert write.allowed is True
    assert write.requires_approval is True


def test_effective_permissions_are_intersection() -> None:
    assert effective_permissions(
        actor_permissions={"agents:read", "agents:write"},
        service_permissions={"agents:read"},
        tenant_permissions={"agents:read", "knowledge:read"},
    ) == frozenset({"agents:read"})


def test_role_tools_never_add_capability_and_autonomy_narrows() -> None:
    role = role_template("mentor")
    assert role is not None
    payload = role.model_dump(by_alias=True)
    payload["allowed_tools"] = ["search_knowledge", "query_database"]
    payload["autonomy_level"] = "answer_only"
    assert filter_agent_tools(["search_knowledge", "call_api"], payload) == [
        "search_knowledge"
    ]
    assert autonomy_allows_tool("answer_only", "call_api") is False
    assert autonomy_allows_tool("require_approval", "call_api") is False
    assert autonomy_allows_tool("execute_reversible", "call_api") is True

    capability_only = dict(payload)
    capability_only["allowed_tools"] = []
    capability_only["allowed_capabilities"] = ["knowledge_query"]
    assert filter_agent_tools(
        ["search_knowledge", "query_database"], capability_only
    ) == ["search_knowledge"]


def test_apply_role_to_frozen_agent_does_not_mutate_original() -> None:
    role = role_template("tutor")
    assert role is not None
    payload = role.model_dump(by_alias=True)
    payload["allowed_tools"] = ["search_knowledge"]
    agent = Agent(
        id=uuid4(),
        organization_id=uuid4(),
        name="Tutor agent",
        description="",
        system_prompt="",
        tools=["search_knowledge", "call_api"],
        model="test",
        config_json={},
        status=AgentStatus.DEPLOYED,
    )
    narrowed = apply_role_to_agent(agent, payload)
    assert narrowed.tools == ["search_knowledge"]
    assert agent.tools == ["search_knowledge", "call_api"]
    assert narrowed is not agent


def test_solution_contract_supports_nm_composition() -> None:
    payload = {
        "schema": "zent.solution/v1",
        "solution_id": f"mentoring_{uuid4().hex[:6]}",
        "version": "1.0.0",
        "name": "Mentoría y auditoría",
        "roles": [
            {"role_ref": "mentor", "version": "1.0.0"},
            {"role_ref": "auditor", "version": "1.0.0"},
        ],
        "agents": [
            {
                "agent_ref": "mentor_agent",
                "role_ref": "mentor",
                "workflow_refs": ["mentor_flow", "audit_flow"],
            },
            {
                "agent_ref": "auditor_agent",
                "role_ref": "auditor",
                "workflow_refs": ["audit_flow"],
            },
        ],
        "workflows": [
            {
                "workflow_ref": "mentor_flow",
                "role_refs": ["mentor"],
                "agent_refs": ["mentor_agent"],
            },
            {
                "workflow_ref": "audit_flow",
                "role_refs": ["mentor", "auditor"],
                "agent_refs": ["mentor_agent", "auditor_agent"],
            },
        ],
        "capabilities": [{"capability_ref": "knowledge_query"}],
        "knowledge": [{"kind": "knowledge_base", "logical_ref": "mentoring"}],
        "installation": [
            {"order": 1, "action": "review_roles"},
            {"order": 2, "action": "install_capabilities"},
        ],
    }
    solution = SolutionV1.model_validate(payload)
    assert len(solution.agents) == 2
    assert len(solution.workflows) == 2
    # One agent in two workflows, one workflow with two agents.
    assert solution.agents[0].workflow_refs == ["mentor_flow", "audit_flow"]
    assert solution.workflows[1].agent_refs == ["mentor_agent", "auditor_agent"]


@pytest.mark.asyncio
async def test_role_lifecycle_and_cross_tenant(async_client: AsyncClient) -> None:
    tenant_auth = await _new_owner_headers(async_client, "Role Lifecycle")
    role_id = f"mentor_{uuid4().hex[:8]}"
    payload = _role_payload("mentor", role_id=role_id)
    created = await async_client.post(
        "/api/v1/studio/roles", json={"role": payload}, headers=tenant_auth
    )
    assert created.status_code == 201, created.text
    role = created.json()["role"]
    assert role["role_id"] == role_id
    assert role["version"] == "1.0.0"
    assert created.json()["mission_sheet"]["will_not_do"]

    role_uuid = role["record_id"]
    assert role_uuid

    updated_payload = dict(role)
    updated_payload["mission"] = "Acompañar con un plan de práctica medible."
    updated = await async_client.put(
        f"/api/v1/studio/roles/{role_uuid}",
        json={"role": updated_payload},
        headers=tenant_auth,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["role"]["mission"].startswith("Acompañar")
    assert updated.json()["role"]["version"] != "1.0.0"

    versions = await async_client.get(
        f"/api/v1/studio/roles/{role_uuid}/versions", headers=tenant_auth
    )
    assert versions.status_code == 200, versions.text
    assert versions.json()["versions"][0]["revision"] >= 2

    cloned = await async_client.post(
        f"/api/v1/studio/roles/{role_uuid}/clone",
        json={"new_id": f"{role_id}_clone"},
        headers=tenant_auth,
    )
    assert cloned.status_code == 201, cloned.text
    assert cloned.json()["role"]["role_id"] == f"{role_id}_clone"
    assert cloned.json()["role"]["name"].startswith("Copia de")

    exported = await async_client.get(
        f"/api/v1/studio/roles/{role_uuid}/export", headers=tenant_auth
    )
    assert exported.status_code == 200, exported.text
    portable = exported.json()["role"]
    assert portable["schema"] == "zent.role/v1"
    assert "organization_id" not in portable

    second_headers = await _new_owner_headers(async_client, "Other Tenant")
    imported = await async_client.post(
        "/api/v1/studio/roles/import", json=portable, headers=second_headers
    )
    assert imported.status_code == 201, imported.text
    assert imported.json()["role"]["role_id"] == role_id

    hidden = await async_client.get(
        f"/api/v1/studio/roles/{role_uuid}", headers=second_headers
    )
    assert hidden.status_code == 404


@pytest.mark.asyncio
async def test_api_accepts_envelope_and_raw_portable_payload(
    async_client: AsyncClient,
) -> None:
    auth = await _new_owner_headers(async_client, "Raw Payload")
    payload = _role_payload("tutor", role_id=f"raw_{uuid4().hex[:8]}")
    response = await async_client.post("/api/v1/studio/roles", json=payload, headers=auth)
    assert response.status_code == 201, response.text
    assert response.json()["role"]["role_id"] == payload["role_id"]


@pytest.mark.asyncio
async def test_solution_lifecycle_and_install_plan(async_client: AsyncClient) -> None:
    tenant_auth = await _new_owner_headers(async_client, "Solution Lifecycle")
    solution_id = f"solution_{uuid4().hex[:8]}"
    payload = {
        "schema": "zent.solution/v1",
        "solution_id": solution_id,
        "version": "1.0.0",
        "name": "Mentoría y auditoría",
        "roles": [{"role_ref": "mentor"}, {"role_ref": "auditor"}],
        "agents": [
            {
                "agent_ref": "mentor_agent",
                "role_ref": "mentor",
                "workflow_refs": ["mentor_flow", "audit_flow"],
            },
            {
                "agent_ref": "auditor_agent",
                "role_ref": "auditor",
                "workflow_refs": ["audit_flow"],
            },
        ],
        "workflows": [
            {
                "workflow_ref": "mentor_flow",
                "role_refs": ["mentor"],
                "agent_refs": ["mentor_agent"],
            },
            {
                "workflow_ref": "audit_flow",
                "role_refs": ["mentor", "auditor"],
                "agent_refs": ["mentor_agent", "auditor_agent"],
            },
        ],
        "capabilities": [{"capability_ref": "knowledge_query", "purpose": "evidencia"}],
        "requirements": ["knowledge_base", "human_review"],
        "installation": [{"order": 1, "action": "review_roles"}],
    }
    created = await async_client.post(
        "/api/v1/studio/solutions", json={"solution": payload}, headers=tenant_auth
    )
    assert created.status_code == 201, created.text
    solution = created.json()["solution"]
    assert solution["solution_id"] == solution_id

    listed = await async_client.get("/api/v1/studio/solutions", headers=tenant_auth)
    assert listed.status_code == 200, listed.text
    assert any(item["solution_id"] == solution_id for item in listed.json()["solutions"])

    solution_uuid = next(
        item["record_id"]
        for item in listed.json()["solutions"]
        if item["solution_id"] == solution_id
    )
    plan = await async_client.get(
        f"/api/v1/studio/solutions/{solution_uuid}/install-plan", headers=tenant_auth
    )
    assert plan.status_code == 200, plan.text
    body = plan.json()
    assert body["workflows"][1]["agent_refs"] == ["mentor_agent", "auditor_agent"]
    assert body["agents"][0]["workflow_refs"] == ["mentor_flow", "audit_flow"]
    assert body["installation"][0]["action"] == "review_roles"

    changed = dict(solution)
    changed["name"] = "Mentoría y auditoría v2"
    updated = await async_client.put(
        f"/api/v1/studio/solutions/{solution_uuid}",
        json={"solution": changed},
        headers=tenant_auth,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["solution"]["name"] == "Mentoría y auditoría v2"
    assert updated.json()["solution"]["version"] != "1.0.0"
    old_snapshot = await async_client.get(
        f"/api/v1/studio/solutions/{solution_uuid}/versions/1", headers=tenant_auth
    )
    assert old_snapshot.status_code == 200, old_snapshot.text
    assert old_snapshot.json()["solution"]["name"] == "Mentoría y auditoría"

    cloned = await async_client.post(
        f"/api/v1/studio/solutions/{solution_uuid}/clone",
        json={"new_id": f"{solution_id}_clone"},
        headers=tenant_auth,
    )
    assert cloned.status_code == 201, cloned.text
    assert cloned.json()["solution"]["solution_id"] == f"{solution_id}_clone"

    exported = await async_client.get(
        f"/api/v1/studio/solutions/{solution_uuid}/export", headers=tenant_auth
    )
    assert exported.status_code == 200, exported.text
    portable = exported.json()["solution"]
    assert portable["schema"] == "zent.solution/v1"
    assert "record_id" not in portable

    second_headers = await _new_owner_headers(async_client, "Solution Tenant B")
    imported = await async_client.post(
        "/api/v1/studio/solutions/import", json=portable, headers=second_headers
    )
    assert imported.status_code == 201, imported.text
    hidden = await async_client.get(
        f"/api/v1/studio/solutions/{solution_uuid}", headers=second_headers
    )
    assert hidden.status_code == 404


@pytest.mark.asyncio
async def test_version_snapshot_does_not_mutate_after_update(
    async_client: AsyncClient,
) -> None:
    tenant_auth = await _new_owner_headers(async_client, "Version Snapshot")
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    role_id = f"snapshot_{uuid4().hex[:8]}"
    payload = _role_payload("mentor", role_id=role_id)
    created = await async_client.post(
        "/api/v1/studio/roles", json={"role": payload}, headers=tenant_auth
    )
    assert created.status_code == 201, created.text
    role = created.json()["role"]
    role_uuid = role["record_id"]

    session = await get_async_session()
    try:
        before = (
            await session.execute(
                text(
                    "SELECT snapshot FROM role_profile_versions "
                    "WHERE role_profile_id = :rid AND revision = 1"
                ),
                {"rid": role_uuid},
            )
        ).fetchone()
    finally:
        await session.close()
    assert before is not None

    changed = dict(role)
    changed["mission"] = "Misión nueva que no debe reescribir la historia."
    response = await async_client.put(
        f"/api/v1/studio/roles/{role_uuid}",
        json={"role": changed},
        headers=tenant_auth,
    )
    assert response.status_code == 200, response.text

    session = await get_async_session()
    try:
        after = (
            await session.execute(
                text(
                    "SELECT snapshot FROM role_profile_versions "
                    "WHERE role_profile_id = :rid AND revision = 1"
                ),
                {"rid": role_uuid},
            )
        ).fetchone()
    finally:
        await session.close()
    assert after is not None
    assert before.snapshot == after.snapshot
    assert before.snapshot["mission"] != changed["mission"]

    snapshot_response = await async_client.get(
        f"/api/v1/studio/roles/{role_uuid}/versions/1", headers=tenant_auth
    )
    assert snapshot_response.status_code == 200, snapshot_response.text
    assert snapshot_response.json()["role"]["mission"] == role["mission"]


@pytest.mark.asyncio
async def test_proposal_is_editable_draft_for_new_user() -> None:
    proposal = await propose_role("Quiero un mentor para práctica profesional")
    assert proposal["requires_review"] is True
    assert proposal["publishable"] is False
    assert proposal["role"]["status"] == "draft"
    assert proposal["mission_sheet"]["will_do"]
    assert proposal["mission_sheet"]["will_not_do"]
    assert proposal["workflow_proposal"]["draft_only"] is True
    assert proposal["workflow_proposal"]["design_steps"]


def test_scan_security_flags_connection_strings() -> None:
    assert scan_contract_secrets({"notes": "redis://cache:6379/0"})
    assert not scan_contract_secrets({"notes": "usa la base autorizada"})


@pytest.mark.asyncio
async def test_session_kinds_are_resolved_separately(async_client: AsyncClient) -> None:
    auth = await _new_owner_headers(async_client, "Session Kinds")
    for kind in ("conversation", "design", "workflow_instance"):
        response = await async_client.post(
            "/api/v1/studio/sessions/resolve",
            json={"session_id": str(uuid4()), "kind": kind},
            headers={**auth, "Idempotency-Key": f"session-{uuid4().hex}"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["kind"] == kind
        assert body["schema"] == "zent.session.ref/v1"
        assert body["exists"] is False


@pytest.mark.asyncio
async def test_agent_and_workflows_support_nm_without_new_registry(
    async_client: AsyncClient,
) -> None:
    from tests.test_workflow_agent_context import _edge, _FakeRuntime, _graph, _node, _run
    from tests.test_workflows import _create_org, _headers, _owner_session

    org = await _create_org(async_client, f"N:M {uuid4().hex[:6]}")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    first = await async_client.post(
        "/api/v1/agents",
        headers=_headers(org),
        json={"name": f"Agent A {uuid4().hex[:6]}", "system_prompt": "A", "tools": []},
    )
    second = await async_client.post(
        "/api/v1/agents",
        headers=_headers(org),
        json={"name": f"Agent B {uuid4().hex[:6]}", "system_prompt": "B", "tools": []},
    )
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    agent_a = first.json()["id"]
    agent_b = second.json()["id"]

    runtime_a = _FakeRuntime(answer="workflow-one")
    graph_one = _graph(
        [
            _node("t", "trigger_webhook"),
            _node("ask", "llm", {"agent_id": agent_a, "prompt": "uno"}),
        ],
        [_edge("e1", "t", "ask")],
        ["t"],
    )
    body_one, _ = await _run(async_client, org, graph_one, runtime=runtime_a)
    assert body_one["status"] in ("simulated", "succeeded"), body_one

    runtime_b = _FakeRuntime(answer="workflow-two")
    graph_two = _graph(
        [
            _node("t", "trigger_webhook"),
            _node("ask_a", "llm", {"agent_id": agent_a, "prompt": "dos-a"}),
            _node("ask_b", "llm", {"agent_id": agent_b, "prompt": "dos-b"}),
        ],
        [
            _edge("e1", "t", "ask_a"),
            _edge("e2", "ask_a", "ask_b"),
        ],
        ["t"],
    )
    body_two, _ = await _run(async_client, org, graph_two, runtime=runtime_b)
    assert body_two["status"] in ("simulated", "succeeded"), body_two
    assert len(runtime_b.requests) == 2
    assert {request.agent.id for request in runtime_b.requests} == {
        UUID(agent_a),
        UUID(agent_b),
    }


@pytest.mark.asyncio
async def test_runtime_narrows_agent_tools_from_role(async_client: AsyncClient) -> None:
    """The same Agent/workflow runtime receives only tools allowed by the role."""
    from tests.test_workflow_agent_context import _edge, _FakeRuntime, _graph, _node, _run
    from tests.test_workflows import _create_org, _headers, _owner_session

    org = await _create_org(async_client, f"Role Runtime {uuid4().hex[:6]}")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    agent = await async_client.post(
        "/api/v1/agents",
        headers=_headers(org),
        json={
            "name": f"Role bound {uuid4().hex[:6]}",
            "system_prompt": "responde",
            "tools": ["search_knowledge", "call_api"],
        },
    )
    assert agent.status_code == 201, agent.text
    agent_id = agent.json()["id"]

    role_payload = _role_payload(
        "tutor", role_id=f"runtime_{uuid4().hex[:8]}", status="active"
    )
    role_payload["allowed_tools"] = ["search_knowledge"]
    role_payload["autonomy_level"] = "propose_actions"
    created = await async_client.post(
        "/api/v1/studio/roles", json={"role": role_payload}, headers=_headers(org)
    )
    assert created.status_code == 201, created.text
    role_uuid = created.json()["role"]["record_id"]
    linked = await async_client.post(
        f"/api/v1/studio/agents/{agent_id}/role",
        json={"role_profile_id": role_uuid},
        headers=_headers(org),
    )
    assert linked.status_code == 200, linked.text

    runtime = _FakeRuntime()
    graph = _graph(
        [
            _node("t", "trigger_webhook"),
            _node("ask", "llm", {"agent_id": agent_id, "prompt": "Analiza"}),
        ],
        [_edge("e1", "t", "ask")],
        ["t"],
    )
    body, _ = await _run(async_client, org, graph, runtime=runtime)
    assert body["status"] in ("simulated", "succeeded"), body
    assert runtime.requests
    assert runtime.requests[0].agent.tools == ["search_knowledge"]
