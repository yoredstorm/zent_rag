# =============================================================================
# Memory Inspector — lectura y acciones administrativas tenant-scoped.
# Activar memoria no cambia prompts, thresholds, modelos ni configuración.
# =============================================================================
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Body, HTTPException, Query, Request
from pydantic import BaseModel, Field

from src.core.domain.memory import MemoryType, ValidationPath
from src.memory.content import MemoryContentError
from src.memory.policy import MemoryPolicyError
from src.memory.replay import ReplayBlocked, ReplayBook
from src.memory.service import MemoryNotFound, empty_query_impact
from src.platform.rbac.policy import require_organization_admin, require_permission

router = APIRouter(prefix="/api/v1/memory", tags=["Memory"])

_TYPES = {item.value for item in MemoryType}
_STATUSES = {
    "observed",
    "reinforced",
    "pattern",
    "validated",
    "active",
    "contradicted",
    "stale",
    "rejected",
    "expired",
    "superseded",
}


class AdminReason(BaseModel):
    model_config = {"extra": "forbid"}

    reason: str = Field(default="", max_length=500)


class ValidateIn(BaseModel):
    model_config = {"extra": "forbid"}

    via: ValidationPath
    reason: str = Field(default="", max_length=500)


def _service():
    from src.memory.wiring import memory_foundation_service

    return memory_foundation_service()


def _audit():
    from src.infrastructure.postgres.relational_db import PostgresAuditLogRepository
    from src.platform.audit.service import AuditLogService

    return AuditLogService(PostgresAuditLogRepository())


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "invalid_date", "message": "Invalid datetime filter"},
        ) from exc


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, MemoryNotFound):
        return HTTPException(
            status_code=404,
            detail={"error_code": "memory_not_found", "message": "Memory not found"},
        )
    if isinstance(exc, (MemoryPolicyError, MemoryContentError)):
        return HTTPException(
            status_code=400,
            detail={"error_code": "memory_policy", "message": str(exc)[:240]},
        )
    raise exc


@router.get("", summary="Listar memorias del tenant")
async def list_memories(
    request: Request,
    memory_type: str | None = None,
    status: str | None = None,
    agent_id: UUID | None = None,
    source: str | None = Query(default=None, max_length=80),
    pattern: str | None = Query(default=None, max_length=80),
    confidence_min: float | None = Query(default=None, ge=0, le=1),
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    ctx = require_permission(request, "knowledge:read")
    if memory_type and memory_type not in _TYPES:
        raise HTTPException(status_code=400, detail={"error_code": "invalid_type", "message": "Invalid memory type"})
    if status and status not in _STATUSES:
        raise HTTPException(status_code=400, detail={"error_code": "invalid_status", "message": "Invalid status"})
    rows = await _service().list_memories(
        ctx.organization_id,
        memory_type=memory_type,
        status=status,
        agent_id=agent_id,
        source_component=source,
        pattern=pattern,
        confidence_min=confidence_min,
        updated_from=_parse_dt(date_from),
        updated_to=_parse_dt(date_to),
        limit=limit,
        offset=offset,
    )
    return {"items": [row.to_public_dict() for row in rows], "limit": limit, "offset": offset}


@router.get("/runs/{run_id}/impact", summary="Memoria usada, creada, reforzada o contradicha en un run")
async def run_impact(run_id: UUID, request: Request):
    ctx = require_permission(request, "knowledge:read")
    return await _service().run_impact(ctx.organization_id, run_id=run_id)


@router.get(
    "/conversations/{conversation_id}/impact",
    summary="Impacto de memoria de una conversación",
)
async def conversation_impact(conversation_id: UUID, request: Request):
    ctx = require_permission(request, "knowledge:read")
    return await _service().run_impact(ctx.organization_id, conversation_id=conversation_id)


@router.get(
    "/queries/{query_id}/impact",
    summary="Impacto de memoria de una respuesta",
)
async def query_memory_impact(query_id: str, request: Request):
    ctx = require_permission(request, "knowledge:read")
    try:
        parsed = UUID(query_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "invalid_query_id",
                "message": "query_id must be a valid UUID",
            },
        ) from exc
    from src.rag.flow_store import request_id_for_query

    request_id = await request_id_for_query(ctx.organization_id, parsed)
    if request_id is None:
        return empty_query_impact(parsed)
    return await _service().query_impact(
        ctx.organization_id, query_id=parsed, request_id=request_id
    )


