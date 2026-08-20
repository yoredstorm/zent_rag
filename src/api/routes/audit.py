# =============================================================================
# Audit Log Routes — Lectura de auditoría (organization-scoped)
# =============================================================================
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from src.api.deps import get_audit_repo
from src.core.ports import AuditLogRepository
from src.platform.audit.service import AuditLogService

router = APIRouter(prefix="/api/v1/audit-logs", tags=["Audit"])


@router.get("", summary="Audit logs de la organización autenticada")
async def list_audit_logs(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    resource_type: str | None = Query(default=None, max_length=100),
    repo: AuditLogRepository = Depends(get_audit_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "audit:read")
    service = AuditLogService(repo)
    entries = await service.list_entries(
        ctx,
        limit=limit,
        offset=offset,
        resource_type=resource_type,
    )
    return {
        "entries": [
            {
                "id": None,  # BIGSERIAL no se expone; created_at + resource bastan
                "action": e.action,
                "resource_type": e.resource_type,
                "resource_id": e.resource_id,
                "actor_user_id": str(e.actor_user_id) if e.actor_user_id else None,
                "ip_address": e.ip_address,
                "metadata": e.metadata,
                "created_at": e.created_at.isoformat(),
            }
            for e in entries
        ],
        "count": len(entries),
    }
