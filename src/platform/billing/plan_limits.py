# =============================================================================
# Plan Limits — enforcement de límites de recursos por plan
# =============================================================================
# Delega en check_entitlement (plan_entitlements). Las columnas plans.max_*
# solo se leen como fallback si falta la fila de entitlement.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from src.platform.billing.entitlements import EntitlementDenied, check_entitlement

_RESOURCE_TO_KEY = {
    "agents": "max_agents",
    "knowledge_bases": "max_knowledge_bases",
    "connectors": "max_connectors",
    "users": "max_users",
}


class PlanLimitError(Exception):
    def __init__(self, resource: str, limit: int | None, current: int) -> None:
        super().__init__(
            f"Plan limit reached for {resource}: {current} >= {limit}"
        )
        self.resource = resource
        self.limit = limit
        self.current = current


def plan_limit_detail(exc: PlanLimitError) -> dict:
    return {
        "error_code": "plan_limit_reached",
        "message": str(exc),
        "resource": exc.resource,
    }


async def check_resource_limit(
    organization_id: UUID, resource: str
) -> None:
    """Lanza PlanLimitError si crear uno más de `resource` excede el plan."""
    key = _RESOURCE_TO_KEY.get(resource)
    if key is None:
        raise ValueError(f"Unknown resource for plan limits: {resource}")
    try:
        await check_entitlement(organization_id, key)
    except EntitlementDenied as exc:
        raise PlanLimitError(resource, exc.limit, exc.current or 0) from exc
