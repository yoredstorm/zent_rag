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
    "source_ids",
    "limits",
    "security",
    "retrieval",
    "guardrails",
    "output_schema",
    "chunk_config",
    "embedding_model",
    "provider",
)

#: Claves que un snapshot ejecutable debe declarar explícitamente. Un snapshot
#: certificado incompleto no puede completarse desde el agente vivo: fail closed.
_AGENT_SNAPSHOT_REQUIRED_KEYS = ("system_prompt", "model", "tools")
_AGENT_SNAPSHOT_SCHEMA_VERSION = 2


class AgentSnapshotError(ValueError):
    """Snapshot ausente, incompleto o de un schema no soportado."""

    def __init__(self, issue: str):
        self.issue = issue
        self.code = "agent_snapshot_invalid"
        super().__init__(f"agent snapshot inválido: {issue}")


def snapshot_issues(snapshot: dict | None) -> list[str]:
    """Problemas de completitud/schema sin consultar el agente vivo."""
    if not isinstance(snapshot, dict) or not snapshot:
        return ["empty"]
    issues: list[str] = []
    schema = snapshot.get("schema_version")
    if schema is None:
        issues.append("missing:schema_version")
    elif not isinstance(schema, int) or schema > _AGENT_SNAPSHOT_SCHEMA_VERSION:
        issues.append(f"unsupported:schema_version:{schema}")
    for key in _AGENT_SNAPSHOT_REQUIRED_KEYS:
        if key not in snapshot:
            issues.append(f"missing:{key}")
    if "tools" in snapshot and not isinstance(snapshot.get("tools"), (list, tuple)):
        issues.append("invalid:tools")
    if "system_prompt" in snapshot and snapshot.get("system_prompt") is not None:
        if not isinstance(snapshot.get("system_prompt"), str):
            issues.append("invalid:system_prompt")
    if "model" in snapshot and snapshot.get("model") is not None:
        if not isinstance(snapshot.get("model"), str):
            issues.append("invalid:model")
    return issues


def validate_agent_snapshot(snapshot: dict | None) -> None:
    """Valida un snapshot certificado. Falla cerrado ante duda."""
    issues = snapshot_issues(snapshot)
    if issues:
        raise AgentSnapshotError(",".join(issues))


def snapshot_from_fields(
    *,
    system_prompt: str | None,
    model: str | None,
    tools: list | tuple | None,
    config_json: dict | None,
) -> dict:
    """Construye el snapshot ejecutable desde columnas de `agents`.

    Es la única definición de "configuración del agente" que comparten las
    versiones, las certificaciones de workflow y el pinning de instancias.
    """
    import copy
    import json

    config = copy.deepcopy(config_json or {})
    config = json.loads(json.dumps(config, default=str))
    return {
        "system_prompt": system_prompt,
        "model": model,
        "tools": list(tools or []),
        "config": {k: config.get(k) for k in _SNAPSHOT_CONFIG_KEYS if k in config},
        "config_extra": {k: v for k, v in config.items() if k not in _SNAPSHOT_CONFIG_KEYS},
        "schema_version": 2,
    }


def snapshot_fingerprint(snapshot: dict) -> str:
    import hashlib
    import json

    blob = json.dumps(snapshot or {}, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def execution_fingerprints(snapshot: dict) -> dict[str, str]:
    """Huellas separadas de modelo, tools, fuentes y propósito."""
    import hashlib
    import json

    def _hash(value) -> str:
        blob = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    config = dict(snapshot.get("config") or {})
    extra = dict(snapshot.get("config_extra") or {})
    source_scope = {
        "source_ids": config.get("source_ids") or extra.get("source_ids"),
        "knowledge_base_ids": config.get("knowledge_base_ids")
        or extra.get("knowledge_base_ids"),
    }
    return {
        "config_fingerprint": snapshot_fingerprint(snapshot),
        "model_fingerprint": _hash({"model": snapshot.get("model")}),
        "tools_fingerprint": _hash(snapshot.get("tools") or []),
        "source_scope_fingerprint": _hash(source_scope),
        "purpose_fingerprint": _hash(
            {
                "system_prompt": snapshot.get("system_prompt"),
                "purpose": config.get("purpose") or extra.get("purpose"),
                "instructions": config.get("instructions")
                or extra.get("instructions"),
            }
        ),
    }


def snapshot_agent(agent: Agent) -> dict:
    """Congela la configuración ejecutable de un agente.

    El snapshot es una copia profunda JSON-serializable (UUID → str):
    sistema + prompt + modelo + tools + config relevante. schema_version 2
    incluye retrieval/guardrails/output_schema/chunking/provider/embedding.
    """
    return snapshot_from_fields(
        system_prompt=agent.system_prompt,
        model=agent.model,
        tools=agent.tools,
        config_json=agent.config_json,
    )


def resolve_agent(agent: Agent, snapshot: dict, *, strict: bool = False) -> Agent:
    """Materializa un Agent con los valores del snapshot (compat runtime).

    Semántica de presencia, no de verdad booleana:

    * clave presente con ``[]``/``""``/``None`` → ese es el valor ejecutable;
    * clave ausente → en modo ``strict`` falla cerrado; en modo legacy se
      conserva el valor vivo (compatibilidad con snapshots parciales antiguos).

    Los snapshots de instancias y de versiones publicadas deben resolverse con
    ``strict=True``. El modo legacy existe solo para llamadores históricos y no
    puede usarse para autorizar acciones irreversibles.
    """
    import copy

    if not snapshot:
        return agent
    if strict:
        validate_agent_snapshot(snapshot)

    config = copy.deepcopy(dict(snapshot.get("config") or {}))
    config.update(copy.deepcopy(dict(snapshot.get("config_extra") or {})))

    def _present(key: str, live: object) -> object:
        if key in snapshot:
            return copy.deepcopy(snapshot.get(key))
        if strict:
            raise AgentSnapshotError(f"missing:{key}")
        return live

    system_prompt = _present("system_prompt", agent.system_prompt)
    model = _present("model", agent.model)
    tools_raw = _present("tools", agent.tools)
    if tools_raw is None:
        # schema 2 escribe list(); un null explícito significa "sin tools",
        # nunca "hereda las tools vivas".
        tools = []
    elif isinstance(tools_raw, (list, tuple)):
        tools = [str(item) for item in copy.deepcopy(list(tools_raw))]
    else:
        if strict:
            raise AgentSnapshotError("invalid:tools")
        tools = list(agent.tools or [])

    return Agent(
        id=agent.id,
        organization_id=agent.organization_id,
        name=agent.name,
        project_id=agent.project_id,
        description=agent.description,
        system_prompt=system_prompt if isinstance(system_prompt, str) else None,
        tools=tools,
        model=model if isinstance(model, str) else None,
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
