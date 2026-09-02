# =============================================================================
# Training Runs — pipeline de entrenamiento de una Knowledge Base
# =============================================================================
from __future__ import annotations

import asyncio
import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.api.deps import get_job_repo, get_kb_repo
from src.core.ports import IngestionJobRepository, KnowledgeBaseRepository
from src.infrastructure.observability.logging_config import get_logger
from src.platform.knowledge.training import (
    aggregate_run,
    create_training_run,
    get_training_run,
    list_training_runs,
    start_run_jobs,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/training", tags=["Training"])


class CreateTrainingRunRequest(BaseModel):
    knowledge_base_id: UUID
    notes: str | None = Field(default=None, max_length=2000)


@router.post("/runs", status_code=201, summary="Crear training run (encola jobs)")
async def create_run(
    body: CreateTrainingRunRequest,
    request: Request,
    jobs: IngestionJobRepository = Depends(get_job_repo),
    kb_repo: KnowledgeBaseRepository = Depends(get_kb_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "rag:ingest")
    kb = await kb_repo.get_kb(ctx.organization_id, body.knowledge_base_id)
    if kb is None:
        raise HTTPException(404, "Knowledge base not found")
    run = await create_training_run(
        ctx.organization_id, body.knowledge_base_id, created_by=ctx.user_id
    )
    enqueued = await start_run_jobs(ctx.organization_id, run, jobs)
    run["jobs"] = enqueued
    return {"run": run, "job_count": len(enqueued)}


@router.get("/runs", summary="Listar training runs (agregados)")
async def list_runs(request: Request):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "rag:read")
    runs = await list_training_runs(ctx.organization_id, limit=50)
    refreshed = []
    for run in runs[:20]:
        refreshed.append(await aggregate_run(ctx.organization_id, UUID(run["id"])) or run)
    return {"runs": refreshed, "count": len(refreshed)}


@router.get("/runs/{run_id}", summary="Estado agregado de un training run")
async def get_run(run_id: str, request: Request):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "rag:read")
    try:
        rid = UUID(run_id)
    except ValueError:
        raise HTTPException(400, "run_id must be a valid UUID")
    run = await aggregate_run(ctx.organization_id, rid)
    if run is None:
        raise HTTPException(404, "Training run not found")
    return {"run": run}


@router.get("/runs/{run_id}/stream", summary="Progreso live del training run (SSE)")
async def stream_run(run_id: str, request: Request):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "rag:read")
    try:
        rid = UUID(run_id)
    except ValueError:
        raise HTTPException(400, "run_id must be a valid UUID")
    if await get_training_run(ctx.organization_id, rid) is None:
        raise HTTPException(404, "Training run not found")

    async def event_stream():
        terminal = False
        while not terminal:
            run = await aggregate_run(ctx.organization_id, rid)
            if run is None:
                yield f"event: error\ndata: {json.dumps({'message': 'run not found'})}\n\n"
                return
            yield (
                f"event: progress\n"
                f"data: {json.dumps(run, default=str)}\n\n"
            )
            terminal = run["status"] in ("completed", "failed")
            if not terminal:
                await asyncio.sleep(1.5)
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
