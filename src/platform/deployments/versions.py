# =============================================================================
# Deployments — Versiones de agentes (snapshot inmutable + resolución)
# =============================================================================
# agent_versions congela prompt/model/tools/config del agente al momento de
# crearse. La ejecución resuelve la configuración desde el snapshot (nunca de
# la fila mutable `agents`) cuando la llamada trae una versión explícita.
# =============================================================================
from __future__ import annotations

import re
from uuid import UUID

from src.core.domain.entities import Agent, AgentVersion, AgentVersionStatus
from src.core.ports import AgentVersionRepository

# Campos de config_json que participan del snapshot (evita duplicar en el
# repo de agentes; el resto de config_json se copia tal cual).
_SNAPSHOT_CONFIG_KEYS = (
    "temperature",
    "tone",
    "knowledge_base_ids",
    "limits",
    "security",
    "retrieval",
    "guardrails",
    "output_schema",
    "chunk_config",
    "embedding_model",
    "provider",
)


def snapshot_agent(agent: Agent) -> dict:
    """Congela la configuración ejecutable de un agente.

    El snapshot es una copia profunda JSON-serializable (UUID → str):
    sistema + prompt + modelo + tools + config relevante. schema_version 2
    incluye retrieval/guardrails/output_schema/chunking/provider/embedding.
    """
    import copy
    import json

    config = copy.deepcopy(agent.config_json or {})
    config = json.loads(json.dumps(config, default=str))
    return {
        "system_prompt": agent.system_prompt,
        "model": agent.model,
        "tools": list(agent.tools or []),
        "config": {k: config.get(k) for k in _SNAPSHOT_CONFIG_KEYS if k in config},
        "config_extra": {k: v for k, v in config.items() if k not in _SNAPSHOT_CONFIG_KEYS},
        "schema_version": 2,
    }


def resolve_agent(agent: Agent, snapshot: dict) -> Agent:
    """Materializa un Agent con los valores del snapshot (compat runtime).

    El runtime recibe un dataclass Agent como siempre: no conoce versiones.
    """
    if not snapshot:
        return agent
    config = dict(snapshot.get("config") or {})
    config.update(snapshot.get("config_extra") or {})
    return Agent(
        id=agent.id,
        organization_id=agent.organization_id,
        name=agent.name,
        project_id=agent.project_id,
        description=agent.description,
        system_prompt=snapshot.get("system_prompt") or agent.system_prompt,
        tools=list(snapshot.get("tools") or agent.tools or []),
        model=snapshot.get("model") or agent.model,
        config_json=config,
        is_active=agent.is_active,
        created_at=agent.created_at,
    )


# Transiciones de estado permitidas del ciclo de vida de una versión.
_VERSION_TRANSITIONS: dict[AgentVersionStatus, set[AgentVersionStatus]] = {
    AgentVersionStatus.DRAFT: {AgentVersionStatus.READY},
    AgentVersionStatus.READY: {AgentVersionStatus.STAGING, AgentVersionStatus.PRODUCTION},
    AgentVersionStatus.STAGING: {AgentVersionStatus.PRODUCTION},
    AgentVersionStatus.PRODUCTION: {AgentVersionStatus.READY, AgentVersionStatus.ARCHIVED},
    AgentVersionStatus.ARCHIVED: set(),
}


def validate_transition(
    current: AgentVersionStatus, target: AgentVersionStatus
) -> bool:
    return target in _VERSION_TRANSITIONS.get(current, set())


async def create_version(
    repo: AgentVersionRepository,
    organization_id: UUID,
    agent: Agent,
    notes: str | None = None,
    created_by: UUID | None = None,
) -> AgentVersion:
    """Snapshot del estado actual del agente como nueva versión draft."""
    return await repo.create_version(
        organization_id=organization_id,
        agent_id=agent.id,
        config_snapshot=snapshot_agent(agent),
        notes=notes,
        created_by=created_by,
    )


async def promote_version(
    repo: AgentVersionRepository,
    organization_id: UUID,
    agent_id: UUID,
    version_id: UUID,
    target: AgentVersionStatus,
) -> AgentVersion:
    """Promueve una versión respetando la máquina de estados.

    Al promover a production, las demás versiones production del mismo agente
    pasan a ready (histórico reusable para rollback).
    """
    version = await repo.get_version(organization_id, agent_id, version_id)
    if version is None:
        raise ValueError(f"Version {version_id} not found")

    current = version.status
    if not validate_transition(current, target):
        raise ValueError(
            f"Invalid version transition: {current.value} -> {target.value}"
        )

    if target == AgentVersionStatus.PRODUCTION:
        for other in await repo.list_versions(organization_id, agent_id):
            if (
                other.id != version_id
                and other.status == AgentVersionStatus.PRODUCTION
            ):
                await repo.promote_version(
                    organization_id, agent_id, other.id, AgentVersionStatus.READY.value
                )

    promoted = await repo.promote_version(
        organization_id, agent_id, version_id, target.value
    )
    if promoted is None:
        raise ValueError(f"Version {version_id} not found")
    return promoted


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(name: str, max_length: int = 48) -> str:
    """Slug legible para deployments (ej: 'inventory-prod')."""
    slug = _SLUG_RE.sub("-", (name or "").lower()).strip("-")
    return slug[:max_length] or "agent"
