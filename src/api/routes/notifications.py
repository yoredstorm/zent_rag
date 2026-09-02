# =============================================================================
# Multi-Tenant Notifications v2 — centro in-app, preferencias y entregas.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/notifications", tags=["Notifications"])


@router.get("", summary="Notificaciones del tenant")
async def tenant_notifications_list(
    request: Request,
    unread_only: bool = False,
    event_type: str | None = None,
    hours: int = 168,
):
    from src.platform.notifyv2.notifications import list_notifications
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:read")
    return await list_notifications(
        ctx.organization_id,
        unread_only=unread_only,
        event_type=event_type,
        hours=hours,
    )


@router.get("/unread-count", summary="No leídas")
async def tenant_notifications_unread(request: Request):
    from src.platform.notifyv2.notifications import unread_count
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:read")
    return {"count": await unread_count(ctx.organization_id)}


@router.post("/read-all", summary="Marcar todo leído")
async def tenant_notifications_read_all(request: Request):
    from src.platform.notifyv2.notifications import mark_all_read
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:read")
    return {"marked": await mark_all_read(ctx.organization_id)}


@router.post("/{notification_id}/read", summary="Marcar como leída")
async def tenant_notification_read(notification_id: str, request: Request):
    from src.platform.notifyv2.notifications import mark_read
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:read")
    ok = await mark_read(ctx.organization_id, UUID(notification_id))
    if not ok:
        raise HTTPException(404, "Notification not found or already read")
    return {"status": "read"}


@router.post("/{notification_id}/archive", summary="Archivar")
async def tenant_notification_archive(notification_id: str, request: Request):
    from src.platform.notifyv2.notifications import archive
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:read")
    ok = await archive(ctx.organization_id, UUID(notification_id))
    if not ok:
        raise HTTPException(404, "Notification not found")
    return {"status": "archived"}


@router.get("/preferences", summary="Preferencias por canal")
async def tenant_notifications_preferences(request: Request):
    from src.platform.notifyv2.notifications import get_preferences
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:read")
    return await get_preferences(ctx.organization_id)


@router.put("/preferences", summary="Actualizar preferencias")
async def tenant_notifications_preferences_put(body: NotificationPreferencesIn, request: Request):
    from src.platform.notifyv2.notifications import update_preferences
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:write")
    return await update_preferences(ctx.organization_id, body.channels, body.events)


@router.get("/deliveries", summary="Entregas de webhook del tenant")
async def tenant_notifications_deliveries(
    request: Request, status: str | None = None, hours: int = 168
):
    from src.platform.notifyv2.notifications import list_deliveries
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:read")
    return await list_deliveries(ctx.organization_id, status, hours)


class NotificationPreferencesIn(BaseModel):
    channels: dict | None = None
    events: dict = Field(default_factory=dict)
