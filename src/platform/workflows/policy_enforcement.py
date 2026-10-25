# =============================================================================
# Policy Enforcement Point — una frontera para nodos sensibles.
#
# Con EffectiveExecutionPolicy: intersección RBAC ∩ scope workflow/solución ∩
# rol del agente ∩ bindings ∩ revocaciones. Sin policy se conserva el camino
# legado para llamadores unitarios; el runtime siempre pasa policy.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)

WRITE_CAPABILITIES = frozenset(
    {
        "api_call",
        "business_node",
        "capability_call",
        "marketplace_action",
        "notify",
        "business_result",
    }
)
_SCOPED_NODE_TYPES = frozenset(
    {
        "api_call",
        "business_node",
        "capability_call",
        "marketplace_action",
        "business_result",
        "subworkflow_call",
    }
)
_CLINICAL_MARKERS = ("clinical.", "medical.", "diagnos", "prescri", "health.")
_IRREVERSIBLE_MARKERS = (
    "checkout",
    "charge",
    "payment",
    "refund",
    "delete",
    "remove",
    "create_order",
    "order.create",
)


@dataclass(frozen=True)
class PolicyVerdict:
    allowed: bool
    code: str = ""
    reasons: tuple[str, ...] = ()
    capability_ref: str = ""
    effective_scope_hash: str = ""
    approval_required: bool = False
    policy_version: str = ""


def _node_agent_id(node: Any) -> str | None:
    config = getattr(node, "config", None) or {}
    value = str(config.get("agent_id") or "").strip()
    return value or None


def _node_capability_ref(node: Any) -> str:
    config = getattr(node, "config", None) or {}
    for key in ("capability", "capability_ref", "action_id"):
        value = str(config.get(key) or "").strip()
        if value:
            return value
    return str(getattr(node, "type", "") or "workflow.node")


def _is_clinical(capability_ref: str) -> bool:
    folded = capability_ref.lower()
    return any(marker in folded for marker in _CLINICAL_MARKERS)


def _is_irreversible(node: Any, capability_ref: str) -> bool:
    node_type = str(getattr(node, "type", ""))
    config = getattr(node, "config", None) or {}
    folded = capability_ref.lower()
    if node_type in ("marketplace_action", "business_node"):
        return True
    if node_type == "api_call" and str(config.get("method") or "GET").upper() not in (
        "GET",
        "HEAD",
        "OPTIONS",
    ):
        return True
    return any(marker in folded for marker in _IRREVERSIBLE_MARKERS)


def _is_internal_effect(node: Any, capability_ref: str) -> bool:
    node_type = str(getattr(node, "type", ""))
    config = getattr(node, "config", None) or {}
    if node_type == "notify":
        return str(config.get("channel") or "in_app") in ("in_app", "zent")
    if node_type in (
        "business_result",
        "state_set",
        "state_merge",
        "state_append",
        "state_remove",
    ):
        return True
    if node_type == "subworkflow_call":
        return True
    if node_type in ("kb_query", "knowledge_query"):
        return True
    return False


