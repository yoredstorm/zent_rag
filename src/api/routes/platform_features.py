"""FASE 03 — Feature flags, business outcomes, telemetry, residency."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import text

from src.infrastructure.postgres.session import get_async_session

router = APIRouter(prefix="/api/v1", tags=["Platform features"])


@router.get("/platform/flags", summary="Feature flags (FASE 03, S23)")
async def list_flags(request: Request):
    from src.platform.features.service import list_flags as _list
    from src.platform.rbac.policy import require_platform_permission

    require_platform_permission(request, "platform.settings.manage")
    return {"flags": await _list()}


@router.put("/platform/flags", summary="Set feature flag (FASE 03, S23)")
async def set_flag(body: dict, request: Request):
    from src.platform.features.service import set_flag as _set
    from src.platform.rbac.policy import require_platform_permission

    ctx = require_platform_permission(request, "platform.settings.manage")
    key = str(body.get("key") or "").strip()
    scope = str(body.get("scope") or "platform")
    if not key or scope not in ("platform", "plan", "organization", "workspace"):
        raise HTTPException(400, "key y scope inválidos")
    await _set(
        key,
        scope,
        bool(body.get("enabled", True)),
        plan_name=body.get("plan_name"),
        organization_id=UUID(body["organization_id"]) if body.get("organization_id") else None,
        workspace_id=UUID(body["workspace_id"]) if body.get("workspace_id") else None,
        created_by=ctx.user_id,
    )
    return {"status": "saved", "key": key, "scope": scope}


@router.get("/organizations/flags", summary="Flags activos del tenant (FASE 03, S23)")
async def tenant_flags(request: Request):
    from src.api.security import resolve_organization
    from src.platform.features.service import list_flags
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:read")
    organization_id = resolve_organization(request)

    plan_name = None
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT p.name FROM subscriptions s "
                    "JOIN plans p ON p.id = s.plan_id "
                    "WHERE s.organization_id = :oid AND s.status IN ('active', 'trialing') "
                    "ORDER BY s.created_at DESC LIMIT 1"
                ),
                {"oid": organization_id},
            )
        ).fetchone()
        if row:
            plan_name = row.name
    finally:
        await session.close()

    flags = await list_flags()
    applicable = [
        f
        for f in flags
        if f["scope"] == "platform"
        or (f["scope"] == "plan" and f["plan_name"] == plan_name)
        or (f["scope"] == "organization" and f["organization_id"] == str(organization_id))
    ]
    return {"flags": applicable}


@router.post("/organizations/outcomes", summary="Registrar métrica de negocio (FASE 03, S13)")
async def record_outcome(body: dict, request: Request):
    from src.api.security import resolve_organization
    from src.platform.features.service import record_business_metric
    from src.platform.rbac.policy import require_organization_admin

    require_organization_admin(request)
    organization_id = resolve_organization(request)
    metric_key = str(body.get("metric_key") or "").strip()
    if not metric_key:
        raise HTTPException(400, "metric_key requerido")
    value = body.get("value")
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise HTTPException(400, "value debe ser numérico") from None
    agent_id = body.get("agent_id")
    await record_business_metric(
        organization_id,
        metric_key,
        value,
        agent_id=UUID(agent_id) if agent_id else None,
        period_start=body.get("period_start"),
        period_end=body.get("period_end"),
        source=body.get("source"),
    )
    return {"status": "recorded"}


@router.get("/organizations/outcomes", summary="Métricas de negocio (FASE 03, S13)")
async def get_outcomes(request: Request, agent_id: str | None = None, days: int = 90):
    from src.api.security import resolve_organization
    from src.platform.features.service import business_metrics
    from src.platform.rbac.policy import require_organization_admin

    require_organization_admin(request)
    organization_id = resolve_organization(request)
    return {
        "metrics": await business_metrics(
            organization_id,
            agent_id=UUID(agent_id) if agent_id else None,
            days=days,
        )
    }


@router.get("/platform/telemetry/adoption", summary="Adopción agregada (FASE 03, S24)")
async def adoption(request: Request):
    from src.platform.features.service import adoption_metrics
    from src.platform.rbac.policy import require_platform_permission

    require_platform_permission(request, "analytics.read")
    return await adoption_metrics()


@router.get("/organizations/residency", summary="Data residency del tenant (FASE 03, S19)")
async def tenant_residency(request: Request):
    from src.api.security import resolve_organization
    from src.platform.edge.multiregion import list_regions, resolve_region
    from src.platform.rbac.policy import require_organization_admin

    require_organization_admin(request)
    organization_id = resolve_organization(request)

    primary = None
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text("SELECT primary_region_id FROM organizations WHERE id = :oid"),
                {"oid": organization_id},
            )
        ).fetchone()
    finally:
        await session.close()
    if row and row.primary_region_id:
        primary = str(row.primary_region_id)

    region = "unknown"
    try:
        region = (await resolve_region(organization_id))["region"]
    except Exception:  # noqa: BLE001
        pass

    regions = await list_regions()
    region_list = regions if isinstance(regions, list) else (regions.get("regions") or [])
    return {
        "organization_id": str(organization_id),
        "primary_region": primary,
        "resolved_region": region,
        "regions": [
            {"code": r.get("code"), "name": r.get("name"), "status": r.get("status")}
            for r in region_list
        ],
        "note": "La infraestructura resuelve la región primaria con failover; "
            "no se promete aislamiento regional adicional.",
    }
