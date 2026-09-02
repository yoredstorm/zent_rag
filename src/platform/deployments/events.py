# =============================================================================
# Deployment Events — historial del ciclo de vida de un deployment
# =============================================================================
from __future__ import annotations

from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

# Eventos del ciclo de vida.
CREATED = "created"
DEPLOYING = "deploying"
HEALTHY = "healthy"
FAILED = "failed"
ROLLED_BACK = "rolled_back"
ROLLED_BACK_TO = "rolled_back_to"


async def record_event(
    organization_id: UUID,
    deployment_id: UUID,
    event: str,
    actor_user_id: UUID | None = None,
    metadata: dict | None = None,
) -> None:
    """Registra un evento del deployment (fail-silent)."""
    try:
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    "INSERT INTO deployment_events (id, organization_id, "
                    "deployment_id, event, actor_user_id, metadata) "
                    "VALUES (uuid_generate_v4(), :oid, :did, :event, :uid, "
                    "CAST(:meta AS jsonb))"
                ),
                {
                    "oid": organization_id,
                    "did": deployment_id,
                    "event": event,
                    "uid": actor_user_id,
                    "meta": _json(metadata or {}),
                },
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
    except Exception as exc:
        logger.warning("Failed to record deployment event", error=str(exc))


async def list_events(
    organization_id: UUID, deployment_id: UUID, limit: int = 100
) -> list[dict]:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id, deployment_id, event, actor_user_id, metadata, "
                    "created_at FROM deployment_events "
                    "WHERE organization_id = :oid AND deployment_id = :did "
                    "ORDER BY created_at ASC LIMIT :limit"
                ),
                {"oid": organization_id, "did": deployment_id, "limit": limit},
            )
        ).fetchall()
    finally:
        await session.close()
    return [
        {
            "id": str(r.id),
            "deployment_id": str(r.deployment_id),
            "event": r.event,
            "actor_user_id": str(r.actor_user_id) if r.actor_user_id else None,
            "metadata": r.metadata if isinstance(r.metadata, dict) else {},
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


def _json(value) -> str:
    import json

    return json.dumps(value, default=str)
