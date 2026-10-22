# =============================================================================
# Role policy — constraints are intersection, never elevation.
#
# Effective authority = actor permissions ∩ service identity ∩ tenant policy.
# A role can only narrow that set with allowed_capabilities/allowed_tools and
# autonomy. A regulated role never gains authority from its label.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass

from src.platform.studio.contracts import RoleProfileV1, role_from_legacy_payload


@dataclass(frozen=True)
class RoleDecision:
    allowed: bool
    requires_approval: bool
    reasons: tuple[str, ...] = ()


def intersect_permissions(*sets: frozenset[str] | set[str] | None) -> frozenset[str]:
    present = [frozenset(value or ()) for value in sets if value is not None]
    if not present:
        return frozenset()
    result = present[0]
    for value in present[1:]:
        result &= value
    return result


def capability_decision(
    role: RoleProfileV1 | dict,
    *,
    capability_ref: str,
    actor_permissions: frozenset[str] | set[str] | None = None,
    required_permissions: list[str] | None = None,
    read_only: bool = True,
    installed: bool = True,
) -> RoleDecision:
    profile = role if isinstance(role, RoleProfileV1) else role_from_legacy_payload(role)
    reasons: list[str] = []
    if not installed:
        return RoleDecision(False, False, ("la capacidad no está instalada",))
    if capability_ref in profile.denied_capabilities:
        return RoleDecision(False, False, (f"{capability_ref} está denegada por el rol",))
    if profile.allowed_capabilities and capability_ref not in profile.allowed_capabilities:
        return RoleDecision(
            False, False, (f"{capability_ref} no está en allowed_capabilities",)
        )
    actor = frozenset(actor_permissions or ())
    missing = [
        permission
        for permission in (required_permissions or [])
        if permission not in actor and "admin:*" not in actor
    ]
    if missing:
        return RoleDecision(
            False,
            False,
            ("permisos insuficientes: " + ", ".join(missing[:4]),),
        )
    if profile.autonomy_level in ("answer_only", "propose_actions") and not read_only:
        return RoleDecision(
            False,
            False,
            (f"autonomía {profile.autonomy_level} no ejecuta escrituras",),
        )
    if profile.autonomy_level == "execute_reversible" and profile.risk_class == "regulated":
        return RoleDecision(False, False, ("rol regulated no ejecuta cambios reversibles",))
    requires_approval = profile.autonomy_level == "require_approval" or (
        profile.risk_class in ("high", "regulated") and not read_only
    )
    if profile.safety.no_automatic_irreversible_action and not read_only:
        requires_approval = True
    return RoleDecision(True, requires_approval, tuple(reasons))


def effective_permissions(
    *,
    actor_permissions: frozenset[str] | set[str] | None,
    service_permissions: frozenset[str] | set[str] | None,
    tenant_permissions: frozenset[str] | set[str] | None,
) -> frozenset[str]:
    """Three-way intersection. Any missing layer is treated as empty."""
    return intersect_permissions(actor_permissions, service_permissions, tenant_permissions)


__all__ = [
    "RoleDecision",
    "capability_decision",
    "effective_permissions",
    "intersect_permissions",
]
