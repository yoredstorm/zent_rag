# =============================================================================
# P18.5-01 — Snapshot de agente: presencia, hash y fail-closed.
# =============================================================================
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.core.domain.entities import Agent
from src.platform.deployments.versions import (
    AgentSnapshotError,
    resolve_agent,
    snapshot_from_fields,
    validate_agent_snapshot,
)


def _agent(**overrides) -> Agent:
    base = dict(
        id=uuid4(),
        organization_id=uuid4(),
        name="Agente P18.5",
        system_prompt="PROMPT_VIVO",
        tools=["api_call"],
        model="model-live",
        config_json={"temperature": 0.9},
    )
    base.update(overrides)
    return Agent(**base)


def _snapshot(**overrides) -> dict:
    data = {
        "schema_version": 2,
        "system_prompt": "",
        "model": "model-pinned",
        "tools": [],
        "config": {"temperature": 0.1},
        "config_extra": {},
    }
    data.update(overrides)
    return data


def test_resolve_agent_uses_presence_not_truthiness() -> None:
    live = _agent()
    resolved = resolve_agent(live, _snapshot(), strict=True)
    assert resolved.tools == []
    assert resolved.system_prompt == ""
    assert resolved.model == "model-pinned"
    assert resolved.config_json["temperature"] == 0.1
    # El agente vivo no se muta.
    assert live.tools == ["api_call"]
    assert live.system_prompt == "PROMPT_VIVO"


def test_resolve_agent_strict_rejects_incomplete_snapshot() -> None:
    live = _agent()
    with pytest.raises(AgentSnapshotError):
        resolve_agent(live, {"system_prompt": "solo prompt"}, strict=True)
    with pytest.raises(AgentSnapshotError):
        validate_agent_snapshot({"schema_version": 99, "tools": []})


def test_legacy_partial_resolution_still_narrows_by_presence() -> None:
    live = _agent()
    resolved = resolve_agent(live, {"system_prompt": "nuevo"})
    assert resolved.system_prompt == "nuevo"
    assert resolved.tools == ["api_call"]  # clave ausente: compat legacy
    # tools presente vacío ya no hereda, incluso sin strict.
    assert resolve_agent(live, {"tools": []}).tools == []


def test_snapshot_from_fields_deep_copies_and_keeps_empty() -> None:
    snapshot = snapshot_from_fields(
        system_prompt="",
        model="m",
        tools=[],
        config_json={"source_ids": [], "temperature": 0.2},
    )
    assert snapshot["tools"] == []
    assert snapshot["system_prompt"] == ""
    assert snapshot["config"]["source_ids"] == []
    assert snapshot["schema_version"] == 2


