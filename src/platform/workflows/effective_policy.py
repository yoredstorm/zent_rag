# =============================================================================
# EffectiveExecutionPolicy — autoridad serializable de una ejecución.
# Se resuelve en servidor desde entidades persistidas; nunca desde payload,
# metadata del LLM o body del cliente.
# =============================================================================
from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from src.infrastructure.postgres.session import get_async_session
from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)

POLICY_SCHEMA_VERSION = "1"
AUTONOMY_RANK = {
    "answer_only": 0,
    "propose_actions": 1,
    "require_approval": 2,
    "execute_reversible": 3,
    "execute_irreversible": 4,
}
_SAFE_INTERNAL_NODES = frozenset(
    {
        "trigger_webhook",
        "trigger_schedule",
        "trigger_event",
        "trigger_manual",
        "condition",
        "condition_branch",
        "router",
        "join",
        "merge",
        "end",
        "wait_event",
        "human_approval",
        "loop",
        "for_each",
        "set_variable",
        "state_set",
        "state_merge",
        "state_append",
        "state_remove",
        "transform",
        "delay",
    }
)


class EffectiveExecutionPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = POLICY_SCHEMA_VERSION
    organization_id: str
    workspace_id: str | None = None
    workflow_id: str
    solution_id: str | None = None
    actor_id: str | None = None
    actor_type: str = "system"
    rbac_scopes: frozenset[str] = frozenset()
    capability_scope: frozenset[str] = frozenset()
    role_bindings: dict[str, Any] = Field(default_factory=dict)
    agents: list[dict[str, Any]] = Field(default_factory=list)
    installed_bindings_hash: str = ""
    autonomy_max: str = "execute_reversible"
    approval_required: bool = False
    privacy_policy: dict[str, Any] = Field(default_factory=dict)
    limits: dict[str, Any] = Field(default_factory=dict)
    safety_profile: str = "standard"
    revoked_capabilities: frozenset[str] = frozenset()
    policy_version: str = "v1"
    definition_source: str = "draft"
    policy_hash: str = ""
    #: true si no se pudo leer el deny-overlay vigente (revocaciones). El PEP
    #: bloquea escrituras; las lecturas pueden seguir con política documentada.
    policy_store_error: bool = False
    #: epoch monotónico del overlay aplicado (informativo/auditoría).
    revocation_epoch: int = 0

    def with_hash(self) -> "EffectiveExecutionPolicy":
        payload = self.model_dump(mode="json", exclude={"policy_hash"})
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()
        return self.model_copy(update={"policy_hash": digest})

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def _scope_from_graph(graph: dict[str, Any] | None) -> set[str]:
    refs: set[str] = set()
    for node in (graph or {}).get("nodes") or []:
        if not isinstance(node, dict):
            continue
        node_type = str(node.get("type") or "")
        if node_type not in {
            "capability_call",
            "marketplace_action",
            "api_call",
            "business_node",
        }:
            continue
        config = node.get("config") or {}
        ref = (
            config.get("capability")
            or config.get("capability_ref")
            or config.get("action_id")
            or node_type
        )
        if ref:
            refs.add(str(ref))
    return refs


def _blueprint_scope(blueprint: dict[str, Any], role_caps: set[str]) -> set[str]:
    refs: set[str] = set(role_caps)
    for item in blueprint.get("capabilities") or []:
        if isinstance(item, dict) and item.get("capability_ref"):
            refs.add(str(item["capability_ref"]))
    for workflow in blueprint.get("workflows") or []:
        if isinstance(workflow, dict):
            for ref in workflow.get("capability_refs") or []:
                refs.add(str(ref))
    return refs


async def _workflow_row(organization_id: UUID, workflow_id: UUID) -> Any:
    session = await get_async_session()
    try:
        return (
            await session.execute(
                text(
                    "SELECT id, organization_id, workspace_id, solution_id, "
                    "capability_scope, capability_scope_source, safety_profile, "
                    "policy_version, graph, release_policy FROM workflows "
                    "WHERE id = :wid AND organization_id = :oid"
                ),
                {"wid": workflow_id, "oid": organization_id},
            )
        ).fetchone()
    finally:
        await session.close()


