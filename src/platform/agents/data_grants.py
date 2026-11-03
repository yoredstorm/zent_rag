# =============================================================================
# P20-04 - grants de datos por agente (backend, no checkbox del prompt).
# =============================================================================
# Un agente solo puede consultar los recursos explícitamente concedidos en
# `agent_data_grants`. La selección de una fuente SQL no concede todas sus
# tablas. Sin grant activo: PERMISSION_DENIED.
from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.postgres.session import get_async_session

#: Capacidad genérica de consulta read-only sobre una fuente SQL.
DATA_QUERY_CAPABILITY = "store.query_database"
_READ_SCOPES = {"read", "aggregate:read", "*"}

_ENSURED = False


async def ensure_agent_data_grants_table() -> None:
    global _ENSURED
    if _ENSURED:
        return
    session = await get_async_session()
    try:
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS agent_data_grants (
                    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                    organization_id UUID NOT NULL,
                    workspace_id UUID,
                    agent_id UUID NOT NULL,
                    capability_ref VARCHAR(120) NOT NULL,
                    resource_ref VARCHAR(200) NOT NULL DEFAULT '',
                    scopes TEXT[] NOT NULL DEFAULT '{}',
                    row_scope JSONB NOT NULL DEFAULT '{}'::jsonb,
                    active BOOLEAN NOT NULL DEFAULT TRUE,
                    expires_at TIMESTAMPTZ,
                    version INTEGER NOT NULL DEFAULT 1,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        )
        await session.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "uq_agent_data_grants_scope ON agent_data_grants "
                "(organization_id, agent_id, capability_ref, resource_ref)"
            )
        )
        await session.commit()
    finally:
        await session.close()
    _ENSURED = True


async def get_agent_data_grants(
    organization_id: UUID,
    agent_id: UUID,
    *,
    workspace_id: UUID | None = None,
) -> list[dict]:
    await ensure_agent_data_grants_table()
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT capability_ref, resource_ref, scopes, row_scope, "
                    "expires_at FROM agent_data_grants "
                    "WHERE organization_id = :oid AND agent_id = :aid "
                    "AND active = TRUE "
                    "AND (expires_at IS NULL OR expires_at > NOW()) "
                    "AND (CAST(:wid AS uuid) IS NULL OR workspace_id IS NULL "
                    "     OR workspace_id = CAST(:wid AS uuid))"
                ),
                {
                    "oid": str(organization_id),
                    "aid": str(agent_id),
                    "wid": str(workspace_id) if workspace_id else None,
                },
            )
        ).fetchall()
    finally:
        await session.close()
    return [
        {
            "capability_ref": str(row.capability_ref),
            "resource_ref": str(row.resource_ref or ""),
            "scopes": list(row.scopes or []),
            "row_scope": dict(row.row_scope or {}),
            "expires_at": row.expires_at,
        }
        for row in rows
    ]


async def allowed_query_resources(
    organization_id: UUID,
    agent_id: UUID | None,
    *,
    workspace_id: UUID | None = None,
) -> tuple[set[str], str | None]:
    """Recursos autorizados para la tool genérica de consulta.

    Falla cerrado si no hay agent_id, no hay grants, el grant está vencido o
    requiere row_scope (la tool genérica no puede aplicarlo todavía).
    """
    if agent_id is None:
        return set(), "PERMISSION_DENIED: la tool requiere un agente identificado"
    grants = await get_agent_data_grants(
        organization_id, agent_id, workspace_id=workspace_id
    )
    return _resources_for_capabilities(
        grants, {DATA_QUERY_CAPABILITY, "store.catalog.read"}
    )


async def allowed_capability_resources(
    organization_id: UUID,
    agent_id: UUID | None,
    capability_ref: str,
    *,
    workspace_id: UUID | None = None,
) -> tuple[set[str], str | None]:
    """Recursos autorizados para una capability comercial específica."""
    if agent_id is None:
        return set(), "PERMISSION_DENIED: la tool requiere un agente identificado"
    grants = await get_agent_data_grants(
        organization_id, agent_id, workspace_id=workspace_id
    )
    return _resources_for_capabilities(grants, {capability_ref})


def _resources_for_capabilities(
    grants: list[dict], capabilities: set[str]
) -> tuple[set[str], str | None]:
    if not grants:
        return set(), "PERMISSION_DENIED: el agente no tiene grants de datos"

    allowed: set[str] = set()
    row_scoped = 0
    for grant in grants:
        if grant["capability_ref"] not in capabilities:
            continue
        scopes = {str(scope) for scope in grant["scopes"]}
        if not scopes & _READ_SCOPES:
            continue
        if grant["row_scope"]:
            row_scoped += 1
            continue
        resource = str(grant["resource_ref"] or "").strip().lower()
        if resource:
            allowed.add(resource)

    if not allowed:
        if row_scoped:
            return set(), (
                "PERMISSION_DENIED: el grant requiere row_scope; "
                "usa una tool tipada con filtro de titularidad"
            )
        return set(), "PERMISSION_DENIED: no hay recursos autorizados"
    return allowed, None


async def set_agent_data_grants(
    organization_id: UUID,
    agent_id: UUID,
    grants: list[dict],
    *,
    workspace_id: UUID | None = None,
) -> None:
    """Reemplaza los grants del agente. Uso administrativo/tests."""
    await ensure_agent_data_grants_table()
    session = await get_async_session()
    try:
        exists = (
            await session.execute(
                text(
                    "SELECT 1 FROM agents WHERE id = :aid "
                    "AND organization_id = :oid"
                ),
                {"aid": str(agent_id), "oid": str(organization_id)},
            )
        ).fetchone()
        if exists is None:
            raise ValueError("agent_not_found")
        await session.execute(
            text(
                "DELETE FROM agent_data_grants "
                "WHERE agent_id = :aid AND organization_id = :oid"
            ),
            {"aid": str(agent_id), "oid": str(organization_id)},
        )
        for grant in grants:
            scopes = [str(scope) for scope in grant.get("scopes") or ["read"]]
            await session.execute(
                text(
                    "INSERT INTO agent_data_grants "
                    "(organization_id, workspace_id, agent_id, capability_ref, "
                    " resource_ref, scopes, row_scope, active, expires_at) "
                    "VALUES (:oid, :wid, :aid, :cap, :res, "
                    "        CAST(:scopes AS text[]), CAST(:row_scope AS jsonb), "
                    "        TRUE, :expires_at)"
                ),
                {
                    "oid": str(organization_id),
                    "wid": str(workspace_id) if workspace_id else None,
                    "aid": str(agent_id),
                    "cap": str(grant.get("capability_ref") or DATA_QUERY_CAPABILITY),
                    "res": str(grant.get("resource_ref") or ""),
                    "scopes": scopes,
                    "row_scope": json.dumps(grant.get("row_scope") or {}),
                    "expires_at": grant.get("expires_at"),
                },
            )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
