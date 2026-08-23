# =============================================================================
# Plan Limits — enforcement de límites de recursos por plan
# =============================================================================
# max_agents / max_knowledge_bases / max_connectors / max_users del plan
# (NULL = ilimitado). Los endpoints de creación consultan acá antes de
# insertar; si se excede el límite, 409 plan_limit_reached.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

# (count SQL, limit column) por recurso — columnas fijas del schema, sin
# interpolación dinámica de input.
_RESOURCE_QUERIES = {
    "agents": (
        "SELECT COUNT(*) FROM agents WHERE organization_id = :org",
        "p.max_agents",
    ),
    "knowledge_bases": (
        "SELECT COUNT(*) FROM knowledge_bases WHERE organization_id = :org",
        "p.max_knowledge_bases",
    ),
    "connectors": (
        "SELECT COUNT(*) FROM connectors WHERE organization_id = :org",
        "p.max_connectors",
    ),
    "users": (
        "SELECT COUNT(*) FROM memberships WHERE organization_id = :org",
        "p.max_users_per_organization",
    ),
}


class PlanLimitError(Exception):
    def __init__(self, resource: str, limit: int | None, current: int) -> None:
        super().__init__(
            f"Plan limit reached for {resource}: {current} >= {limit}"
        )
        self.resource = resource
        self.limit = limit
        self.current = current


async def check_resource_limit(
    organization_id: UUID, resource: str
) -> None:
    """Lanza PlanLimitError si crear uno más de `resource` excede el plan."""
    if resource not in _RESOURCE_QUERIES:
        raise ValueError(f"Unknown resource for plan limits: {resource}")
    count_sql, limit_column = _RESOURCE_QUERIES[resource]

    from src.platform.billing.invoices import ensure_billing_tables

    await ensure_billing_tables()

    session = await get_async_session()
    try:
        current = int(
            (
                await session.execute(text(count_sql), {"org": organization_id})
            ).scalar()
            or 0
        )
        query_sql = (
            "SELECT {col} AS limit_value FROM subscriptions s "
            "JOIN plans p ON s.plan_id = p.id "
            "WHERE s.organization_id = :org "
            "AND s.status IN ('trialing','active') "
            "ORDER BY s.created_at DESC LIMIT 1"
        ).format(col=limit_column)  # noqa: S608 (col de constante interna)
        row = (
            await session.execute(
                text(query_sql),
                {"org": organization_id},
            )
        ).fetchone()
    finally:
        await session.close()

    if row is None or row.limit_value is None:
        return  # Sin suscripción o sin límite: permitido.

    limit = int(row.limit_value)
    if current >= limit:
        raise PlanLimitError(resource, limit, current)
