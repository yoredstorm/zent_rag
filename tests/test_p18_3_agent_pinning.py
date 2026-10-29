# =============================================================================
# P18.3-09 - Snapshot inmutable del agente en workflows durables
# =============================================================================
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.infrastructure.postgres.relational_db import (
    PostgresAgentRepository,
    PostgresOrganizationRepository,
    PostgresWorkspaceRepository,
)
from src.platform.deployments.versions import (
    execution_fingerprints,
    snapshot_agent,
)
from src.platform.workflows.definition import (
    PublishedDefinitionError,
    load_published_definition,
    trigger_fingerprint,
)
from src.platform.workflows.instances import InstanceRef, _build_policy_snapshot
from src.platform.workflows.release_policy import agent_versions_stale, graph_fingerprint


def _graph(agent_id) -> dict:
    return {
        "nodes": [
            {
                "id": "llm-1",
                "type": "llm",
                "label": "Responder",
                "config": {"agent_id": str(agent_id), "prompt": "hola"},
            }
        ],
        "edges": [],
    }


@pytest.mark.asyncio
async def test_instance_snapshot_freezes_agent_config_and_fingerprint() -> None:
    org = await PostgresOrganizationRepository().create_organization(
        uuid4(), f"P18.3 Pin {uuid4().hex[:6]}"
    )
    repo = PostgresAgentRepository()
    agent = await repo.create_agent(
        org.id,
        f"Agente A {uuid4().hex[:6]}",
        system_prompt="Responde como narrador infantil.",
        tools=["knowledge_search"],
        model="model-a",
        config_json={"temperature": 0.1, "source_ids": ["s1"]},
    )
    try:
        snapshot = await _build_policy_snapshot(org.id, _graph(agent.id))
        entry = snapshot["agents"][0]
        assert snapshot["schema_version"] == 2
        assert entry["agent_id"] == str(agent.id)
        assert entry["config_snapshot"]["system_prompt"].startswith("Responde como narrador")
        assert entry["config_snapshot"]["model"] == "model-a"
        assert entry["config_fingerprint"] == execution_fingerprints(
            snapshot_agent(agent)
        )["config_fingerprint"]
        assert entry["model_fingerprint"]
        assert entry["tools_fingerprint"]
        assert entry["source_scope_fingerprint"]
        assert entry["purpose_fingerprint"]
    finally:
        await _cleanup_org(org.id)