async def _solution_row(organization_id: UUID, row: Any) -> Any:
    if row is None:
        return None
    graph = row.graph if isinstance(row.graph, dict) else {}
    slug = str((graph.get("metadata") or {}).get("solution_ref") or "")
    session = await get_async_session()
    try:
        if row.solution_id:
            return (
                await session.execute(
                    text(
                        "SELECT id, slug, blueprint FROM studio_solutions "
                        "WHERE id = :sid AND organization_id = :oid"
                    ),
                    {"sid": row.solution_id, "oid": organization_id},
                )
            ).fetchone()
        if slug:
            return (
                await session.execute(
                    text(
                        "SELECT id, slug, blueprint FROM studio_solutions "
                        "WHERE slug = :slug AND organization_id = :oid"
                    ),
                    {"slug": slug, "oid": organization_id},
                )
            ).fetchone()
    finally:
        await session.close()
    return None


async def _solution_role_caps(organization_id: UUID, blueprint: dict[str, Any]) -> set[str]:
    refs: set[str] = set()
    role_refs = [
        str(item.get("role_ref") or "")
        for item in blueprint.get("roles") or []
        if isinstance(item, dict)
    ]
    if not role_refs:
        return refs
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT slug, allowed_capabilities FROM role_profiles "
                    "WHERE organization_id = :oid AND slug = ANY(:refs)"
                ),
                {"oid": organization_id, "refs": role_refs},
            )
        ).fetchall()
    finally:
        await session.close()
    for row in rows:
        for ref in row.allowed_capabilities or []:
            if ref not in ("knowledge_query", "conversation.send"):
                refs.add(str(ref))
    return refs


async def _role_bindings(organization_id: UUID, graph: dict[str, Any]) -> tuple[dict[str, Any], bool, str, bool]:
    from src.platform.studio.roles import get_agent_role

    bindings: dict[str, Any] = {}
    approval_required = False
    autonomy_max = "execute_reversible"
    wellness = False
    agent_ids = sorted(
        {
            str((node.get("config") or {}).get("agent_id") or "").strip()
            for node in graph.get("nodes") or []
            if isinstance(node, dict)
            and str((node.get("config") or {}).get("agent_id") or "").strip()
        }
    )
    agents: dict[str, Any] = {}
    if agent_ids:
        session = await get_async_session()
        try:
            rows = (
                await session.execute(
                    text(
                        "SELECT id, is_active, role_profile_id FROM agents "
                        "WHERE organization_id = :oid AND id = ANY(:ids)"
                    ),
                    {"oid": organization_id, "ids": [UUID(item) for item in agent_ids]},
                )
            ).fetchall()
        finally:
            await session.close()
        agents = {str(row.id): row for row in rows}
    for agent_id in agent_ids:
        agent = agents.get(agent_id)
        if agent is None or not bool(agent.is_active):
            bindings[agent_id] = {"missing": True}
            continue
        if not agent.role_profile_id:
            bindings[agent_id] = {"agent_id": agent_id, "role": None}
            continue
        role = await get_agent_role(organization_id, UUID(agent_id))
        if role is None:
            bindings[agent_id] = {"agent_id": agent_id, "role": None}
            continue
        bindings[agent_id] = role
        role_id = str(role.get("role_id") or "")
        if role_id.startswith("wellness"):
            wellness = True
        autonomy = str(role.get("autonomy_level") or "propose_actions")
        if autonomy in ("answer_only", "propose_actions", "require_approval"):
            approval_required = True
        if AUTONOMY_RANK.get(autonomy, 1) < AUTONOMY_RANK.get(autonomy_max, 3):
            autonomy_max = autonomy
        if str(role.get("risk_class") or "") in ("high", "critical", "regulated"):
            approval_required = True
    return bindings, approval_required, autonomy_max, wellness


