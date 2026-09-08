# =============================================================================
# Data Onboarding Wizard — facade customer-facing (Phase 31A)
# =============================================================================
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field

from src.api.deps import get_rag_orchestrator
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.relational_db import PostgresAuditLogRepository
from src.platform.audit.service import AuditLogService
from src.platform.data_onboarding.constants import KINDS, READ_PERMS, WRITE_PERMS
from src.platform.data_onboarding.service import DataOnboardingError, DataOnboardingService
from src.platform.rbac.policy import get_ctx, require_permission

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/data-onboarding", tags=["Data Onboarding"])

_svc = DataOnboardingService()


def _audit() -> AuditLogService:
    return AuditLogService(PostgresAuditLogRepository())


def _require_any(request: Request, perms: tuple[str, ...]):
    from src.platform.auth.scopes import permission_satisfied

    ctx = get_ctx(request)
    if "admin:*" in ctx.scopes:
        return ctx
    for perm in perms:
        if ctx.has_permission(perm) or permission_satisfied(ctx.permissions, perm):
            return ctx
    raise HTTPException(
        status_code=403,
        detail={
            "error_code": "permission_denied",
            "message": f"Missing required permission: {perms[0]}",
        },
    )


def _org(request: Request) -> UUID:
    ctx = getattr(request.state, "tenant_context", None)
    if ctx is None or ctx.tenant_id is None:
        raise HTTPException(401, "Tenant context required")
    return ctx.tenant_id


def _handle(exc: DataOnboardingError) -> None:
    raise HTTPException(exc.status_code, str(exc)) from exc


class CreateSessionBody(BaseModel):
    kind: str = Field(..., min_length=1, max_length=32)
    workspace_id: UUID | None = None


