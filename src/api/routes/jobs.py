# =============================================================================
# Jobs Routes — Estado, retry y cancel de ingestion jobs (Knowledge Platform)
# =============================================================================
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from src.api.deps import get_job_repo
from src.core.domain.entities import IngestionJobStatus
from src.core.ports import IngestionJobRepository
from src.infrastructure.postgres.relational_db import PostgresAuditLogRepository
from src.platform.audit.service import AuditLogService

router = APIRouter(prefix="/api/v1/jobs", tags=["Knowledge Jobs"])


def _audit() -> AuditLogService:
    return AuditLogService(PostgresAuditLogRepository())


def _job_response(job) -> dict:
    return {
        "id": str(job.id),
        "job_type": job.job_type,
        "status": job.status.value,
        "progress": job.progress,
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
        "records_processed": job.records_processed,
        "records_failed": job.records_failed,
        "error_summary": job.error_summary,
        "source_id": str(job.source_id) if job.source_id else None,
        "knowledge_base_id": str(job.knowledge_base_id) if job.knowledge_base_id else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "retry_at": job.retry_at.isoformat() if job.retry_at else None,
        "created_at": job.created_at.isoformat(),
    }


@router.get("", summary="Listar ingestion jobs de la organización")
async def list_jobs(
    request: Request,
    status: str | None = Query(default=None, pattern=r"^(pending|running|completed|failed|dead|canceled)$"),
    source_id: UUID | None = Query(default=None),
    knowledge_base_id: UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    repo: IngestionJobRepository = Depends(get_job_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "sources:read")
    jobs = await repo.list_jobs(
        ctx.organization_id,
        status=status,
        source_id=source_id,
        knowledge_base_id=knowledge_base_id,
        limit=limit,
    )
    return {"jobs": [_job_response(j) for j in jobs], "count": len(jobs)}


@router.get("/{job_id}", summary="Estado de un ingestion job")
async def get_job(
    job_id: str,
    request: Request,
    repo: IngestionJobRepository = Depends(get_job_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "sources:read")
    try:
        jid = UUID(job_id)
    except ValueError:
        raise HTTPException(400, "job_id must be a valid UUID")
    job = await repo.get_job(ctx.organization_id, jid)
    if job is None:
        raise HTTPException(404, "Job not found")
    return _job_response(job)


@router.post("/{job_id}/retry", summary="Reintentar un job (failed/dead)")
async def retry_job(
    job_id: str,
    request: Request,
    repo: IngestionJobRepository = Depends(get_job_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "sources:write")
    try:
        jid = UUID(job_id)
    except ValueError:
        raise HTTPException(400, "job_id must be a valid UUID")
    job = await repo.get_job(ctx.organization_id, jid)
    if job is None:
        raise HTTPException(404, "Job not found")
    if job.status not in (IngestionJobStatus.FAILED, IngestionJobStatus.DEAD):
        raise HTTPException(409, f"Job is {job.status.value}; only failed/dead jobs can be retried")

    await repo.update_job(
        jid,
        status=IngestionJobStatus.PENDING.value,
        retry_at=None,
        attempts=0,
        error_summary={},
    )
    from src.knowledge.queue import enqueue_knowledge_job

    await enqueue_knowledge_job(str(jid))
    await _audit().write(ctx, "job.retried", "ingestion_job", jid)
    return {"job_id": str(jid), "status": "pending"}


@router.post("/{job_id}/cancel", summary="Cancelar un job pendiente/fallido")
async def cancel_job(
    job_id: str,
    request: Request,
    repo: IngestionJobRepository = Depends(get_job_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "sources:write")
    try:
        jid = UUID(job_id)
    except ValueError:
        raise HTTPException(400, "job_id must be a valid UUID")
    job = await repo.get_job(ctx.organization_id, jid)
    if job is None:
        raise HTTPException(404, "Job not found")
    if job.is_terminal and job.status == IngestionJobStatus.CANCELED:
        raise HTTPException(409, "Job is already canceled")

    await repo.update_job(
        jid,
        status=IngestionJobStatus.CANCELED.value,
        completed_at=datetime.now(timezone.utc),
    )
    await _audit().write(ctx, "job.canceled", "ingestion_job", jid)
    return {"job_id": str(jid), "status": "canceled"}
