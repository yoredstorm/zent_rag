"""MCP Control Plane (FASE 03, S16).

Config org (tools/permissions/RPM), usage y auditoría agregada de llamadas MCP.
El servidor MCP embebido sigue siendo único; aquí se gobierna lo que ejecuta.
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import text

from src.infrastructure.postgres.session import get_async_session

router = APIRouter(prefix="/api/v1/mcp", tags=["MCP Control Plane"])

_MCP_TOOLS = [
    {"name": "search_knowledge", "permission": "rag:read", "default_rpm": 60},
    {"name": "query_database", "permission": "rag:read", "default_rpm": 20},
    {"name": "get_document", "permission": "rag:read", "default_rpm": 60},
    {"name": "execute_agent", "permission": "agents:execute", "default_rpm": 10},
    {"name": "get_usage", "permission": "usage:read", "default_rpm": 30},
]


def _default_config() -> dict:
    return {
        "enabled": True,
        "tools": {t["name"]: {"enabled": True, "min_role": "customer", "rpm": t["default_rpm"]} for t in _MCP_TOOLS},
    }


async def _org_config_value(organization_id) -> dict:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text("SELECT config_json FROM organizations WHERE id = :oid"),
                {"oid": organization_id},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        return {}
    cfg = row.config_json if isinstance(row.config_json, dict) else {}
    return cfg.get("mcp") or _default_config()


@router.get("/config", summary="Config MCP de la organización (FASE 03)")
async def get_mcp_config(request: Request):
    from src.api.security import resolve_organization
    from src.platform.rbac.policy import require_organization_admin

    require_organization_admin(request)
    organization_id = resolve_organization(request)
    return {
        "config": await _org_config_value(organization_id),
        "tools": _MCP_TOOLS,
        "endpoint": "/mcp",
    }


@router.put("/config", summary="Guardar config MCP de la organización (FASE 03)")
async def put_mcp_config(body: dict, request: Request):
    from src.api.security import resolve_organization
    from src.platform.rbac.policy import require_organization_admin

    require_organization_admin(request)
    organization_id = resolve_organization(request)

    tools = body.get("tools") or {}
    sanitized: dict = {}
    for name, tool in tools.items():
        if name not in {t["name"] for t in _MCP_TOOLS}:
            continue
        sanitized[name] = {
            "enabled": bool(tool.get("enabled", True)),
            "min_role": str(tool.get("min_role", "customer"))[:20],
            "rpm": max(0, min(int(tool.get("rpm", 60)), 1000)),
        }
    config = {"enabled": bool(body.get("enabled", True)), "tools": sanitized}

    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE organizations SET config_json = "
                "jsonb_set(COALESCE(config_json, '{}'::jsonb), '{mcp}', CAST(:cfg AS jsonb)) "
                "WHERE id = :oid"
            ),
            {"oid": organization_id, "cfg": config},
        )
        await session.commit()
    finally:
        await session.close()
    return {"config": config}


@router.get("/usage", summary="Uso MCP agregado (FASE 03)")
async def get_mcp_usage(request: Request, days: int = 30):
    from src.api.security import resolve_organization
    from src.platform.rbac.policy import require_organization_admin

    require_organization_admin(request)
    organization_id = resolve_organization(request)
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT COALESCE(cost_tags->>'tool', 'all') AS tool, "
                    "COUNT(*)::int AS calls, "
                    "COUNT(*) FILTER (WHERE status IN ('error','failed'))::int AS errors, "
                    "COALESCE(AVG(latency_ms), 0)::float AS avg_latency_ms, "
                    "COALESCE(SUM(COALESCE(actual_cost, estimated_cost)), 0)::float AS cost "
                    "FROM usage_events WHERE event_type = 'mcp_tool' "
                    "AND organization_id = :oid "
                    "AND created_at >= NOW() - (make_interval(days => :days)) "
                    "GROUP BY 1 ORDER BY calls DESC LIMIT 25"
                ),
                {"oid": organization_id, "days": days},
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "days": days,
        "tools": [
            {
                "tool": r.tool,
                "calls": int(r.calls or 0),
                "errors": int(r.errors or 0),
                "error_rate_pct": round(int(r.errors or 0) / max(int(r.calls or 1), 1) * 100, 2),
                "avg_latency_ms": round(float(r.avg_latency_ms or 0), 1),
                "cost": round(float(r.cost or 0), 4),
            }
            for r in rows
        ],
    }


@router.get("/audit", summary="Auditoría de llamadas MCP (FASE 03)")
async def get_mcp_audit(request: Request, limit: int = 50):
    from src.api.security import resolve_organization
    from src.platform.rbac.policy import require_organization_admin

    require_organization_admin(request)
    organization_id = resolve_organization(request)
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id, action, actor_user_id, ip_address, "
                    "metadata, created_at FROM audit_logs "
                    "WHERE action = 'mcp.tool_call' AND organization_id = :oid "
                    "ORDER BY created_at DESC LIMIT :limit"
                ),
                {"oid": organization_id, "limit": min(limit, 200)},
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "entries": [
            {
                "id": str(r.id),
                "action": r.action,
                "actor_user_id": str(r.actor_user_id) if r.actor_user_id else None,
                "ip_address": r.ip_address,
                "tool": (r.metadata or {}).get("tool") if isinstance(r.metadata, dict) else None,
                "status": (r.metadata or {}).get("status") if isinstance(r.metadata, dict) else None,
                "latency_ms": (r.metadata or {}).get("latency_ms") if isinstance(r.metadata, dict) else None,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
    }