async def authorize_node(
    rctx: Any,
    node: Any,
    node_def: Any,
    policy: Any | None = None,
) -> PolicyVerdict:
    """Evalúa RBAC + scope + rol + autonomía + revocaciones + aprobación."""
    from src.platform.studio.policy import capability_decision
    from src.platform.workflows.nodes import capability_permission

    policy = policy if policy is not None else getattr(rctx.execution, "effective_policy", None)
    permissions = frozenset(getattr(rctx.execution, "permissions", frozenset()) or ())
    reasons: list[str] = []
    required: list[str] = []
    for capability in getattr(node_def, "capabilities", ()) or ():
        permission = capability_permission(capability)
        if permission:
            required.append(permission)

    capability_ref = _node_capability_ref(node)
    agent_id = _node_agent_id(node)
    node_type = str(getattr(node, "type", ""))
    read_only = node_type not in WRITE_CAPABILITIES
    code = "policy.allow"
    approval_required = False
    effective_scope_hash = ""
    policy_version = ""

    if policy is None:
        # Camino legado para llamadores unitarios. El runtime pasa policy.
        missing = [item for item in required if item not in permissions]
        if missing:
            reasons.append("permisos insuficientes: " + ", ".join(sorted(set(missing))))
        role = None
        if agent_id:
            try:
                from src.platform.studio.roles import get_agent_role

                role = await get_agent_role(
                    UUID(str(rctx.organization_id)), UUID(str(agent_id))
                )
            except (ValueError, TypeError):
                role = None
        if role is not None:
            if node_type != "llm":
                decision = capability_decision(
                    role,
                    capability_ref=capability_ref,
                    actor_permissions=permissions,
                    required_permissions=required,
                    read_only=read_only,
                )
                if not decision.allowed:
                    reasons.extend(str(item) for item in decision.reasons)
            role_id = str(role.get("role_id") or "")
            if role_id.startswith("wellness") and (
                _is_clinical(capability_ref) or not read_only
            ):
                reasons.append(
                    "bienestar no ejecuta acciones clínicas ni escrituras autónomas"
                )
    else:
        rbac = frozenset(getattr(policy, "rbac_scopes", frozenset()) or ())
        effective_permissions = permissions & rbac if rbac else permissions
        missing = [item for item in required if item not in effective_permissions]
        if missing:
            reasons.append("permisos insuficientes: " + ", ".join(sorted(set(missing))))
            code = "policy.denied"
        effective_scope_hash = str(getattr(policy, "policy_hash", "") or "")
        policy_version = str(getattr(policy, "policy_version", "v1"))
        policy_workspace = getattr(policy, "workspace_id", None)
        node_workspace = getattr(rctx.execution, "workspace_id", None)
        if policy_workspace and node_workspace and str(policy_workspace) != str(node_workspace):
            reasons.append("la política pertenece a otro workspace")
            code = "policy.workspace_mismatch"

        revoked = set(getattr(policy, "revoked_capabilities", frozenset()) or ())
        if "*" in revoked or capability_ref in revoked:
            reasons.append(f"capacidad revocada: {capability_ref}")
            code = "policy.revoked"

        scope = set(getattr(policy, "capability_scope", frozenset()) or ())
        is_internal = _is_internal_effect(node, capability_ref)
        if (
            node_type in _SCOPED_NODE_TYPES
            and not is_internal
            and capability_ref not in scope
        ):
            reasons.append(f"{capability_ref} está fuera del scope del workflow/solución")
            code = "policy.scope_exceeded"

        if node_type == "llm":
            if not agent_id:
                source = str(getattr(policy, "definition_source", "draft"))
                if source in ("published", "instance") and not bool(
                    getattr(rctx, "simulate", False)
                ):
                    reasons.append("paso de IA sin agente en ejecución publicada")
                    code = "policy.role_missing"
            else:
                role = (getattr(policy, "role_bindings", {}) or {}).get(str(agent_id))
                if not role or role.get("missing"):
                    reasons.append(f"agente {agent_id} inexistente o inactivo")
                    code = "policy.role_missing"
        elif agent_id:
            role = (getattr(policy, "role_bindings", {}) or {}).get(str(agent_id))
            if not role or role.get("missing"):
                reasons.append(f"agente {agent_id} inexistente o inactivo")
                code = "policy.role_missing"
            elif role.get("role") is None and not role.get("role_id"):
                # Agente activo sin RoleProfile: RBAC + scope del workflow.
                pass
            else:
                decision = capability_decision(
                    role,
                    capability_ref=capability_ref,
                    actor_permissions=effective_permissions,
                    required_permissions=required,
                    read_only=read_only,
                )
                if not decision.allowed:
                    reasons.extend(str(item) for item in decision.reasons)
                    code = "policy.denied"

        if str(getattr(policy, "safety_profile", "standard")) == "wellness" and (
            _is_clinical(capability_ref) or not read_only
        ):
            reasons.append(
                "bienestar no ejecuta acciones clínicas ni escrituras autónomas"
            )
            code = "policy.denied"

        if (
            bool(getattr(policy, "approval_required", False))
            and _is_irreversible(node, capability_ref)
            and not (getattr(node, "config", None) or {}).get("approval_ref")
        ):
            reasons.append("acción irreversible sin aprobación válida")
            code = "policy.approval_required"
            approval_required = True

    allowed = not reasons
    verdict = PolicyVerdict(
        allowed=allowed,
        code="policy.allow" if allowed else (code or "policy.denied"),
        reasons=tuple(reasons[:6]),
        capability_ref=capability_ref,
        effective_scope_hash=effective_scope_hash,
        approval_required=approval_required,
        policy_version=policy_version,
    )
    try:
        logger.info(
            "policy.decision",
            organization_id=str(getattr(rctx, "organization_id", "")),
            workspace_id=str(getattr(rctx.execution, "workspace_id", "") or ""),
            actor_type=str(getattr(rctx.execution, "actor_type", "")),
            actor_id=str(getattr(rctx.execution, "actor_id", "") or ""),
            node_id=str(getattr(node, "id", "")),
            node_type=node_type,
            capability_ref=capability_ref,
            agent_id=agent_id or "",
            role_id=str(
                ((getattr(policy, "role_bindings", {}) or {}).get(agent_id or "") or {}).get(
                    "role_id", ""
                )
                if policy is not None
                else ""
            ),
            allowed=allowed,
            code=verdict.code,
            reasons=list(verdict.reasons),
            policy_version=verdict.policy_version,
            effective_scope_hash=verdict.effective_scope_hash,
            approval_required=verdict.approval_required,
            correlation_id=str(getattr(rctx.execution, "correlation_id", "") or ""),
        )
    except Exception:  # noqa: BLE001 — tracing nunca tumba el runtime
        pass
    return verdict


__all__ = ["PolicyVerdict", "WRITE_CAPABILITIES", "authorize_node"]
