# =============================================================================
# Policy Enforcement Point — una frontera para nodos sensibles.
#
# No crea una autoridad paralela: combina el mapa de capacidades del runtime con
# las restricciones del RoleProfile del agente y el RBAC ya resuelto. Fail
# closed: si falta un dato obligatorio o no se puede verificar, DENY.
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
    }
)
_CLINICAL_MARKERS = ("clinical.", "medical.", "diagnos", "prescri", "health.")


@dataclass(frozen=True)
class PolicyVerdict:
    allowed: bool
    code: str = ""
    reasons: tuple[str, ...] = ()
    capability_ref: str = ""


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


async def authorize_node(rctx: Any, node: Any, node_def: Any) -> PolicyVerdict:
    """Evalúa permisos estáticos + rol del agente + guardrail de bienestar."""
    from src.platform.studio.policy import capability_decision
    from src.platform.workflows.nodes import capability_permission

    permissions = frozenset(getattr(rctx.execution, "permissions", frozenset()) or ())
    reasons: list[str] = []
    required: list[str] = []
    for capability in getattr(node_def, "capabilities", ()) or ():
        permission = capability_permission(capability)
        if permission:
            required.append(permission)
    missing = [item for item in required if item not in permissions]
    if missing:
        reasons.append("permisos insuficientes: " + ", ".join(sorted(set(missing))))

    capability_ref = _node_capability_ref(node)
    agent_id = _node_agent_id(node)
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
        node_type = str(getattr(node, "type", ""))
        read_only = node_type not in WRITE_CAPABILITIES
        # `llm` no es una capability del catálogo: el rol ya recorta sus tools.
        # Evaluarlo contra allowed_capabilities bloquearía al agente legítimo.
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

    allowed = not reasons
    verdict = PolicyVerdict(
        allowed=allowed,
        code="policy.allow" if allowed else "policy.denied",
        reasons=tuple(reasons[:6]),
        capability_ref=capability_ref,
    )
    try:
        logger.info(
            "policy.decision",
            organization_id=str(getattr(rctx, "organization_id", "")),
            workspace_id=str(getattr(rctx.execution, "workspace_id", "") or ""),
            actor_type=str(getattr(rctx.execution, "actor_type", "")),
            actor_id=str(getattr(rctx.execution, "actor_id", "") or ""),
            node_id=str(getattr(node, "id", "")),
            node_type=str(getattr(node, "type", "")),
            capability_ref=capability_ref,
            agent_id=agent_id or "",
            role_id=str((role or {}).get("role_id") or ""),
            allowed=allowed,
            reasons=list(verdict.reasons),
            correlation_id=str(getattr(rctx.execution, "correlation_id", "") or ""),
        )
    except Exception:  # noqa: BLE001 — tracing nunca tumba el runtime
        pass
    return verdict


__all__ = ["PolicyVerdict", "authorize_node"]
