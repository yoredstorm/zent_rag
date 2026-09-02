# =============================================================================
# Training Runs — ejecuciones de pipeline (prepare → chunk → embed → index)
# =============================================================================
# Un training run agrupa jobs de ingestión de una KB y agrega su progreso.
# Reutiliza la cola durable de knowledge jobs; el worker no conoce runs.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from sqlalchemy import text

from src.core.ports import IngestionJobRepository
from src.infrastructure.postgres.session import get_async_session

_RUN_COLS = (
    "id, organization_id, knowledge_base_id, status, current_step, progress, "
    "rows_processed, vectors_upserted, errors, error_summary, created_by, "
    "created_at, started_at, finished_at"
)


def _row_to_run(row) -> dict:
    return {
        "id": str(row.id),
        "knowledge_base_id": str(row.knowledge_base_id),
        "status": row.status,
        "current_step": row.current_step,
        "progress": int(row.progress),
        "rows_processed": int(row.rows_processed),
        "vectors_upserted": int(row.vectors_upserted),
        "errors": int(row.errors),
        "error_summary": row.error_summary,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
    }


async def create_training_run(
    organization_id: UUID,
    knowledge_base_id: UUID,
    created_by: UUID | None = None,
) -> dict:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(  # noqa: S608 (_RUN_COLS es constante del módulo)
                    f"INSERT INTO training_runs (id, organization_id, knowledge_base_id, "
                    f"created_by) VALUES (uuid_generate_v4(), :oid, :kid, :by) "
                    f"RETURNING {_RUN_COLS}"
                ),
                {"oid": organization_id, "kid": knowledge_base_id, "by": created_by},
            )
        ).fetchone()
        await session.commit()
        return _row_to_run(row)
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def update_run_progress(
    organization_id: UUID,
    run_id: UUID,
    *,
    status: str | None = None,
    current_step: str | None = None,
    progress: int | None = None,
    rows_processed: int | None = None,
    vectors_upserted: int | None = None,
    errors: int | None = None,
    error_summary: str | None = None,
    finished: bool = False,
) -> None:
    sets: list[str] = []
    params: dict = {"oid": organization_id, "rid": run_id}
    if status is not None:
        sets.append("status = :status")
        params["status"] = status
    if current_step is not None:
        sets.append("current_step = :step")
        params["step"] = current_step
    if progress is not None:
        sets.append("progress = :progress")
        params["progress"] = max(0, min(100, progress))
    if rows_processed is not None:
        sets.append("rows_processed = :rows")
        params["rows"] = rows_processed
    if vectors_upserted is not None:
        sets.append("vectors_upserted = :vectors")
        params["vectors"] = vectors_upserted
    if errors is not None:
        sets.append("errors = :errors")
        params["errors"] = errors
    if error_summary is not None:
        sets.append("error_summary = :esum")
        params["esum"] = error_summary
    if sets:
        sets.append("started_at = COALESCE(started_at, NOW())")
        if finished:
            sets.append("finished_at = NOW()")
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    f"UPDATE training_runs SET {', '.join(sets)} "
                    "WHERE id = :rid AND organization_id = :oid"
                ),
                params,
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def list_training_runs(organization_id: UUID, limit: int = 100) -> list[dict]:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    f"SELECT {_RUN_COLS} FROM training_runs "
                    "WHERE organization_id = :oid "
                    "ORDER BY created_at DESC LIMIT :limit"
                ),
                {"oid": organization_id, "limit": limit},
            )
        ).fetchall()
    finally:
        await session.close()
    return [_row_to_run(r) for r in rows]


async def get_training_run(organization_id: UUID, run_id: UUID) -> dict | None:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    f"SELECT {_RUN_COLS} FROM training_runs "
                    "WHERE id = :rid AND organization_id = :oid"
                ),
                {"rid": run_id, "oid": organization_id},
            )
        ).fetchone()
    finally:
        await session.close()
    return _row_to_run(row) if row is not None else None


async def aggregate_run(
    organization_id: UUID, run_id: UUID
) -> dict | None:
    """Recalcula el estado del run desde sus jobs de ingestión."""
    run = await get_training_run(organization_id, run_id)
    if run is None:
        return None

    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT status, progress, records_processed, records_failed, "
                    "error_summary "
                    "FROM ingestion_jobs WHERE organization_id = :oid "
                    "AND training_run_id = :rid"
                ),
                {"oid": organization_id, "rid": run_id},
            )
        ).fetchall()
    finally:
        await session.close()

    if not rows:
        return run

    statuses = [r.status for r in rows]
    total = len(statuses)
    completed = sum(1 for s in statuses if s == "completed")
    failed = sum(1 for s in statuses if s in ("failed", "dead"))
    running = sum(1 for s in statuses if s in ("pending", "running"))

    if failed and running:
        run["status"] = "partial"
    elif failed:
        run["status"] = "failed"
    elif completed == total:
        run["status"] = "completed"
    else:
        run["status"] = "running"

    if run["status"] == "running" or running:
        run["current_step"] = "indexing"
    elif run["status"] == "completed":
        run["current_step"] = "validation"
    else:
        run["current_step"] = "preparation"

    run["progress"] = round(sum(int(r.progress or 0) for r in rows) / total)
    run["rows_processed"] = int(sum(int(r.records_processed or 0) for r in rows))
    run["vectors_upserted"] = int(sum(int(r.records_processed or 0) for r in rows))
    run["errors"] = int(sum(int(r.records_failed or 0) for r in rows))
    errors = [r.error_summary for r in rows if r.error_summary]
    run["error_summary"] = (errors[0] if errors else None) or run.get("error_summary")

    await update_run_progress(
        organization_id,
        run_id,
        status=run["status"],
        current_step=run["current_step"],
        progress=run["progress"],
        rows_processed=run["rows_processed"],
        vectors_upserted=run["vectors_upserted"],
        errors=run["errors"],
        finished=run["status"] in ("completed", "failed"),
    )
    return run


async def start_run_jobs(
    organization_id: UUID,
    run: dict,
    jobs: IngestionJobRepository,
) -> list[dict]:
    """Encola un job de sync por fuente activa de la KB y enlaza al run."""
    session = await get_async_session()
    try:
        sources = (
            await session.execute(
                text(
                    "SELECT id FROM kb_sources "
                    "WHERE organization_id = :oid AND knowledge_base_id = :kid "
                    "AND status <> 'ingesting'"
                ),
                {"oid": organization_id, "kid": UUID(run["knowledge_base_id"])},
            )
        ).fetchall()
    finally:
        await session.close()

    enqueued: list[dict] = []
    for (source_id,) in sources:
        job = await jobs.create_job(
            organization_id,
            job_type="sync_source:training",
            source_id=source_id,
            knowledge_base_id=UUID(run["knowledge_base_id"]),
            training_run_id=UUID(run["id"]),
        )
        from src.knowledge.queue import enqueue_knowledge_job

        await enqueue_knowledge_job(str(job.id))
        enqueued.append({"job_id": str(job.id), "source_id": str(source_id)})
    return enqueued