@pytest.mark.asyncio
async def test_llm_node_executes_pinned_agent_not_live_edit(monkeypatch) -> None:
    from src.api import deps
    from src.platform.workflows import context_service, nodes
    from src.platform.workflows.ir import WorkflowNode
    from src.platform.workflows.runtime import ExecutionContext

    org = await PostgresOrganizationRepository().create_organization(
        uuid4(), f"P18.3 Pin Run {uuid4().hex[:6]}"
    )
    repo = PostgresAgentRepository()
    agent = await repo.create_agent(
        org.id,
        f"Narrador A {uuid4().hex[:6]}",
        system_prompt="PROMPT_A: narrador infantil.",
        tools=[],
        model="model-a",
        config_json={"temperature": 0.2},
    )
    try:
        snapshot = await _build_policy_snapshot(org.id, _graph(agent.id))
        entry = snapshot["agents"][0]
        instance = InstanceRef(
            id=uuid4(),
            organization_id=org.id,
            workspace_id=None,
            status="RUNNING",
            conversation_id=None,
            state={},
            policy_snapshot=snapshot,
        )

        # Edición posterior en Agent Studio: B reemplaza la fila viva.
        await repo.update_agent(
            org.id,
            agent.id,
            system_prompt="PROMPT_B: analista técnico.",
            model="model-b",
        )
        live = await repo.get_agent(org.id, agent.id)
        assert live is not None
        live_fingerprint = execution_fingerprints(snapshot_agent(live))[
            "config_fingerprint"
        ]
        assert live_fingerprint != entry["config_fingerprint"]

        captured: dict[str, str] = {}

        class Runtime:
            async def run(self, request):
                captured["system_prompt"] = request.agent.system_prompt or ""
                captured["model"] = request.agent.model or ""
                return SimpleNamespace(
                    answer="respuesta",
                    message="respuesta",
                    model=request.agent.model,
                    cost=0.0,
                    status="completed",
                )

        monkeypatch.setattr(deps, "get_agent_repo", lambda: repo)
        monkeypatch.setattr(deps, "get_agent_runtime", lambda: Runtime())
        monkeypatch.setattr(
            nodes,
            "_agent_context_payload",
            lambda _rctx: _async_none(),
        )
        monkeypatch.setattr(nodes, "_org_config_json", lambda _oid: _async_empty())
        monkeypatch.setattr(
            context_service,
            "assemble_memory_context",
            lambda **_kwargs: _async_memory(),
        )

        execution = ExecutionContext(
            organization_id=org.id,
            workflow_id=uuid4(),
            run_id=uuid4(),
            actor_type="user",
            trigger_type="manual",
            permissions=frozenset({"agents:execute"}),
            actor_id=uuid4(),
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
        assert captured["system_prompt"].startswith("PROMPT_A")
        assert captured["model"] == "model-a"
        assert outcome.output["agent_id"] == str(agent.id)
    finally:
        await _cleanup_org(org.id)


@pytest.mark.asyncio
async def test_published_definition_rejects_agent_edited_after_certification() -> None:
    import json
    from datetime import datetime, timezone

    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session
    from src.platform.workflows.release_policy import _agent_fingerprint

    org = await PostgresOrganizationRepository().create_organization(
        uuid4(), f"P18.3 Cert Drift {uuid4().hex[:6]}"
    )
    workspace = await PostgresWorkspaceRepository().create_workspace(
        org.id, "Cert", f"cert-{uuid4().hex[:8]}"
    )
    repo = PostgresAgentRepository()
    agent = await repo.create_agent(
        org.id,
        f"Agente certificado {uuid4().hex[:6]}",
        system_prompt="PROMPT_CERTIFICADO",
        model="model-a",
        config_json={"temperature": 0.1},
        workspace_id=workspace.id,
    )
    graph = _graph(agent.id)
    graph_hash = graph_fingerprint(graph)
    trigger_hash = trigger_fingerprint("manual", {})
    certified_agents, roles, missing = await _agent_fingerprint(org.id, graph)
    assert not missing
    workflow_id = uuid4()
    version_id = uuid4()
    certificate_id = uuid4()
    try:
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    "INSERT INTO workflows "
                    "(id, organization_id, workspace_id, name, trigger_type, trigger_config, "
                    " steps, status, editor_state, graph, workflow_version, graph_source) "
                    "VALUES (:wid, :oid, :ws, 'P18.3 cert', 'manual', '{}'::jsonb, "
                    "'[]'::jsonb, 'active', '{}'::jsonb, CAST(:graph AS jsonb), 1, 'graph')"
                ),
                {
                    "wid": str(workflow_id),
                    "oid": str(org.id),
                    "ws": str(workspace.id),
                    "graph": json.dumps(graph),
                },
            )
            snapshot = {
                "name": "P18.3 cert",
                "graph": graph,
                "steps": [],
                "trigger_type": "manual",
                "trigger_config": {},
                "workflow_version": 1,
            }
            await session.execute(
                text(
                    "INSERT INTO workflow_versions "
                    "(id, organization_id, workflow_id, version_number, status, "
                    " config_snapshot, certificate_id, workspace_id, graph_hash, "
                    " trigger_hash, policy_version, published_at) "
                    "VALUES (:vid, :oid, :wid, 1, 'production', CAST(:snap AS jsonb), "
                    ":cid, :ws, :ghash, :thash, 'v1', now())"
                ),
                {
                    "vid": str(version_id),
                    "oid": str(org.id),
                    "wid": str(workflow_id),
                    "snap": json.dumps(snapshot),
                    "cid": str(certificate_id),
                    "ws": str(workspace.id),
                    "ghash": graph_hash,
                    "thash": trigger_hash,
                },
            )
            await session.execute(
                text(
                    "INSERT INTO workflow_certificates "
                    "(id, organization_id, workspace_id, workflow_id, workflow_version, "
                    " risk_class, level, state, graph_hash, agent_versions, role_versions, "
                    " policy_version, trigger_hash, issued_at) "
                    "VALUES (:cid, :oid, :ws, :wid, 1, 'normal', 'L2', 'issued', "
                    ":ghash, CAST(:agents AS jsonb), CAST(:roles AS jsonb), 'v1', "
                    ":thash, :issued)"
                ),
                {
                    "cid": str(certificate_id),
                    "oid": str(org.id),
                    "ws": str(workspace.id),
                    "wid": str(workflow_id),
                    "ghash": graph_hash,
                    "agents": json.dumps(certified_agents),
                    "roles": json.dumps(roles),
                    "thash": trigger_hash,
                    "issued": datetime.now(timezone.utc),
                },
            )
            await session.execute(
                text(
                    "UPDATE workflows SET published_version_id = :vid, "
                    "published_certificate_id = :cid, published_graph_hash = :ghash, "
                    "published_at = now() WHERE id = :wid"
                ),
                {
                    "vid": str(version_id),
                    "cid": str(certificate_id),
                    "ghash": graph_hash,
                    "wid": str(workflow_id),
                },
            )
            await session.commit()
        finally:
            await session.close()

        definition = await load_published_definition(org.id, workflow_id)
        assert definition["version_id"] == str(version_id)

        await repo.update_agent(
            org.id,
            agent.id,
            system_prompt="PROMPT_EDITADO_DESPUES_DE_PUBLICAR",
            model="model-b",
        )
        with pytest.raises(PublishedDefinitionError) as exc:
            await load_published_definition(org.id, workflow_id)
        assert exc.value.code == "agents_stale"
    finally:
        await _cleanup_org(org.id)


def test_certificate_detects_config_drift_but_legacy_certificate_is_not_overclaimed() -> None:
    certified = {
        "schema_version": 2,
        "agents": [
            {
                "agent_id": "a1",
                "version": 1,
                "config_fingerprint": "aaa",
                "model_fingerprint": "mmm",
            }
        ],
    }
    current = {
        "schema_version": 2,
        "agents": [
            {
                "agent_id": "a1",
                "version": 1,
                "config_fingerprint": "bbb",
                "model_fingerprint": "mmm",
            }
        ],
    }
    assert agent_versions_stale(certified, current) is True
    assert agent_versions_stale(certified, certified) is False

    legacy = {"agents": [{"agent_id": "a1", "version": 1}]}
    assert agent_versions_stale(legacy, current) is False


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
