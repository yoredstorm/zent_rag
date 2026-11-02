# =============================================================================
# P20 - resolución de un conector PostgreSQL externo para consultas en vivo.
# =============================================================================
# Vive en platform/ para que la capa de agentes no importe adaptadores de
# infraestructura (guard de arquitectura). Devuelve una fábrica de sesiones
# read-only ya validada por connector_security (SSRF/TLS).
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import quote_plus
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.platform.workflows.connector_security import (
    get_connector_engine,
    prepare_connector_target,
)

_POSTGRES_TYPES = {"postgres", "postgresql"}


@dataclass(kw_only=True)
class ExternalPostgresConnection:
    config: dict = field(default_factory=dict)
    secret: dict = field(default_factory=dict)
    session_factory: Callable[[], AsyncSession] | None = None
    error: str | None = None


async def resolve_external_postgres_connection(
    *,
    organization_id: UUID,
    connector_id: UUID,
    workspace_id: UUID | None,
) -> ExternalPostgresConnection:
    """Valida conector/workspace/credenciales y prepara una sesión externa.

    No abre la Managed DB ni la base interna de ZENT. Los errores son códigos
    estables para que la tool los propague sin filtrar secretos.
    """
    from src.infrastructure.postgres.relational_db import PostgresConnectorRepository
    from src.infrastructure.secrets.secret_store_resolver import get_secret_store

    connector = await PostgresConnectorRepository().get_connector(
        organization_id, connector_id
    )
    if connector is None or str(connector.status or "").lower() != "active":
        return ExternalPostgresConnection(error="SOURCE_UNAVAILABLE")
    if str(connector.type or "").lower() not in _POSTGRES_TYPES:
        return ExternalPostgresConnection(error="PROVIDER_NOT_SUPPORTED")
    if (
        workspace_id is not None
        and connector.workspace_id
        and str(connector.workspace_id) != str(workspace_id)
    ):
        return ExternalPostgresConnection(error="PERMISSION_DENIED")

    config = dict(connector.config_json or {})
    secret = await get_secret_store().get(organization_id, connector_id)
    password = secret.get("password") if isinstance(secret, dict) else None
    if not password:
        return ExternalPostgresConnection(error="NEEDS_CREDENTIALS")
    try:
        target = await prepare_connector_target(
            organization_id=organization_id,
            workspace_id=workspace_id,
            connector_id=connector_id,
            config=config,
            password=str(password),
        )
        dsn = (
            f"postgresql+asyncpg://{quote_plus(target.user)}:"
            f"{quote_plus(target.password)}@{target.host}:{target.port}/"
            f"{quote_plus(target.database)}"
        )
        engine = get_connector_engine(dsn, target)
    except Exception as exc:  # noqa: BLE001
        return ExternalPostgresConnection(error=str(exc)[:300])

    factory = async_sessionmaker(engine, expire_on_commit=False)
    return ExternalPostgresConnection(
        config=config,
        secret=secret if isinstance(secret, dict) else {},
        session_factory=factory,
    )