@pytest.mark.asyncio
async def test_instance_llm_ignores_live_expansion(monkeypatch) -> None:
    from src.api import deps
    from src.infrastructure.postgres.relational_db import (
        PostgresAgentRepository,
        PostgresOrganizationRepository,
    )
    from src.platform.workflows import context_service, nodes
    from src.platform.workflows.instances import InstanceRef, _build_policy_snapshot
    from src.platform.workflows.ir import WorkflowNode
    from src.platform.workflows.runtime import ExecutionContext

    org = await PostgresOrganizationRepository().create_organization(
        uuid4(), f"P18.5 snap {uuid4().hex[:6]}"
    )
    repo = PostgresAgentRepository()
    agent = await repo.create_agent(
        org.id,
        f"Agente pin {uuid4().hex[:6]}",
        system_prompt="PROMPT_CERTIFICADO",
        tools=[],
        model="model-a",
        config_json={"temperature": 0.1},
    )
    graph = {
        "nodes": [
            {
                "id": "llm-1",
                "type": "llm",
                "label": "Responder",
                "config": {"agent_id": str(agent.id), "prompt": "hola"},
            }
        ],
        "edges": [],
    }
    try:
        pinned = await _build_policy_snapshot(org.id, graph)
        entry = pinned["agents"][0]
        assert entry["config_snapshot"]["tools"] == []
        assert "agent_version_id" in entry

        # La fila viva se amplía después de iniciar la instancia.
        await repo.update_agent(
            org.id,
            agent.id,
            system_prompt="PROMPT_VIVO_AMPLIADO",
            model="model-live",
        )
        live = await repo.get_agent(org.id, agent.id)
        assert live is not None
        # update_agent no acepta tools en este repo; se fuerza por SQL directo.
        from sqlalchemy import text

        from src.infrastructure.postgres.session import get_async_session

        session = await get_async_session()
        try:
            await session.execute(
                text("UPDATE agents SET tools = CAST(:tools AS jsonb) WHERE id = :aid"),
                {"tools": '["api_call"]', "aid": str(agent.id)},
            )
            await session.commit()
        finally:
            await session.close()

        captured: dict[str, object] = {}

        class Runtime:
            async def run(self, request):
                captured["tools"] = list(request.agent.tools or [])
                captured["system_prompt"] = request.agent.system_prompt
                return SimpleNamespace(
                    answer="ok",
                    message="ok",
                    model=request.agent.model,
                    cost=0.0,
                    status="completed",
                )

        monkeypatch.setattr(deps, "get_agent_repo", lambda: repo)
        monkeypatch.setattr(deps, "get_agent_runtime", lambda: Runtime())
        monkeypatch.setattr(nodes, "_agent_context_payload", lambda _rctx: _async_none())
        monkeypatch.setattr(nodes, "_org_config_json", lambda _oid: _async_empty())
        monkeypatch.setattr(
            context_service,
            "assemble_memory_context",
            lambda **_kwargs: _async_memory(),
        )

        instance = InstanceRef(
            id=uuid4(),
            organization_id=org.id,
            workspace_id=None,
            status="RUNNING",
            conversation_id=None,
            state={},
            policy_snapshot=pinned,
        )
        execution = ExecutionContext(
            organization_id=org.id,
            workflow_id=uuid4(),
            run_id=uuid4(),
            actor_type="user",
            trigger_type="manual",
            permissions=frozenset({"agents:execute"}),
            actor_id=uuid4(),
            instance_id=instance.id,
            definition_source="instance",
        )
        rctx = nodes.NodeContext(
            execution=execution,
            node=WorkflowNode(
                id="llm-1",
                type="llm",
                label="Responder",
                config={"agent_id": str(agent.id), "prompt": "Cuéntame"},
            ),
            node_type=nodes.NodeTypeDef(
                node_type="llm",
                version=1,
                label="Responder",
                category="ai",
                risk_level="normal",
                capabilities=frozenset(),
            ),
            node_id="llm-1",
            inputs={},
            trigger={},
            payload={},
            variables={},
            node_outputs={},
            idempotency_key=None,
            instance=instance,
        )
        outcome = await nodes._exec_llm(rctx)
        assert outcome.error is None, outcome.error
        assert captured["tools"] == []
        assert captured["system_prompt"] == "PROMPT_CERTIFICADO"
        assert outcome.output["agent_snapshot_status"] == "PINNED_INSTANCE"
        assert outcome.output["agent_version_id"] == entry["agent_version_id"]
    finally:
        await _cleanup_org(org.id)


@pytest.mark.asyncio
async def test_instance_llm_blocks_when_snapshot_missing(monkeypatch) -> None:
    from src.infrastructure.postgres.relational_db import (
        PostgresAgentRepository,
        PostgresOrganizationRepository,
    )
    from src.platform.workflows import nodes
    from src.platform.workflows.instances import InstanceRef
    from src.platform.workflows.ir import WorkflowNode
    from src.platform.workflows.runtime import ExecutionContext

    org = await PostgresOrganizationRepository().create_organization(
        uuid4(), f"P18.5 legacy {uuid4().hex[:6]}"
    )
    repo = PostgresAgentRepository()
    agent = await repo.create_agent(
        org.id,
        f"Agente legacy {uuid4().hex[:6]}",
        system_prompt="PROMPT",
        tools=["api_call"],
        model="model-a",
    )
    try:
        instance = InstanceRef(
            id=uuid4(),
            organization_id=org.id,
            workspace_id=None,
            status="RUNNING",
            conversation_id=None,
            state={},
            policy_snapshot={},
        )
        rctx = nodes.NodeContext(
            execution=ExecutionContext(
                organization_id=org.id,
                workflow_id=uuid4(),
                run_id=uuid4(),
                actor_type="user",
                trigger_type="manual",
                permissions=frozenset({"agents:execute"}),
                instance_id=instance.id,
                definition_source="instance",
            ),
            node=WorkflowNode(
                id="llm-1",
                type="llm",
                label="Responder",
                config={"agent_id": str(agent.id), "prompt": "hola"},
            ),
            node_type=nodes.NodeTypeDef(
                node_type="llm",
                version=1,
                label="Responder",
                category="ai",
                risk_level="normal",
                capabilities=frozenset(),
            ),
            node_id="llm-1",
            inputs={},
            trigger={},
            payload={},
            variables={},
            node_outputs={},
            idempotency_key=None,
            instance=instance,
        )
        outcome = await nodes._exec_llm(rctx)
        assert outcome.error is not None
        assert "agent_snapshot_missing" in outcome.error
        assert outcome.output["agent_snapshot_status"] == "UNCERTIFIED_LEGACY"
    finally:
        await _cleanup_org(org.id)


async def _async_none():
    return (None, False, None, ())


async def _async_empty():
    return {}


async def _async_memory():
    return SimpleNamespace(items=[], payload={}, summary=lambda: {})


async def _cleanup_org(org_id) -> None:
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        await session.execute(
            text("DELETE FROM organizations WHERE id = :oid"), {"oid": str(org_id)}
        )
        await session.commit()
    finally:
        await session.close()
