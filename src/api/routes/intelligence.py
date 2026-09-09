# =============================================================================
# Phase 32C — Intelligence API
# BusinessResults (inbox), workflow copilot (NL→draft), assist options y
# stats de automatización.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/intelligence", tags=["Intelligence"])


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
@router.get("/results", summary="Inbox de resultados de inteligencia")
async def intelligence_results(
    request: Request,
    section: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    limit: int = 50,
    since_minutes: int | None = None,
):
    ctx = _require(request, "intelligence:read")
    from src.platform.intelligence.results import list_results

    return await list_results(
        ctx.organization_id,
        workspace_id=await _workspace_id(request),
        section=section,
        entity_type=entity_type,
        entity_id=entity_id,
        limit=limit,
        since_minutes=since_minutes,
    )


@router.get("/results/{result_id}", summary="Detalle de resultado")
async def intelligence_result_detail(result_id: str, request: Request):
    ctx = _require(request, "intelligence:read")
    from src.platform.intelligence.results import get_result

    result = await get_result(ctx.organization_id, UUID(result_id))
    if result is None:
        raise HTTPException(404, "Resultado no encontrado")
    return result


# ---------------------------------------------------------------------------
# Workflow Copilot — describe → draft
# ---------------------------------------------------------------------------
@router.post("/workflow/draft", summary="Copiloto: lenguaje natural → draft de workflow")
async def intelligence_workflow_draft(body: DraftIn, request: Request):
    ctx = _require(request, "workflows:create")
    from src.platform.workflows.copilot import build_draft

    prompt = (body.prompt or "").strip()
    if len(prompt) < 8:
        raise HTTPException(400, "describe qué quieres automatizar")
    plan = build_draft(prompt)
    return {
        "name": plan.name,
        "trigger_type": plan.trigger_type,
        "trigger_config": plan.trigger_config,
        "steps": plan.steps,
        "questions": plan.questions,
        "source_hint": plan.source_hint,
        "integration_hint": plan.integration_hint,
        "draft": True,
        "must_review": True,
    }


# ---------------------------------------------------------------------------
# Asistente de opciones (smart pickers): fuentes, integraciones, agentes
# ---------------------------------------------------------------------------
@router.get("/assist/options", summary="Opciones para los pickers del editor")
async def intelligence_assist_options(request: Request):
    ctx = _require(request, "intelligence:read")
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session
    from src.platform.marketplace.runtime import list_installs

    session = await get_async_session()
    try:
        kbs = (
            await session.execute(
                text(
                    "SELECT id, name FROM knowledge_bases "
                    "WHERE organization_id = :oid ORDER BY name"
                ),
                {"oid": ctx.organization_id},
            )
        ).fetchall()
        agents = (
            await session.execute(
                text(
                    "SELECT id, name FROM agents WHERE organization_id = :oid "
                    "AND status IN ('configured','ready','deployed') ORDER BY name"
                ),
                {"oid": ctx.organization_id},
            )
        ).fetchall()
        try:
            sources = (
                await session.execute(
                    text(
                        "SELECT id, name, source_type FROM catalog_sources "
                        "WHERE organization_id = :oid ORDER BY name LIMIT 100"
                    ),
                    {"oid": ctx.organization_id},
                )
            ).fetchall()
        except Exception:  # noqa: BLE001 — tabla opcional en some envs
            sources = []
    finally:
        await session.close()

    installs = await list_installs(ctx.organization_id, await _workspace_id(request))
    return {
        "knowledge_bases": [{"id": str(k.id), "name": k.name} for k in kbs],
        "agents": [{"id": str(a.id), "name": a.name} for a in agents],
        "data_sources": [
            {"id": str(s.id), "name": s.name, "type": s.source_type} for s in sources
        ],
        "integrations": [
            {
                "install_id": i["id"],
                "slug": i["integration"]["slug"],
                "name": i["integration"]["name"],
                "status": i["status"],
            }
            for i in installs["installs"]
        ],
    }


# ---------------------------------------------------------------------------
# Stats de automatizaciones (Automations Home)
# ---------------------------------------------------------------------------
@router.get("/automations/stats", summary="Stats para Automations Home")
async def intelligence_automations_stats(request: Request):
    ctx = _require(request, "intelligence:read")
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT "
                    "(SELECT COUNT(*) FROM workflows WHERE organization_id = :oid AND status = 'active') AS active, "
                    "(SELECT COUNT(*) FROM workflow_runs WHERE organization_id = :oid "
                    "AND status = 'failed' AND started_at > NOW() - interval '24 hours') AS failed_24h, "
                    "(SELECT COUNT(*) FROM workflow_runs WHERE organization_id = :oid "
                    "AND started_at > NOW() - interval '24 hours') AS runs_24h, "
                    "(SELECT COUNT(*) FROM workflow_runs r JOIN workflows w ON w.id = r.workflow_id "
                    "WHERE w.organization_id = :oid AND r.status = 'succeeded' "
                    "AND r.started_at > NOW() - interval '30 days') AS runs_30d, "
                    "(SELECT AVG(duration_ms) FROM workflow_runs WHERE organization_id = :oid "
                    "AND started_at > NOW() - interval '7 days') AS avg_ms"
                ),
                {"oid": ctx.organization_id},
            )
        ).fetchone()
        spend = (
            await session.execute(
                text(
                    "SELECT COALESCE(SUM(customer_cost), 0) AS spend FROM integration_usage_ledger "
                    "WHERE organization_id = :oid AND created_at > NOW() - interval '24 hours'"
                ),
                {"oid": ctx.organization_id},
            )
        ).scalar()
        ext_calls_24h = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM integration_usage_ledger WHERE organization_id = :oid "
                    "AND created_at > NOW() - interval '24 hours'"
                ),
                {"oid": ctx.organization_id},
            )
        ).scalar()
    finally:
        await session.close()
    total = int(row.runs_24h or 0)
    ok_24h = max(0, total - int(row.failed_24h or 0))
    return {
        "active_automations": int(row.active or 0),
        "needs_attention": int(row.failed_24h or 0),
        "runs_today": total,
        "success_rate_24h": round(ok_24h / total * 100, 1) if total else 0.0,
        "success_rate_30d": 0.0,
        "external_calls_24h": int(ext_calls_24h or 0),
        "marketplace_spend_24h": float(spend or 0),
        "avg_runtime_ms": int(row.avg_ms or 0),
        "runs_30d": int(row.runs_30d or 0),
    }


class DraftIn(BaseModel):
    prompt: str = Field(min_length=8, max_length=2000)
