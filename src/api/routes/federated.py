# =============================================================================
# Federated Search — POST /api/v1/rag/federated
# =============================================================================
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from src.api.deps import get_embedding_provider, get_vector_store

router = APIRouter(prefix="/api/v1/rag", tags=["rag"])


class FederatedSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    knowledge_base_ids: list[str] | None = None
    workspace_ids: list[str] | None = None
    top_k: int = Field(default=10, ge=1, le=50)
    per_kb_top: int = Field(default=10, ge=1, le=30)


@router.post("/federated", summary="Búsqueda federada cross-KB con ranking unificado")
async def federated_search_endpoint(
    body: FederatedSearchRequest,
    request: Request,
    vector_store=Depends(get_vector_store),
    embedding_provider=Depends(get_embedding_provider),
):
    from src.platform.federated.search import federated_search
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "rag:read")
    kb_ids = [UUID(x) for x in body.knowledge_base_ids] if body.knowledge_base_ids else None
    ws_ids = [UUID(x) for x in body.workspace_ids] if body.workspace_ids else None
    return await federated_search(
        organization_id=ctx.organization_id,
        query=body.query,
        vector_store=vector_store,
        embedding_provider=embedding_provider,
        knowledge_base_ids=kb_ids,
        workspace_ids=ws_ids,
        top_k=body.top_k,
        per_kb_top=body.per_kb_top,
    )
