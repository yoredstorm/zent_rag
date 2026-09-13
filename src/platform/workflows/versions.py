# =============================================================================
# Workflow Versions — snapshot inmutable del workflow (grafo + trigger)
# =============================================================================
# El hook y /run siempre ejecutan la fila viva `workflows`. Una versión es una
# copia congelada de lo publicable: nombre, trigger, steps y grafo. Restaurar
# escribe el snapshot de vuelta en la fila viva (rollback). El secret del
# webhook NUNCA entra al snapshot (`get_workflow` lo filtra).
# =============================================================================
from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

VERSION_STATUSES = ("draft", "ready", "production", "archived")

# Transiciones permitidas del ciclo de vida de una versión de workflow.
_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"ready", "archived"},
    "ready": {"production", "archived"},
    "production": {"ready", "archived"},
    "archived": set(),
}

# Campos de `get_workflow` que forman el snapshot ejecutable.
_SNAPSHOT_KEYS = (
    "name",
    "description",
    "trigger_type",
    "trigger_config",
    "steps",
    "graph",
    "workflow_version",
    "graph_source",
    "editor_state",
)

_TABLE = """
CREATE TABLE IF NOT EXISTS workflow_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    workflow_id UUID NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'ready', 'production', 'archived')),
    config_snapshot JSONB NOT NULL DEFAULT '{}',
    notes TEXT,
    created_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (workflow_id, version_number)
)
"""

_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_workflow_versions_wf "
    "ON workflow_versions(workflow_id, version_number DESC)"
)


def validate_transition(current: str, target: str) -> bool:
    return target in _TRANSITIONS.get(current, set())


def snapshot_workflow(workflow: dict) -> dict:
    """Congela la configuración publicable de un workflow.

    `workflow` es la salida de `get_workflow` (trigger_config ya viene sin
    `hook_secret_hash`).
    """
    snapshot = {key: workflow.get(key) for key in _SNAPSHOT_KEYS}
    snapshot["schema_version"] = 1
    return json.loads(json.dumps(snapshot, default=str))


async def ensure_workflow_versions_table() -> None:
    """Crea la tabla si la base es anterior a la migración 109 (fail-silent)."""
    session = await get_async_session()
    try:
        await session.execute(text(_TABLE))
        await session.execute(text(_INDEX))
        await session.commit()
    except Exception:  # noqa: BLE001
        await session.rollback()
        logger.warning("Failed to ensure workflow_versions table")
    finally:
        await session.close()


def _version_response(row) -> dict:
    return {
        "id": str(row.id),
        "workflow_id": str(row.workflow_id),
        "version_number": int(row.version_number),
        "status": row.status,
        "config_snapshot": row.config_snapshot or {},
        "notes": row.notes,
        "created_by": str(row.created_by) if row.created_by else None,
        "created_at": row.created_at.isoformat(),
    }


async def list_versions(organization_id: UUID, workflow_id: UUID) -> dict:
    await ensure_workflow_versions_table()
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id, workflow_id, version_number, status, config_snapshot, "
                    "notes, created_by, created_at FROM workflow_versions "
                    "WHERE organization_id = :oid AND workflow_id = :wid "
                    "ORDER BY version_number DESC"
                ),
                {"oid": organization_id, "wid": workflow_id},
            )
        ).fetchall()
    finally:
        await session.close()
    versions = [_version_response(r) for r in rows]
    return {"versions": versions, "count": len(versions)}


async def _demote_other_productions(
    session, organization_id: UUID, workflow_id: UUID, keep_id: UUID
) -> None:
    """Solo una versión en production por workflow: el resto vuelve a ready."""
    await session.execute(
        text(
            "UPDATE workflow_versions SET status = 'ready' "
            "WHERE organization_id = :oid AND workflow_id = :wid "
            "AND status = 'production' AND id <> :vid"
        ),
        {"oid": organization_id, "wid": workflow_id, "vid": keep_id},
    )


