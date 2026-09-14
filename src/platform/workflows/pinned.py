# =============================================================================
# Workflow Pinned Data — datos fijados para pruebas (Fase 4).
#
# Aislamiento: tenant + workspace vía workflow. SOLO se aplican cuando el run
# es simulación (`simulate=true`); en producción se ignoran por diseño.
# Nunca forman parte del graph ni de las versiones publicadas.
# =============================================================================
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.postgres.session import get_async_session

_DDL = """
CREATE TABLE IF NOT EXISTS workflow_pinned_data (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    workflow_id UUID NOT NULL,
    node_id VARCHAR(80) NOT NULL,
    output JSONB NOT NULL DEFAULT '{}',
    created_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (workflow_id, node_id)
)
"""

_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_workflow_pinned_org "
    "ON workflow_pinned_data(organization_id, workflow_id)"
)


_ENSURED = False


async def ensure_pinned_table() -> None:
    global _ENSURED
    if _ENSURED:
        return
    session = await get_async_session()
    try:
        # Paridad si la migración 112 aún no se aplicó (dev/test).
        await session.execute(
            text(
                "ALTER TABLE workflow_runs ADD COLUMN IF NOT EXISTS run_mode "
                "VARCHAR(20) NOT NULL DEFAULT 'full', "
                "ADD COLUMN IF NOT EXISTS target_node_id VARCHAR(80), "
                "ADD COLUMN IF NOT EXISTS source_run_id UUID"
            )
        )
        await session.execute(text(_DDL))
        await session.execute(text(_INDEX))
        await session.commit()
        _ENSURED = True
    except Exception:  # noqa: BLE001
        await session.rollback()
    finally:
        await session.close()


async def _workflow_owned(organization_id: UUID, workflow_id: UUID) -> bool:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text("SELECT 1 FROM workflows WHERE id = :wid AND organization_id = :oid"),
                {"wid": workflow_id, "oid": organization_id},
            )
        ).fetchone()
        return row is not None
    finally:
        await session.close()


async def list_pinned(organization_id: UUID, workflow_id: UUID) -> dict[str, Any] | None:
    await ensure_pinned_table()
    if not await _workflow_owned(organization_id, workflow_id):
        return None
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT node_id, output, updated_at FROM workflow_pinned_data "
                    "WHERE organization_id = :oid AND workflow_id = :wid ORDER BY node_id"
                ),
                {"oid": organization_id, "wid": workflow_id},
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "nodes": [
            {
                "node_id": str(r.node_id),
                "output": r.output or {},
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ]
    }


async def upsert_pinned(
    organization_id: UUID,
    workflow_id: UUID,
    node_id: str,
    output: dict[str, Any],
    *,
    created_by: UUID | None = None,
) -> dict[str, Any] | None:
    await ensure_pinned_table()
    if not await _workflow_owned(organization_id, workflow_id):
        return None
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO workflow_pinned_data "
                    "(organization_id, workflow_id, node_id, output, created_by) "
                    "VALUES (:oid, :wid, :nid, CAST(:output AS jsonb), :by) "
                    "ON CONFLICT (workflow_id, node_id) DO UPDATE SET "
                    "output = EXCLUDED.output, updated_at = NOW() "
                    "RETURNING node_id, output, updated_at"
                ),
                {
                    "oid": organization_id,
                    "wid": workflow_id,
                    "nid": str(node_id)[:80],
                    "output": json.dumps(output or {}, default=str),
                    "by": created_by,
                },
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    return {
        "node_id": str(row.node_id),
        "output": row.output or {},
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def delete_pinned(organization_id: UUID, workflow_id: UUID, node_id: str) -> bool:
    await ensure_pinned_table()
    session = await get_async_session()
    try:
        result = await session.execute(
            text(
                "DELETE FROM workflow_pinned_data "
                "WHERE organization_id = :oid AND workflow_id = :wid AND node_id = :nid"
            ),
            {"oid": organization_id, "wid": workflow_id, "nid": node_id},
        )
        await session.commit()
        return result.rowcount > 0
    finally:
        await session.close()


async def load_pinned_map(organization_id: UUID, workflow_id: UUID) -> dict[str, dict[str, Any]]:
    """node_id → output fijado (solo para runs simulados)."""
    data = await list_pinned(organization_id, workflow_id)
    if data is None:
        return {}
    return {entry["node_id"]: dict(entry["output"] or {}) for entry in data["nodes"]}


__all__ = [
    "delete_pinned",
    "ensure_pinned_table",
    "list_pinned",
    "load_pinned_map",
    "upsert_pinned",
]