def _is_missing_table(exc: Exception) -> bool:
    """UndefinedTable de Postgres; una caída/conexión NO es tabla ausente."""
    code = getattr(getattr(exc, "orig", None), "sqlstate", None) or getattr(
        exc, "sqlstate", None
    )
    if str(code) == "42P01":
        return True
    folded = str(exc).lower()
    return "does not exist" in folded and "workflow_policy_revocations" in folded


async def _revocations(
    organization_id: UUID, workspace_id: UUID | None, workflow_id: UUID, solution_id: str | None
) -> set[str]:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT capability_ref FROM workflow_policy_revocations "
                    "WHERE organization_id = :oid AND active = true "
                    "AND (workspace_id IS NULL OR workspace_id = :ws) "
                    "AND (capability_ref IS NOT NULL OR scope_type = 'workflow') "
                    "AND (scope_id IS NULL OR scope_id = :wid "
                    "     OR scope_id = CAST(:sid AS uuid))"
                ),
                {
                    "oid": organization_id,
                    "ws": workspace_id,
                    "wid": workflow_id,
                    "sid": solution_id,
                },
            )
        ).fetchall()
    except Exception as exc:  # noqa: BLE001 — tabla ausente != base caída
        # Una instalación sin la tabla es distinta de una caída: si la tabla no
        # existe, el deny-overlay es vacío. Cualquier otro error se propaga para
        # que el llamador decida fail-closed; nunca se convierte en set().
        if _is_missing_table(exc):
            return set()
        raise
    finally:
        await session.close()
    refs: set[str] = set()
    for row in rows:
        refs.add(str(row.capability_ref or "*"))
    return refs


async def overlay_restrictive_policy(
    policy: EffectiveExecutionPolicy,
    *,
    organization_id: UUID,
    workspace_id: UUID | None,
    workflow_id: UUID,
    solution_id: str | None = None,
    permissions: frozenset[str] | None = None,
) -> EffectiveExecutionPolicy:
    """Aplica el deny-overlay vigente sobre un snapshot inmutable.

    NUNCA reconstruye desde el agente/workflow vivo: parte de la política
    congelada y solo puede agregar revocaciones o reducir RBAC. Si la lectura
    de revocaciones falla, devuelve la política con ``policy_store_error`` para
    que el PEP bloquee escrituras (fail closed) sin inventar un set() vacío.
    """
    try:
        live = await _revocations(
            organization_id, workspace_id, workflow_id, solution_id
        )
        store_error = False
    except Exception as exc:  # noqa: BLE001 — fail closed, no fail open
        logger.warning(
            "workflow policy revocation overlay unavailable",
            organization_id=str(organization_id),
            workflow_id=str(workflow_id),
            error=str(exc)[:240],
        )
        live = {"*"}
        store_error = True
    revoked = frozenset(set(policy.revoked_capabilities) | set(live))
    rbac = frozenset(policy.rbac_scopes)
    if permissions is not None:
        current = frozenset(permissions)
        rbac = rbac & current if rbac else current
    changed = (
        revoked != policy.revoked_capabilities
        or rbac != policy.rbac_scopes
        or store_error
    )
    if not changed:
        return policy
    return policy.model_copy(
        update={
            "revoked_capabilities": revoked,
            "rbac_scopes": rbac,
            "policy_store_error": store_error,
            "revocation_epoch": int(policy.revocation_epoch) + 1,
        }
    ).with_hash()