async def create_version(
    organization_id: UUID,
    workflow_id: UUID,
    *,
    notes: str | None = None,
    created_by: UUID | None = None,
    status: str = "draft",
) -> dict | None:
    """Snapshot del estado vivo del workflow. None = workflow inexistente."""
    if status not in VERSION_STATUSES:
        raise ValueError(f"status debe ser uno de {VERSION_STATUSES}")
    from src.platform.workflows.engine import get_workflow

    workflow = await get_workflow(organization_id, workflow_id)
    if workflow is None:
        return None
    snapshot = snapshot_workflow(workflow)

    await ensure_workflow_versions_table()
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO workflow_versions (organization_id, workflow_id, "
                    "version_number, status, config_snapshot, notes, created_by) "
                    "SELECT :oid, :wid, "
                    "COALESCE(MAX(version_number), 0) + 1, :status, "
                    "CAST(:snapshot AS jsonb), :notes, :by "
                    "FROM workflow_versions WHERE workflow_id = :wid "
                    "RETURNING id, workflow_id, version_number, status, "
                    "config_snapshot, notes, created_by, created_at"
                ),
                {
                    "oid": organization_id,
                    "wid": workflow_id,
                    "status": status,
                    "snapshot": json.dumps(snapshot),
                    "notes": notes,
                    "by": created_by,
                },
            )
        ).fetchone()
        if status == "production":
            await _demote_other_productions(
                session, organization_id, workflow_id, row.id
            )
        await session.commit()
    finally:
        await session.close()
    return _version_response(row)


async def promote_version(
    organization_id: UUID, workflow_id: UUID, version_id: UUID, status: str
) -> dict | None:
    """Mueve una versión en el ciclo de vida. None = versión inexistente."""
    if status not in VERSION_STATUSES:
        raise ValueError(f"status debe ser uno de {VERSION_STATUSES}")
    await ensure_workflow_versions_table()
    session = await get_async_session()
    try:
        current = (
            await session.execute(
                text(
                    "SELECT status FROM workflow_versions WHERE id = :vid "
                    "AND workflow_id = :wid AND organization_id = :oid"
                ),
                {"vid": version_id, "wid": workflow_id, "oid": organization_id},
            )
        ).fetchone()
        if current is None:
            return None
        if not validate_transition(current.status, status):
            raise ValueError(
                f"transición inválida: {current.status} → {status}"
            )
        row = (
            await session.execute(
                text(
                    "UPDATE workflow_versions SET status = :status WHERE id = :vid "
                    "RETURNING id, workflow_id, version_number, status, "
                    "config_snapshot, notes, created_by, created_at"
                ),
                {"status": status, "vid": version_id},
            )
        ).fetchone()
        if status == "production":
            await _demote_other_productions(
                session, organization_id, workflow_id, version_id
            )
        await session.commit()
    finally:
        await session.close()
    return _version_response(row)


async def restore_version(
    organization_id: UUID, workflow_id: UUID, version_id: UUID
) -> dict | None:
    """Rollback: copia el snapshot a la fila viva. None = versión inexistente.

    El grafo legacy (graph_source='legacy') se restaura desde `steps` para que
    el adapter regenere el grafo y no promueva el workflow a IR v2.
    """
    await ensure_workflow_versions_table()
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT version_number, config_snapshot FROM workflow_versions "
                    "WHERE id = :vid AND workflow_id = :wid AND organization_id = :oid"
                ),
                {"vid": version_id, "wid": workflow_id, "oid": organization_id},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        return None
    snapshot = row.config_snapshot if isinstance(row.config_snapshot, dict) else {}

    from src.platform.workflows.engine import update_workflow

    legacy = str(snapshot.get("graph_source") or "graph") == "legacy"
    updated = await update_workflow(
        organization_id,
        workflow_id,
        snapshot.get("name"),
        snapshot.get("description"),
        snapshot.get("trigger_config") or {},
        snapshot.get("steps") or [],
        snapshot.get("editor_state") or {},
        graph=None if legacy else (snapshot.get("graph") or None),
        workflow_version=snapshot.get("workflow_version"),
        trigger_type=snapshot.get("trigger_type"),
    )
    if updated is None:
        return None
    return {
        "restored": True,
        "workflow_id": str(workflow_id),
        "version_id": str(version_id),
        "version_number": int(row.version_number),
    }


async def publish_workflow(
    organization_id: UUID,
    workflow_id: UUID,
    *,
    notes: str | None = None,
    created_by: UUID | None = None,
) -> dict | None:
    """Publicar = snapshot en production + workflow activo (webhook/schedule)."""
    from src.platform.workflows.engine import set_workflow_status

    version = await create_version(
        organization_id,
        workflow_id,
        notes=notes,
        created_by=created_by,
        status="production",
    )
    if version is None:
        return None
    status = await set_workflow_status(organization_id, workflow_id, "active")
    return {
        "workflow_id": str(workflow_id),
        "status": (status or {}).get("status", "active"),
        "version": version,
    }
