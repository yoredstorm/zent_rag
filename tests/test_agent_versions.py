# =============================================================================
# Agent Versions — snapshot/resolve unit + máquina de estados de promoción
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from src.core.domain.entities import Agent, AgentVersion, AgentVersionStatus
from src.platform.deployments.versions import (
    resolve_agent,
    slugify,
    snapshot_agent,
    validate_transition,
)

ORG = UUID("00000000-0000-0000-0000-000000000001")


def _agent(**overrides) -> Agent:
    base = dict(
        id=UUID("10000000-0000-0000-0000-000000000001"),
        organization_id=ORG,
        name="Inventory Assistant",
        system_prompt="Eres un asistente de inventario.",
        tools=["search_knowledge", "query_database"],
        model="gpt-4o-mini",
        config_json={
            "temperature": 0.1,
            "tone": "concise",
            "knowledge_base_ids": [UUID("20000000-0000-0000-0000-000000000001")],
            "limits": {"max_steps": 3},
            "security": {"sql_enabled": True},
            "purpose": "inventario",
        },
    )
    base.update(overrides)
    return Agent(**base)


def test_snapshot_roundtrip_preserves_effective_config() -> None:
    agent = _agent()
    snapshot = snapshot_agent(agent)
    resolved = resolve_agent(agent, snapshot)

    assert resolved.system_prompt == agent.system_prompt
    assert resolved.model == agent.model
    assert resolved.tools == agent.tools
    assert resolved.config_json["temperature"] == 0.1
    assert resolved.config_json["tone"] == "concise"
    assert resolved.config_json["limits"] == {"max_steps": 3}
    assert resolved.config_json["security"] == {"sql_enabled": True}
    assert resolved.config_json["purpose"] == "inventario"
    assert resolved.config_json["knowledge_base_ids"] == [
        "20000000-0000-0000-0000-000000000001"
    ]


def test_snapshot_is_serializable_and_detached() -> None:
    import json

    agent = _agent()
    snapshot = snapshot_agent(agent)
    assert json.loads(json.dumps(snapshot)) == snapshot
    agent.config_json["temperature"] = 0.9
    assert snapshot["config"]["temperature"] == 0.1


def test_resolve_agent_keeps_identity_and_defaults() -> None:
    agent = _agent()
    resolved = resolve_agent(agent, {})
    assert resolved is agent

    resolved2 = resolve_agent(agent, {"system_prompt": "Nuevo prompt"})
    assert resolved2.id == agent.id
    assert resolved2.organization_id == agent.organization_id
    assert resolved2.system_prompt == "Nuevo prompt"
    assert resolved2.tools == agent.tools


def test_snapshot_overrides_prompt_model_tools() -> None:
    agent = _agent()
    snapshot = snapshot_agent(agent)
    snapshot["system_prompt"] = "Prompt v2"
    snapshot["model"] = "gpt-4o"
    snapshot["tools"] = ["search_knowledge"]
    resolved = resolve_agent(agent, snapshot)
    assert resolved.system_prompt == "Prompt v2"
    assert resolved.model == "gpt-4o"
    assert resolved.tools == ["search_knowledge"]


def test_version_transitions() -> None:
    assert validate_transition(AgentVersionStatus.DRAFT, AgentVersionStatus.READY)
    assert validate_transition(AgentVersionStatus.READY, AgentVersionStatus.STAGING)
    assert validate_transition(AgentVersionStatus.READY, AgentVersionStatus.PRODUCTION)
    assert validate_transition(AgentVersionStatus.STAGING, AgentVersionStatus.PRODUCTION)
    assert validate_transition(
        AgentVersionStatus.PRODUCTION, AgentVersionStatus.ARCHIVED
    )
    assert not validate_transition(AgentVersionStatus.DRAFT, AgentVersionStatus.PRODUCTION)
    assert not validate_transition(AgentVersionStatus.DRAFT, AgentVersionStatus.DRAFT)
    assert not validate_transition(AgentVersionStatus.ARCHIVED, AgentVersionStatus.READY)
    assert not validate_transition(AgentVersionStatus.PRODUCTION, AgentVersionStatus.STAGING)


def test_slugify() -> None:
    assert slugify("Inventory Assistant") == "inventory-assistant"
    assert slugify("  Mi  Agente  ") == "mi-agente"
    assert slugify("Agente: v2 (prod)") == "agente-v2-prod"
    assert slugify("!!!") == "agent"


# ---------------------------------------------------------------------------
# Promoción con repo fake (la lógica de estados vive en el servicio)
# ---------------------------------------------------------------------------


class _FakeVersionRepo:
    def __init__(self, versions: list[AgentVersion]) -> None:
        self._versions = versions
        self.promoted: list[tuple[UUID, str]] = []

    async def list_versions(self, organization_id: UUID, agent_id: UUID):
        return list(self._versions)

    async def get_version(self, organization_id: UUID, agent_id: UUID, version_id: UUID):
        return next((v for v in self._versions if v.id == version_id), None)

    async def create_version(self, **kwargs) -> AgentVersion:
        raise NotImplementedError

    async def promote_version(
        self, organization_id: UUID, agent_id: UUID, version_id: UUID, status: str
    ):
        self.promoted.append((version_id, status))
        version = next(v for v in self._versions if v.id == version_id)
        updated = AgentVersion(
            id=version.id,
            organization_id=version.organization_id,
            agent_id=version.agent_id,
            version_number=version.version_number,
            status=AgentVersionStatus(status),
            config_snapshot=version.config_snapshot,
            notes=version.notes,
            created_by=version.created_by,
            created_at=version.created_at,
        )
        self._versions = [updated if v.id == version_id else v for v in self._versions]
        return updated


def _version(n: int, status: AgentVersionStatus) -> AgentVersion:
    return AgentVersion(
        id=UUID(f"30000000-0000-0000-0000-{n:012d}"),
        organization_id=ORG,
        agent_id=UUID("10000000-0000-0000-0000-000000000001"),
        version_number=n,
        status=status,
        config_snapshot={},
    )


@pytest.mark.asyncio
async def test_promote_to_production_demotes_previous_production() -> None:
    from src.platform.deployments.versions import promote_version

    v1 = _version(1, AgentVersionStatus.PRODUCTION)
    v2 = _version(2, AgentVersionStatus.READY)
    repo = _FakeVersionRepo([v1, v2])

    promoted = await promote_version(repo, ORG, v1.agent_id, v2.id, AgentVersionStatus.PRODUCTION)

    assert promoted.status == AgentVersionStatus.PRODUCTION
    assert (v1.id, AgentVersionStatus.READY.value) in repo.promoted
    assert (v2.id, AgentVersionStatus.PRODUCTION.value) in repo.promoted


@pytest.mark.asyncio
async def test_promote_rejects_invalid_transition() -> None:
    from src.platform.deployments.versions import promote_version

    repo = _FakeVersionRepo([_version(1, AgentVersionStatus.DRAFT)])
    with pytest.raises(ValueError, match="Invalid version transition"):
        await promote_version(
        repo, ORG, repo._versions[0].agent_id, repo._versions[0].id, AgentVersionStatus.PRODUCTION
    )


@pytest.mark.asyncio
async def test_promote_unknown_version_raises() -> None:
    from src.platform.deployments.versions import promote_version

    repo = _FakeVersionRepo([_version(1, AgentVersionStatus.DRAFT)])
    with pytest.raises(ValueError, match="not found"):
        await promote_version(
        repo, ORG, repo._versions[0].agent_id, uuid4(), AgentVersionStatus.READY
    )