async def resolve_effective_policy(
    *,
    organization_id: UUID,
    workspace_id: UUID | None,
    workflow_id: UUID,
    actor_id: UUID | None = None,
    actor_type: str = "system",
    permissions: frozenset[str] | None = None,
    definition: dict[str, Any] | None = None,
    instance_policy: dict[str, Any] | None = None,
) -> EffectiveExecutionPolicy:
    """Resuelve la autoridad efectiva desde entidades persistidas."""
    if instance_policy:
        try:
            pinned_policy = EffectiveExecutionPolicy.model_validate(instance_policy)
        except Exception:  # noqa: BLE001 — snapshot corrupto: fail closed
            logger.error(
                "workflow instance policy corrupt; denying sensitive execution",
                organization_id=str(organization_id),
                workflow_id=str(workflow_id),
            )
            return EffectiveExecutionPolicy(
                organization_id=str(organization_id),
                workspace_id=str(workspace_id) if workspace_id else None,
                workflow_id=str(workflow_id),
                actor_id=str(actor_id) if actor_id else None,
                actor_type=actor_type,
                rbac_scopes=frozenset(),
                capability_scope=frozenset(),
                revoked_capabilities=frozenset({"*"}),
                definition_source="instance",
                policy_store_error=True,
            ).with_hash()
        pinned_solution = pinned_policy.solution_id
        return await overlay_restrictive_policy(
            pinned_policy,
            organization_id=organization_id,
            workspace_id=workspace_id,
            workflow_id=workflow_id,
            solution_id=pinned_solution,
            permissions=permissions,
        )
    row = await _workflow_row(organization_id, workflow_id)
    if row is None:
        return EffectiveExecutionPolicy(
            organization_id=str(organization_id),
            workspace_id=str(workspace_id) if workspace_id else None,
            workflow_id=str(workflow_id),
            actor_id=str(actor_id) if actor_id else None,
            actor_type=actor_type,
            rbac_scopes=frozenset(permissions or ()),
            capability_scope=frozenset(),
            policy_version="v1",
        ).with_hash()
    graph = definition.get("graph") if definition else row.graph
    if not isinstance(graph, dict):
        graph = row.graph if isinstance(row.graph, dict) else {}
    solution = await _solution_row(organization_id, row)
    blueprint = solution.blueprint if solution and isinstance(solution.blueprint, dict) else {}
    workflow_scope = {
        str(item) for item in (row.capability_scope or []) if isinstance(item, str)
    }
    if solution is not None:
        role_caps = await _solution_role_caps(organization_id, blueprint)
        scope = _blueprint_scope(blueprint, role_caps)
        if not scope:
            scope = workflow_scope or _scope_from_graph(graph)
    else:
        scope = workflow_scope or _scope_from_graph(graph)
    bindings, approval_required, autonomy_max, wellness = await _role_bindings(
        organization_id, graph
    )
    safety_profile = str(row.safety_profile or "standard")
    if wellness or str((solution.slug if solution else "")).startswith("wellness"):
        safety_profile = "wellness"
    from src.platform.workflows.release_policy import _active_bindings_fingerprint

    try:
        live_revocations = await _revocations(
            organization_id,
            workspace_id,
            workflow_id,
            str(solution.id) if solution is not None else None,
        )
        policy_store_error = False
    except Exception as exc:  # noqa: BLE001 — fail closed
        logger.warning(
            "workflow policy revocations unavailable at resolution",
            organization_id=str(organization_id),
            workflow_id=str(workflow_id),
            error=str(exc)[:240],
        )
        live_revocations = {"*"}
        policy_store_error = True

    policy = EffectiveExecutionPolicy(
        organization_id=str(organization_id),
        workspace_id=str(workspace_id) if workspace_id else None,
        workflow_id=str(workflow_id),
        solution_id=str(solution.id) if solution is not None else None,
        actor_id=str(actor_id) if actor_id else None,
        actor_type=actor_type,
        rbac_scopes=frozenset(permissions or ()),
        capability_scope=frozenset(scope),
        role_bindings=bindings,
        installed_bindings_hash=await _active_bindings_fingerprint(
            organization_id, workspace_id
        ),
        autonomy_max=autonomy_max,
        approval_required=approval_required,
        safety_profile=safety_profile,
        revoked_capabilities=frozenset(live_revocations),
        policy_version=str(row.policy_version or "v1"),
        definition_source=str((definition or {}).get("definition_source") or "draft"),
        policy_store_error=policy_store_error,
    )
    return policy.with_hash()


__all__ = [
    "AUTONOMY_RANK",
    "EffectiveExecutionPolicy",
    "POLICY_SCHEMA_VERSION",
    "resolve_effective_policy",
]
