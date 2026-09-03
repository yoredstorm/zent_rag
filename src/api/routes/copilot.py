# =============================================================================
# AI Copilot & Assistant Platform v2 — marketplace, chat, sugerencias.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/copilot", tags=["Copilot"])


@router.get("/marketplace", summary="Marketplace de agentes pre-entrenados")
async def copilot_marketplace(request: Request, category: str | None = None):
    from src.platform.copilot.copilot import list_marketplace
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:read")
    return await list_marketplace(category)


@router.post("/marketplace/install", summary="Instalar agente del marketplace")
async def copilot_marketplace_install(body: InstallIn, request: Request):
    from src.platform.copilot.copilot import install_marketplace
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:write")
    try:
        return await install_marketplace(ctx.organization_id, body.slug)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/marketplace/installs", summary="Instalaciones del tenant")
async def copilot_installs(request: Request):
    from src.platform.copilot.copilot import my_installs
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:read")
    return await my_installs(ctx.organization_id)


@router.post("/marketplace/{install_id}/remove", summary="Desinstalar agente")
async def copilot_marketplace_remove(install_id: str, request: Request):
    from src.platform.copilot.copilot import remove_install
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:write")
    return await remove_install(ctx.organization_id, UUID(install_id))


@router.post("/chat", summary="Mensaje al copilot (router por intención)")
async def copilot_chat(body: ChatIn, request: Request):
    from src.platform.copilot.copilot import chat
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:read")
    return await chat(
        ctx.organization_id,
        ctx.user_id,
        body.message,
        UUID(body.session_id) if body.session_id else None,
        body.title or None,
    )


@router.get("/sessions", summary="Sesiones del tenant")
async def copilot_sessions(request: Request):
    from src.platform.copilot.copilot import list_sessions
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:read")
    return await list_sessions(ctx.organization_id)


@router.get("/sessions/{session_id}", summary="Mensajes de una sesión")
async def copilot_session_messages(session_id: str, request: Request):
    from src.platform.copilot.copilot import session_messages
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:read")
    result = await session_messages(ctx.organization_id, UUID(session_id))
    if result is None:
        raise HTTPException(404, "Session not found")
    return result


@router.get("/automations/suggest", summary="Sugerencias de automatización")
async def copilot_automations(request: Request):
    from src.platform.copilot.copilot import suggest_automations
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:read")
    return await suggest_automations(ctx.organization_id)


class InstallIn(BaseModel):
    slug: str = Field(min_length=2, max_length=80)


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    session_id: str | None = None
    title: str | None = Field(default=None, max_length=200)
