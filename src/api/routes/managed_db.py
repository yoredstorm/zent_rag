# =============================================================================
# Managed database + Database Builder API
# =============================================================================
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src.platform.managed_db import ai_designer, builder, importer
from src.platform.managed_db.service import (
    get_managed_database,
    provision_managed_database,
)
from src.platform.rbac.policy import require_permission
from src.platform.workspaces.context import resolve_workspace

router = APIRouter(prefix="/api/v1/managed-db", tags=["Managed Database"])


class ProposalRequest(BaseModel):
    prompt: str | None = None
    proposal: dict | None = None
    status: str = "DRAFT"


class ApplyRequest(BaseModel):
    proposal_id: UUID


class ImportPreviewRequest(BaseModel):
    headers: list[str]
    rows: list[list[str]] = Field(default_factory=list)
    table_name: str = "Imported"


@router.post("", status_code=201, summary="Create a database with Zent")
async def create_managed(request: Request):
    ctx = require_permission(request, "connectors:write")
    ws = await resolve_workspace(request)
    try:
        created = await provision_managed_database(ctx, ws.id)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except NotImplementedError as exc:
        raise HTTPException(501, str(exc)) from exc
    return created


@router.get("", summary="Managed database del workspace")
async def get_managed(request: Request):
    ctx = require_permission(request, "connectors:read")
    ws = await resolve_workspace(request)
    found = await get_managed_database(ctx.organization_id, ws.id)
    if found is None:
        raise HTTPException(404, "No managed database")
    return found


@router.post("/proposals", summary="Guardar / proponer schema")
async def create_proposal(body: ProposalRequest, request: Request):
    ctx = require_permission(request, "connectors:write")
    ws = await resolve_workspace(request)
    managed = await get_managed_database(ctx.organization_id, ws.id)
    if managed is None:
        raise HTTPException(404, "No managed database")
    proposal = body.proposal
    status = body.status
    if body.prompt and not proposal:
        from src.api.deps import get_llm_provider

        proposal = await ai_designer.propose_schema(body.prompt, get_llm_provider())
        status = "AI_PROPOSED"
    if not proposal:
        raise HTTPException(400, "proposal or prompt required")
    saved = await builder.save_proposal(
        ctx,
        ws.id,
        UUID(managed["id"]),
        proposal,
        status=status,
        prompt=body.prompt,
    )
    saved["relationship_labels"] = [
        builder.relationship_label(rel) for rel in (proposal.get("relationships") or [])
    ]
    return saved


@router.post("/proposals/{proposal_id}/apply", summary="Approve Schema")
async def apply_proposal(proposal_id: UUID, request: Request):
    ctx = require_permission(request, "connectors:write")
    ws = await resolve_workspace(request)
    try:
        return await builder.apply_proposal(ctx, ws.id, proposal_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/import/preview", summary="Infer types from CSV/Excel headers")
async def import_preview(body: ImportPreviewRequest, request: Request):
    require_permission(request, "sources:write")
    columns = importer.infer_columns(body.headers, body.rows)
    return {
        "columns": columns,
        "proposal": importer.create_table_proposal(body.table_name, columns),
    }


class ImportApplyRequest(BaseModel):
    headers: list[str]
    rows: list[list[str]] = Field(default_factory=list)
    table_name: str = "Imported"
    mode: str = "create"


@router.post("/import/apply", summary="INSERT CSV/Excel into managed database")
async def import_apply(body: ImportApplyRequest, request: Request):
    ctx = require_permission(request, "sources:write")
    ws = await resolve_workspace(request)
    columns = importer.infer_columns(body.headers, body.rows)
    proposal = importer.create_table_proposal(body.table_name, columns)
    if body.mode == "create":
        from src.platform.managed_db.builder import to_ddl
        from src.platform.managed_db.service import run_schema_admin_sql

        await run_schema_admin_sql(ctx.organization_id, ws.id, to_ddl(proposal))
    sql = importer.insert_sql(body.table_name, columns, body.rows)
    from src.platform.managed_db.service import run_schema_admin_sql

    await run_schema_admin_sql(ctx.organization_id, ws.id, sql)
    return {"status": "imported", "columns": columns, "rows": len(body.rows)}
