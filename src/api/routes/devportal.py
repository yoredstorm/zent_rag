# =============================================================================
# Developer Experience (tenant + público)
# Webhooks salientes, SDK reference y status/changelog público.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1", tags=["dev"])


class WebhookIn(BaseModel):
    event_type: str = Field(..., pattern="^[a-z0-9_.-]{3,60}$")
    url: str = Field(..., min_length=8, max_length=500)
    secret: str | None = Field(default=None, min_length=8, max_length=200)


@router.post("/webhooks", status_code=201, summary="Suscribir webhook saliente")
async def create_webhook(body: WebhookIn, request: Request):
    from src.platform.devportal.sdk import subscribe_webhook
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "agents:write")
    try:
        return await subscribe_webhook(ctx.organization_id, body.event_type, body.url, body.secret)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/webhooks", summary="Listar webhooks de la organización")
async def list_webhooks(request: Request):
    from src.platform.devportal.sdk import list_webhooks as _list
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "agents:read")
    webhooks = await _list(ctx.organization_id)
    return {"webhooks": webhooks, "count": len(webhooks)}


@router.delete("/webhooks/{webhook_id}", summary="Eliminar webhook")
async def delete_webhook(webhook_id: str, request: Request):
    from src.platform.devportal.sdk import delete_webhook as _delete
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "agents:write")
    ok = await _delete(ctx.organization_id, UUID(webhook_id))
    if not ok:
        raise HTTPException(404, "Webhook not found")
    return {"status": "deleted"}


@router.post("/webhooks/{webhook_id}/test", summary="Enviar ping de prueba")
async def test_webhook(webhook_id: str, request: Request):
    from src.platform.devportal.sdk import test_webhook as _test
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "agents:write")
    result = await _test(ctx.organization_id, UUID(webhook_id))
    if result["status"] == "not_found":
        raise HTTPException(404, "Webhook not found")
    return result


@router.get("/dev/sdk-reference", summary="Referencia SDK (tenant)")
async def tenant_sdk_reference(request: Request):
    from src.platform.devportal.sdk import sdk_reference

    return await sdk_reference()


@router.get("/dev/status", summary="Estado público del platform (sin auth)")
async def public_dev_status():
    from src.platform.devportal.sdk import platform_status

    return await platform_status()


@router.get("/dev/changelog", summary="Changelog público (sin auth)")
async def public_dev_changelog():
    from src.platform.devportal.sdk import list_changelog

    entries = await list_changelog(public_only=True)
    return {"changelog": entries, "count": len(entries)}
