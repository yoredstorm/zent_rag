# =============================================================================
# Workflow Samples — últimos outputs reales por nodo para el Data Picker y el
# Live Preview (misión §10-§12). Solo lectura: reutiliza
# workflow_runs/workflow_run_steps; NUNCA inventa datos de ejemplo.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from sqlalchemy import text

from src.infrastructure.postgres.session import get_async_session


async def latest_node_outputs(
    organization_id: UUID,
    workflow_id: UUID,
    *,
    run_id: UUID | None = None,
) -> dict | None:
    """Devuelve {run_id, status, nodes: {node_id: {status, output}}} del run más
    reciente (o del run indicado). None si el workflow no existe en la org."""
    session = await get_async_session()
    try:
        workflow = (
            await session.execute(
                text(
                    "SELECT name, status FROM workflows "
                    "WHERE id = :wid AND organization_id = :oid"
                ),
                {"wid": workflow_id, "oid": organization_id},
            )
        ).fetchone()
        if workflow is None:
            return None

        if run_id is not None:
            run = (
                await session.execute(
                    text(
                        "SELECT id, status, started_at, completed_at, trigger_payload "
                        "FROM workflow_runs "
                        "WHERE id = :rid AND workflow_id = :wid AND organization_id = :oid"
                    ),
                    {"rid": run_id, "wid": workflow_id, "oid": organization_id},
                )
            ).fetchone()
        else:
            run = (
                await session.execute(
                    text(
                        "SELECT id, status, started_at, completed_at, trigger_payload "
                        "FROM workflow_runs "
                        "WHERE workflow_id = :wid AND organization_id = :oid "
                        "ORDER BY started_at DESC LIMIT 1"
                    ),
                    {"wid": workflow_id, "oid": organization_id},
                )
            ).fetchone()

        nodes: dict[str, dict] = {}
        if run is not None:
            rows = (
                await session.execute(
                    text(
                        "SELECT node_id, node_type, status, output FROM workflow_run_steps "
                        "WHERE run_id = :rid AND node_id IS NOT NULL ORDER BY step_index"
                    ),
                    {"rid": run.id},
                )
            ).fetchall()
            for row in rows:
                nodes[str(row.node_id)] = {
                    "node_type": row.node_type,
                    "status": row.status,
                    "output": row.output or {},
                }
    finally:
        await session.close()

    return {
        "workflow_id": str(workflow_id),
        "workflow_name": workflow.name,
        "workflow_status": workflow.status,
        "run_id": str(run.id) if run is not None else None,
        "run_status": run.status if run is not None else None,
        "started_at": run.started_at.isoformat() if run is not None and run.started_at else None,
        "completed_at": (
            run.completed_at.isoformat() if run is not None and run.completed_at else None
        ),
        "trigger_payload": (run.trigger_payload or {}) if run is not None else {},
        "nodes": nodes,
    }


__all__ = ["latest_node_outputs"]