class DatabaseConnectBody(BaseModel):
    name: str = Field(default="Base de datos", max_length=255)
    engine: str = Field(default="postgres")
    host: str = Field(..., min_length=1, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    database: str = Field(..., min_length=1, max_length=128)
    username: str = Field(..., min_length=1, max_length=128)
    password: str = Field(..., min_length=1, max_length=512)
    ssl: bool = False
    advanced: dict | None = None


class WebConnectBody(BaseModel):
    url: str = Field(..., min_length=8, max_length=2000)
    commit: bool = False


class ApiConnectBody(BaseModel):
    name: str = Field(default="API", max_length=255)
    base_url: str = Field(..., min_length=8, max_length=2000)
    auth: str = Field(default="none")
    token: str | None = None
    username: str | None = None
    password: str | None = None
    method: str = "GET"
    path: str = ""
    items_path: list[str] | None = None
    ssrf_allowlist: list[str] | None = None


class DriveStartBody(BaseModel):
    name: str = Field(default="Google Drive", max_length=255)


class DriveFolderBody(BaseModel):
    folder_id: str = Field(..., min_length=1, max_length=256)


class ReviewBody(BaseModel):
    action: str
    payload: dict | None = None


class FreeTextBody(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)


class AskBody(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)


class FeedbackBody(BaseModel):
    verdict: str
    reason: str | None = None
    question: str | None = None


@router.get("/gate", summary="¿Hay datos reales? (empty state)")
async def onboarding_gate(request: Request):
    _require_any(request, READ_PERMS)
    from src.platform.workspaces.context import resolve_workspace

    ws = await resolve_workspace(request)
    return await _svc.gate(
        _org(request), workspace_id=ws.id, workspace_kind=str(ws.kind.value)
    )


@router.post("/sessions", status_code=201, summary="Crear sesión de onboarding")
async def create_session(body: CreateSessionBody, request: Request):
    ctx = _require_any(request, WRITE_PERMS)
    if body.kind not in KINDS:
        raise HTTPException(400, f"kind must be one of {sorted(KINDS)}")
    from src.platform.workspaces.context import resolve_workspace

    ws = await resolve_workspace(request)
    try:
        session = await _svc.create_session(
            ctx.organization_id,
            body.kind,
            workspace_id=body.workspace_id or ws.id,
            created_by=ctx.user_id,
        )
    except DataOnboardingError as exc:
        _handle(exc)
    await _audit().write(
        ctx, "data_onboarding.started", "data_onboarding_session", UUID(session["id"]),
        metadata={"kind": body.kind},
    )
    return session


@router.get("/sessions", summary="Listar sesiones")
async def list_sessions(request: Request, status: str | None = Query(default=None)):
    ctx = _require_any(request, READ_PERMS)
    from src.platform.workspaces.context import resolve_workspace

    ws = await resolve_workspace(request)
    sessions = await _svc.list_sessions(
        ctx.organization_id, status=status, workspace_id=ws.id
    )
    return {"sessions": sessions, "count": len(sessions)}


@router.get("/sessions/{session_id}", summary="Reanudar sesión")
async def get_session(session_id: UUID, request: Request):
    ctx = _require_any(request, READ_PERMS)
    try:
        return await _svc.get_session(ctx.organization_id, session_id)
    except DataOnboardingError as exc:
        _handle(exc)


@router.post("/sessions/{session_id}/connect/database")
async def connect_database(session_id: UUID, body: DatabaseConnectBody, request: Request):
    ctx = require_permission(request, "connectors:write")
    try:
        result = await _svc.connect_database(
            ctx.organization_id, session_id, body.model_dump()
        )
    except DataOnboardingError as exc:
        _handle(exc)
    await _audit().write(
        ctx, "data_onboarding.connected", "connector",
        UUID(result["connector_id"]) if result.get("connector_id") else session_id,
        metadata={"kind": "database", "engine": body.engine},
    )
    return result


@router.post("/sessions/{session_id}/connect/upload")
async def connect_upload(
    session_id: UUID,
    request: Request,
    file: UploadFile = File(...),
):
    ctx = require_permission(request, "sources:write")
    data = await file.read()
    try:
        result = await _svc.connect_upload(
            ctx.organization_id,
            session_id,
            filename=file.filename or "upload.bin",
            data=data,
            created_by=ctx.user_id,
        )
    except DataOnboardingError as exc:
        _handle(exc)
    await _audit().write(
        ctx, "data_onboarding.uploaded", "source",
        UUID(result["kb_source_id"]) if result.get("kb_source_id") else session_id,
        metadata={"filename": file.filename},
    )
    return result


@router.post("/sessions/{session_id}/connect/web")
async def connect_web(session_id: UUID, body: WebConnectBody, request: Request):
    ctx = require_permission(request, "sources:write")
    try:
        result = await _svc.connect_web(
            ctx.organization_id, session_id, url=body.url, commit=body.commit
        )
    except DataOnboardingError as exc:
        _handle(exc)
    if body.commit:
        await _audit().write(
            ctx, "data_onboarding.connected", "source", session_id,
            metadata={"kind": "website"},
        )
    return result


@router.post("/sessions/{session_id}/connect/api")
async def connect_api(session_id: UUID, body: ApiConnectBody, request: Request):
    ctx = require_permission(request, "connectors:write")
    try:
        result = await _svc.connect_api(
            ctx.organization_id, session_id, body.model_dump()
        )
    except DataOnboardingError as exc:
        _handle(exc)
    await _audit().write(
        ctx, "data_onboarding.connected", "connector", session_id,
        metadata={"kind": "api"},
    )
    return result


@router.post("/sessions/{session_id}/connect/drive/start")
async def connect_drive_start(session_id: UUID, body: DriveStartBody, request: Request):
    ctx = require_permission(request, "connectors:write")
    try:
        result = await _svc.start_drive_oauth(
            ctx.organization_id, session_id, body.name
        )
    except DataOnboardingError as exc:
        _handle(exc)
    await _audit().write(
        ctx, "data_onboarding.connected", "connector", session_id,
        metadata={"kind": "drive", "oauth": "start"},
    )
    return result


@router.get("/sessions/{session_id}/connect/drive/folders")
async def connect_drive_folders(
    session_id: UUID,
    request: Request,
    parent_id: str | None = Query(default=None),
):
    require_permission(request, "connectors:read")
    try:
        return await _svc.list_drive_folders(_org(request), session_id, parent_id)
    except DataOnboardingError as exc:
        _handle(exc)


@router.post("/sessions/{session_id}/connect/drive/folder")
async def connect_drive_folder(session_id: UUID, body: DriveFolderBody, request: Request):
    ctx = require_permission(request, "sources:write")
    try:
        result = await _svc.select_drive_folder(
            ctx.organization_id, session_id, body.folder_id
        )
    except DataOnboardingError as exc:
        _handle(exc)
    await _audit().write(
        ctx, "data_onboarding.connected", "source", session_id,
        metadata={"kind": "drive", "folder_id": body.folder_id},
    )
    return result


@router.post("/sessions/{session_id}/analyze")
async def analyze(session_id: UUID, request: Request):
    ctx = _require_any(request, WRITE_PERMS)
    try:
        result = await _svc.analyze(ctx.organization_id, session_id)
    except DataOnboardingError as exc:
        _handle(exc)
    return result


@router.get("/sessions/{session_id}/progress")
async def progress(session_id: UUID, request: Request):
    _require_any(request, READ_PERMS)
    try:
        return await _svc.progress(_org(request), session_id)
    except DataOnboardingError as exc:
        _handle(exc)


@router.get("/sessions/{session_id}/understanding")
async def understanding(session_id: UUID, request: Request):
    _require_any(request, READ_PERMS)
    try:
        return await _svc.understanding(_org(request), session_id)
    except DataOnboardingError as exc:
        _handle(exc)


@router.post("/sessions/{session_id}/review/{suggestion_id}")
async def review(
    session_id: UUID,
    suggestion_id: UUID,
    body: ReviewBody,
    request: Request,
):
    ctx = require_permission(request, "catalog:write")
    try:
        result = await _svc.review(
            ctx.organization_id,
            session_id,
            suggestion_id,
            body.action,
            body.payload,
            ctx.user_id,
        )
    except DataOnboardingError as exc:
        _handle(exc)
    await _audit().write(
        ctx, "data_onboarding.reviewed", "catalog_suggestion", suggestion_id,
        metadata={"action": body.action},
    )
    return result


@router.post("/sessions/{session_id}/free-text")
async def free_text(session_id: UUID, body: FreeTextBody, request: Request):
    ctx = require_permission(request, "catalog:write")
    try:
        result = await _svc.free_text(ctx.organization_id, session_id, body.text)
    except DataOnboardingError as exc:
        _handle(exc)
    await _audit().write(
        ctx, "data_onboarding.reviewed", "catalog_suggestion", session_id,
        metadata={"kind": "free_text"},
    )
    return result


@router.get("/sessions/{session_id}/questions")
async def questions(session_id: UUID, request: Request):
    _require_any(request, READ_PERMS)
    try:
        return await _svc.questions(_org(request), session_id)
    except DataOnboardingError as exc:
        _handle(exc)


@router.post("/sessions/{session_id}/ask")
async def ask(
    session_id: UUID,
    body: AskBody,
    request: Request,
    orchestrator=Depends(get_rag_orchestrator),
):
    ctx = require_permission(request, "rag:read")
    try:
        return await _svc.ask(
            ctx.organization_id,
            session_id,
            body.question,
            ctx.user_id or UUID(int=0),
            orchestrator,
        )
    except DataOnboardingError as exc:
        _handle(exc)


@router.post("/sessions/{session_id}/answer-feedback")
async def answer_feedback(session_id: UUID, body: FeedbackBody, request: Request):
    ctx = require_permission(request, "catalog:write")
    try:
        result = await _svc.answer_feedback(
            ctx.organization_id,
            session_id,
            verdict=body.verdict,
            reason=body.reason,
            question=body.question,
        )
    except DataOnboardingError as exc:
        _handle(exc)
    await _audit().write(
        ctx, "data_onboarding.reviewed", "catalog_suggestion", session_id,
        metadata={"verdict": body.verdict, "reason": body.reason},
    )
    return result


@router.post("/sessions/{session_id}/skip/{what}")
async def skip(session_id: UUID, what: str, request: Request):
    ctx = _require_any(request, WRITE_PERMS)
    try:
        result = await _svc.skip(ctx.organization_id, session_id, what)
    except DataOnboardingError as exc:
        _handle(exc)
    await _audit().write(
        ctx, "data_onboarding.skipped", "data_onboarding_session", session_id,
        metadata={"what": what},
    )
    return result


@router.post("/sessions/{session_id}/complete")
async def complete(session_id: UUID, request: Request):
    ctx = _require_any(request, WRITE_PERMS)
    try:
        result = await _svc.complete(ctx.organization_id, session_id)
    except DataOnboardingError as exc:
        _handle(exc)
    await _audit().write(
        ctx, "data_onboarding.completed", "data_onboarding_session", session_id,
        metadata={"status": result["status"]},
    )
    return result


@router.get("/sessions/{session_id}/readiness")
async def readiness(session_id: UUID, request: Request):
    _require_any(request, READ_PERMS)
    try:
        return await _svc.readiness(_org(request), session_id)
    except DataOnboardingError as exc:
        _handle(exc)
