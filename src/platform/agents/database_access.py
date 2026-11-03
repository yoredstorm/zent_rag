# =============================================================================
# P20 - resolución de la fuente de datos declarada por un agente.
# =============================================================================
# No concede permisos: solo identifica la fuente única y su conector. Los
# grants se validan en `agent_data_grants` antes de consultar.
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import bindparam, text

DB_SOURCE_TYPES: tuple[str, ...] = (
    "sql",
    "postgres",
    "postgresql",
    "mysql",
    "mssql",
    "oracle",
    "snowflake",
)


@dataclass(kw_only=True)
class AgentDatabaseSource:
    source_id: str
    name: str
    connector_id: str
    workspace_id: str | None
    source_mode: str


async def resolve_agent_database_source(
    *,
    organization_id: UUID,
    user_id: UUID | None,
    source_ids: list[str],
) -> tuple[AgentDatabaseSource | None, str | None]:
    """Resuelve la fuente DB externa declarada por el agente.

    Solo usa `source_ids` efectivos (scope del agente ∩ scope del caller).
    Si hay más de un conector distinto, falla cerrado.
    """
    ids = [str(item).strip() for item in source_ids if str(item).strip()]
    if not ids:
        return None, None

    from src.infrastructure.postgres.session import get_async_session

    stmt = text(
        "SELECT id::text AS id, name, workspace_id::text AS workspace_id, "
        "config_json, status FROM kb_sources "
        "WHERE organization_id = :oid AND id::text IN :ids "
        "AND type IN :types "
        "AND COALESCE(config_json->>'connector_id', '') <> '' "
        "AND status NOT IN ('disabled', 'suspended', 'deleted', 'error', 'failed')"
    ).bindparams(
        bindparam("ids", expanding=True),
        bindparam("types", expanding=True),
    )
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                stmt,
                {
                    "oid": str(organization_id),
                    "ids": ids,
                    "types": list(DB_SOURCE_TYPES),
                },
            )
        ).fetchall()
    finally:
        await session.close()
    if not rows:
        return None, None

    connector_ids = {
        str((row.config_json or {}).get("connector_id") or "") for row in rows
    }
    connector_ids.discard("")
    if not connector_ids:
        return None, None
    if len(connector_ids) > 1:
        return None, (
            "MULTIPLE_DATABASE_SOURCES: el agente tiene más de una base "
            "de datos vinculada; selecciona una sola para consultar"
        )

    row = rows[0]
    workspace_id = row.workspace_id
    if user_id is not None:
        try:
            from src.platform.workspaces.context import get_active_workspace_id

            active = await get_active_workspace_id(organization_id, user_id)
            if active is not None:
                if workspace_id and str(active) != str(workspace_id):
                    return None, (
                        "PERMISSION_DENIED: la fuente pertenece a otro workspace"
                    )
                workspace_id = str(active)
        except Exception as exc:  # noqa: BLE001 - fail closed
            return None, (
                "PERMISSION_DENIED: no se pudo verificar el workspace de la fuente"
            )
    config = dict(row.config_json or {})
    return AgentDatabaseSource(
        source_id=str(row.id),
        name=str(row.name or ""),
        connector_id=next(iter(connector_ids)),
        workspace_id=workspace_id,
        source_mode=str(config.get("source_mode") or ""),
    ), None