class ReplayToolIn(BaseModel):
    model_config = {"extra": "forbid"}

    name: str = Field(max_length=80)
    execution: str = Field(default="live", max_length=20)
    side_effect: bool = False


class ReplayIn(BaseModel):
    model_config = {"extra": "forbid"}

    question: str = Field(default="", max_length=4000)
    tools: list[ReplayToolIn] = Field(default_factory=list, max_length=20)


async def _replay_patterns(organization_id: UUID, question: str) -> list[dict]:
    if not question.strip():
        return []
    try:
        from src.core.domain.memory import MemoryType
        from src.memory.recall import RecallQuery
        from src.memory.signature import infer_pattern_features
        from src.memory.wiring import memory_recall_service

        records = await memory_recall_service().recall(
            RecallQuery(
                organization_id=organization_id,
                features=infer_pattern_features(question, sql_enabled=False),
                memory_types=(MemoryType.OPERATIONAL, MemoryType.LEARNING),
                limit=5,
            )
        )
    except Exception:  # noqa: BLE001 — el replay no inventa memorias si el recall falla
        return []
    return [
        {
            "memory_id": str(record.id),
            "display_id": str(record.id).replace("-", "")[:8],
            "title": record.title,
            "retrieval_modality": record.retrieval_modality,
        }
        for record in records
    ]


@router.post(
    "/queries/{query_id}/replay",
    summary="Reejecutar una respuesta con la memoria actual",
)
async def replay_query(query_id: str, body: ReplayIn, request: Request):
    ctx = require_permission(request, "knowledge:read")
    try:
        parsed = UUID(query_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "invalid_query_id",
                "message": "query_id must be a valid UUID",
            },
        ) from exc
    from src.rag.flow_store import get_flow, request_id_for_query

    flow = await get_flow(ctx.organization_id, parsed)
    if flow is None:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "flow_not_found", "message": "Flow not found"},
        )
    flow = {**flow, "query_id": str(parsed)}
    tools = [tool.model_dump() for tool in body.tools]
    try:
        patterns = await _replay_patterns(ctx.organization_id, body.question)
        original_memories: list[dict] = []
        request_id = await request_id_for_query(ctx.organization_id, parsed)
        if request_id is not None:
            impact = await _service().query_impact(
                ctx.organization_id, query_id=parsed, request_id=request_id
            )
            original_memories = list(impact.get("used") or [])
        book = ReplayBook()
        book.remember(ctx.organization_id, flow)
        result = book.start(
            ctx.organization_id,
            parsed,
            tools=tools,
            patterns=patterns,
            original_memories=original_memories,
        )
    except ReplayBlocked as exc:
        raise HTTPException(
            status_code=409,
            detail={"error_code": "replay_blocked", "message": str(exc), "tool": exc.tool},
        ) from exc
    result.pop("organization_id", None)
    from src.memory.replay_store import persist_replay

    await persist_replay(ctx.organization_id, result)
    return result


@router.get("/{memory_id}", summary="Ver una memoria")
async def get_memory(memory_id: UUID, request: Request):
    ctx = require_permission(request, "knowledge:read")
    try:
        record = await _service().get(ctx.organization_id, memory_id)
    except MemoryNotFound as exc:
        raise _http(exc) from exc
    return record.to_public_dict()


