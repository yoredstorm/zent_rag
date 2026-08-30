# =============================================================================
# Knowledge Bases Routes — CRUD (organization-scoped, project opcional)
# =============================================================================
# Configuración completa de chunking/retrieval de la Knowledge Platform:
# chunking_strategy (fixed|recursive|sentence), chunk_size, chunk_overlap,
# retrieval_strategy (vector), reranker, metadata_schema (validación de
# metadatos durante la ingestion).
# =============================================================================
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src.api.deps import get_kb_repo
from src.core.ports import KnowledgeBaseRepository
from src.infrastructure.postgres.relational_db import PostgresAuditLogRepository
from src.platform.audit.service import AuditLogService

router = APIRouter(prefix="/api/v1/knowledge-bases", tags=["Knowledge Bases"])


def _audit() -> AuditLogService:
    return AuditLogService(PostgresAuditLogRepository())


class CreateKbRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    project_id: UUID | None = None
    embedding_model: str | None = Field(default=None, max_length=100)
    chunking_strategy: str = Field(
        default="fixed", pattern=r"^(fixed|recursive|sentence)$"
    )
    chunk_size: int = Field(default=1200, ge=100, le=32000)
    chunk_overlap: int = Field(default=150, ge=0, le=4000)
    retrieval_strategy: str = Field(default="vector", pattern=r"^(vector|hybrid)$")
    reranker: str | None = Field(default=None, max_length=50)
    metadata_schema: dict = Field(default_factory=dict)


class UpdateKbRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    project_id: UUID | None = None
    status: str | None = Field(default=None, pattern=r"^(active|archived)$")
    embedding_model: str | None = Field(default=None, max_length=100)
    chunking_strategy: str | None = Field(default=None, pattern=r"^(fixed|recursive|sentence)$")
    chunk_size: int | None = Field(default=None, ge=100, le=32000)
    chunk_overlap: int | None = Field(default=None, ge=0, le=4000)
    retrieval_strategy: str | None = Field(default=None, pattern=r"^(vector|hybrid)$")
    reranker: str | None = Field(default=None, max_length=50)
    metadata_schema: dict | None = None


def _kb_response(kb) -> dict:
    return {
        "id": str(kb.id),
        "name": kb.name,
        "description": kb.description,
        "project_id": str(kb.project_id) if kb.project_id else None,
        "status": kb.status,
        "embedding_model": kb.embedding_model,
        "chunking_strategy": kb.chunking_strategy,
        "chunk_size": kb.chunk_size,
        "chunk_overlap": kb.chunk_overlap,
        "retrieval_strategy": kb.retrieval_strategy,
        "reranker": kb.reranker,
        "metadata_schema": kb.metadata_schema,
        "created_at": kb.created_at.isoformat(),
    }


@router.get("", summary="Listar knowledge bases")
async def list_kbs(
    request: Request,
    repo: KnowledgeBaseRepository = Depends(get_kb_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "kbs:read")
    kbs = await repo.list_kbs(ctx.organization_id)
    return {"knowledge_bases": [_kb_response(k) for k in kbs], "count": len(kbs)}


@router.post("", status_code=201, summary="Crear knowledge base")
async def create_kb(
    body: CreateKbRequest,
    request: Request,
    repo: KnowledgeBaseRepository = Depends(get_kb_repo),
):
    from src.platform.billing.plan_limits import (
        PlanLimitError,
        check_resource_limit,
        plan_limit_detail,
    )
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "kbs:write")
    try:
        await check_resource_limit(ctx.organization_id, "knowledge_bases")
    except PlanLimitError as exc:
        raise HTTPException(status_code=409, detail=plan_limit_detail(exc)) from None
    if body.project_id is not None:
        await _require_own_project(ctx, body.project_id)
    kb = await repo.create_kb(
        ctx.organization_id,
        body.name,
        description=body.description,
        project_id=body.project_id,
        embedding_model=body.embedding_model,
        chunking_strategy=body.chunking_strategy,
        chunk_size=body.chunk_size,
        chunk_overlap=body.chunk_overlap,
        retrieval_strategy=body.retrieval_strategy,
        reranker=body.reranker,
        metadata_schema=body.metadata_schema,
    )
    await _audit().write(ctx, "kb.created", "knowledge_base", kb.id, metadata={"name": kb.name})
    return _kb_response(kb)


@router.get("/{kb_id}", summary="Obtener knowledge base")
async def get_kb(
    kb_id: str,
    request: Request,
    repo: KnowledgeBaseRepository = Depends(get_kb_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "kbs:read")
    try:
        kid = UUID(kb_id)
    except ValueError:
        raise HTTPException(400, "kb_id must be a valid UUID")
    kb = await repo.get_kb(ctx.organization_id, kid)
    if kb is None:
        raise HTTPException(404, "Knowledge base not found")
    return _kb_response(kb)


@router.put("/{kb_id}", summary="Actualizar knowledge base")
async def update_kb(
    kb_id: str,
    body: UpdateKbRequest,
    request: Request,
    repo: KnowledgeBaseRepository = Depends(get_kb_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "kbs:write")
    try:
        kid = UUID(kb_id)
    except ValueError:
        raise HTTPException(400, "kb_id must be a valid UUID")
    if body.project_id is not None:
        await _require_own_project(ctx, body.project_id)
    try:
        kb = await repo.update_kb(ctx.organization_id, kid, **body.model_dump(exclude_none=True))
    except ValueError:
        raise HTTPException(404, "Knowledge base not found")
    await _audit().write(ctx, "kb.updated", "knowledge_base", kid, metadata={"name": kb.name})
    return _kb_response(kb)


@router.delete("/{kb_id}", summary="Eliminar knowledge base (y sus vectores)")
async def delete_kb(
    kb_id: str,
    request: Request,
    repo: KnowledgeBaseRepository = Depends(get_kb_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "kbs:write")
    try:
        kid = UUID(kb_id)
    except ValueError:
        raise HTTPException(400, "kb_id must be a valid UUID")
    kb = await repo.get_kb(ctx.organization_id, kid)
    if kb is None:
        raise HTTPException(404, "Knowledge base not found")

    await repo.delete_kb(ctx.organization_id, kid)
    # Purga de vectores SIEMPRE scoped a (organization, kb) — jamás org-cruzado.
    from src.api.deps import get_vector_store

    vs = get_vector_store()
    try:
        await vs.delete_by_knowledge_base(ctx.organization_id, kid)
    except Exception:
        raise HTTPException(500, "Failed to purge knowledge base vectors")
    await _audit().write(ctx, "kb.deleted", "knowledge_base", kid, metadata={"name": kb.name})
    return {"status": "deleted", "kb_id": str(kid)}


async def _require_own_project(ctx, project_id: UUID) -> None:
    """El project_id (si viene) debe pertenecer a la organización autenticada."""
    from src.api.deps import get_project_repo

    project = await get_project_repo().get_project(ctx.organization_id, project_id)
    if project is None:
        raise HTTPException(404, "Project not found in this organization")
