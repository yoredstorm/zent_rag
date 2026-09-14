# =============================================================================
# Universal API Connector — API (misión §11-§16).
#
#   POST /api/v1/integrations/import/openapi   documento/url → borrador
#   GET  /api/v1/integrations/drafts           borradores del tenant
#   PATCH /drafts/{id}                          revisión humana (labels/auth/…)
#   POST  /drafts/{id}/install                  revisión → manifest + install
#
# El discovery NUNCA ejecuta endpoints de la API externa: sólo lee el
# documento OpenAPI. Las credenciales van al SecretStore existente.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/integrations", tags=["Conectores API"])


class OpenApiImportIn(BaseModel):
    url: str | None = Field(default=None, max_length=2048)
    document: str | dict | None = None
    format: str | None = Field(default=None, pattern="^(json|yaml)$")
    name: str | None = Field(default=None, max_length=150)


class DraftPatchIn(BaseModel):
    name: str | None = Field(default=None, max_length=150)
    description: str | None = Field(default=None, max_length=400)
    base_url: str | None = Field(default=None, max_length=500)
    auth_kind: str | None = Field(default=None, max_length=30)
    auth_header_name: str | None = Field(default=None, max_length=60)
    rate_limits: dict | None = None
    actions: list[dict] | None = None


async def _workspace_id(request: Request) -> UUID | None:
    from src.platform.workspaces.context import (
        get_active_workspace_id,
        workspace_header_or_none,
    )

    ctx = getattr(request.state, "tenant_context", None)
    if ctx is None:
        return None
    header = workspace_header_or_none(request)
    if header is not None:
        return header
    try:
        active = await get_active_workspace_id(ctx.organization_id, ctx.user_id)
        if active is not None:
            return active
    except Exception:  # noqa: BLE001
        pass
    return None


def _require(request: Request, permission: str):
    from src.platform.rbac.policy import require_permission

    return require_permission(request, permission)


def _as_uuid(value: str) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise HTTPException(404, "Borrador no encontrado") from exc


@router.post("/import/openapi", status_code=201, summary="Importar OpenAPI → borrador")
async def connector_import_openapi(body: OpenApiImportIn, request: Request):
    ctx = _require(request, "marketplace:install")
    from src.platform.marketplace.connector_drafts import DraftError, create_draft
    from src.platform.marketplace.openapi_import import (
        OpenApiImportError,
        build_draft,
        fetch_openapi_document,
        parse_openapi_document,
    )

    has_url = bool(body.url)
    has_document = body.document is not None and body.document != ""
    if has_url == has_document:
        raise HTTPException(422, "Envía una URL o el documento OpenAPI (no ambos).")

    try:
        if has_url:
            text = await fetch_openapi_document(str(body.url))
            document = parse_openapi_document(text, format_hint=body.format)
            source_kind, source_url = "url", str(body.url)
        else:
            document = parse_openapi_document(body.document, format_hint=body.format)
            source_kind, source_url = "document", None
        draft = build_draft(
            document,
            source_kind=source_kind,
            source_url=source_url,
            name_override=body.name,
        )
        saved = await create_draft(
            ctx.organization_id,
            draft,
            workspace_id=await _workspace_id(request),
            created_by=ctx.user_id,
        )
    except OpenApiImportError as exc:
        raise HTTPException(400, f"{exc.code}: {exc}") from exc
    except DraftError as exc:
        raise HTTPException(400, str(exc)) from exc
    saved["draft"] = draft
    saved["counts"] = {
        "capabilities": len(draft.get("capabilities") or []),
        "actions": sum(len(c.get("actions") or []) for c in draft.get("capabilities") or []),
    }
    return saved


@router.get("/drafts", summary="Borradores de importación")
async def connector_list_drafts(request: Request, status: str | None = None):
    ctx = _require(request, "marketplace:read")
    from src.platform.marketplace.connector_drafts import list_drafts

    return await list_drafts(ctx.organization_id, status=status)


@router.get("/drafts/{draft_id}", summary="Detalle de borrador")
async def connector_get_draft(draft_id: str, request: Request):
    ctx = _require(request, "marketplace:read")
    from src.platform.marketplace.connector_drafts import get_draft

    result = await get_draft(ctx.organization_id, _as_uuid(draft_id))
    if result is None:
        raise HTTPException(404, "Borrador no encontrado")
    return result


@router.patch("/drafts/{draft_id}", summary="Revisar borrador (labels, auth, mapping)")
async def connector_update_draft(draft_id: str, body: DraftPatchIn, request: Request):
    ctx = _require(request, "marketplace:install")
    from src.platform.marketplace.connector_drafts import DraftError, update_draft
    from src.platform.marketplace.openapi_import import OpenApiImportError

    try:
        result = await update_draft(
            ctx.organization_id, _as_uuid(draft_id), body.model_dump(exclude_unset=True)
        )
    except (DraftError, OpenApiImportError) as exc:
        raise HTTPException(400, str(exc)) from exc
    if result is None:
        raise HTTPException(404, "Borrador no encontrado")
    return result


@router.delete("/drafts/{draft_id}", summary="Descartar borrador")
async def connector_delete_draft(draft_id: str, request: Request):
    ctx = _require(request, "marketplace:install")
    from src.platform.marketplace.connector_drafts import discard_draft

    if not await discard_draft(ctx.organization_id, _as_uuid(draft_id)):
        raise HTTPException(404, "Borrador no encontrado")
    return {"discarded": True}


@router.post("/drafts/{draft_id}/install", summary="Instalar integración revisada")
async def connector_install_draft(draft_id: str, request: Request):
    ctx = _require(request, "marketplace:install")
    from src.platform.marketplace.connector_drafts import (
        DraftError,
        DraftNotFound,
        install_draft,
    )
    from src.platform.marketplace.runtime import PurposeRequiredError

    try:
        result = await install_draft(
            ctx.organization_id,
            _as_uuid(draft_id),
            workspace_id=await _workspace_id(request),
            created_by=ctx.user_id,
        )
    except DraftNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except PurposeRequiredError as exc:
        raise HTTPException(422, str(exc)) from exc
    except DraftError as exc:
        raise HTTPException(400, str(exc)) from exc
    return result