@router.get("/{memory_id}/timeline", summary="Timeline append-only")
async def memory_timeline(
    memory_id: UUID,
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    ctx = require_permission(request, "knowledge:read")
    try:
        events = await _service().timeline(ctx.organization_id, memory_id, limit=limit, offset=offset)
    except Exception as exc:
        raise _http(exc) from exc
    return {"items": [event.to_public_dict() for event in events], "limit": limit, "offset": offset}


@router.get("/{memory_id}/evidence", summary="Evidencia que sostiene la memoria")
async def memory_evidence(
    memory_id: UUID,
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    ctx = require_permission(request, "knowledge:read")
    try:
        links = await _service().evidence(ctx.organization_id, memory_id, limit=limit, offset=offset)
    except Exception as exc:
        raise _http(exc) from exc
    return {"items": [link.to_public_dict() for link in links], "limit": limit, "offset": offset}


@router.get("/{memory_id}/conversations", summary="Conversaciones relacionadas")
async def memory_conversations(
    memory_id: UUID,
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    ctx = require_permission(request, "knowledge:read")
    try:
        items = await _service().conversations(
            ctx.organization_id, memory_id, limit=limit, offset=offset
        )
    except Exception as exc:
        raise _http(exc) from exc
    return {"items": items, "limit": limit, "offset": offset}


@router.get("/{memory_id}/metrics", summary="Métricas de la memoria")
async def memory_metrics(memory_id: UUID, request: Request):
    ctx = require_permission(request, "knowledge:read")
    try:
        return await _service().metrics(ctx.organization_id, memory_id)
    except Exception as exc:
        raise _http(exc) from exc


async def _admin(request: Request, memory_id: UUID, action: str, runner):
    ctx = require_organization_admin(request)
    require_permission(request, "knowledge:write")
    try:
        record = await runner(ctx.organization_id, ctx.user_id)
    except Exception as exc:
        raise _http(exc) from exc
    await _audit().write(
        ctx,
        action=action,
        resource_type="memory",
        resource_id=memory_id,
        metadata={"status": record.status.value},
    )
    return record.to_public_dict()


@router.post("/{memory_id}/validate", summary="Validar por experimento, golden set, estadística o admin")
async def validate_memory(memory_id: UUID, body: ValidateIn, request: Request):
    async def runner(organization_id, actor_id):
        return await _service().validate(organization_id, memory_id, via=body.via, actor_id=actor_id)

    return await _admin(request, memory_id, "memory.validate", runner)


@router.post("/{memory_id}/activate", summary="Autorizar recall. No muta producción.")
async def activate_memory(
    memory_id: UUID, request: Request, body: AdminReason | None = Body(default=None)
):
    del body

    async def runner(organization_id, actor_id):
        return await _service().activate(organization_id, memory_id, actor_id=actor_id)

    return await _admin(request, memory_id, "memory.activate", runner)


@router.post("/{memory_id}/deactivate")
async def deactivate_memory(
    memory_id: UUID, request: Request, body: AdminReason | None = Body(default=None)
):
    del body

    async def runner(organization_id, actor_id):
        return await _service().deactivate(organization_id, memory_id, actor_id=actor_id)

    return await _admin(request, memory_id, "memory.deactivate", runner)


@router.post("/{memory_id}/reject")
async def reject_memory(
    memory_id: UUID, request: Request, body: AdminReason | None = Body(default=None)
):
    del body

    async def runner(organization_id, actor_id):
        return await _service().reject(organization_id, memory_id, actor_id=actor_id)

    return await _admin(request, memory_id, "memory.reject", runner)


@router.post("/{memory_id}/expire")
async def expire_memory(
    memory_id: UUID, request: Request, body: AdminReason | None = Body(default=None)
):
    del body

    async def runner(organization_id, actor_id):
        return await _service().expire(organization_id, memory_id, actor_id=actor_id)

    return await _admin(request, memory_id, "memory.expire", runner)


@router.post("/{memory_id}/restore")
async def restore_memory(
    memory_id: UUID, request: Request, body: AdminReason | None = Body(default=None)
):
    del body

    async def runner(organization_id, actor_id):
        return await _service().restore(organization_id, memory_id, actor_id=actor_id)

    return await _admin(request, memory_id, "memory.restore", runner)
