"""Human-in-the-loop (FASE 03, S14) + workspace collaboration (S15).

Gate de aprobación en el runtime del agente: tools flaggeadas por política de
org pausan el run en 'awaiting_approval' hasta decisión humana.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import text

from src.infrastructure.postgres.session import get_async_session

APPROVAL_WINDOW_MINUTES = 10


def approval_required_tools(org_config: dict) -> list[str]:
    """Tools que exigen aprobación humana (config_json['approval_required'])."""
    raw = (org_config or {}).get("approval_required") or []
    return [str(t) for t in raw if isinstance(t, str)]


async def has_recent_approval(
    organization_id: UUID, agent_id: UUID, tool: str
) -> bool:
    """¿Hay una aprobación reciente (sin usar) para (agente, tool)?"""
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT id FROM approval_requests "
                    "WHERE organization_id = :oid AND agent_id = :aid AND tool = :tool "
                    "AND status = 'approved' AND decided_at >= NOW() - (make_interval(mins => :win)) "
                    "ORDER BY decided_at DESC LIMIT 1"
                ),
                {"oid": organization_id, "aid": agent_id, "tool": tool[:60], "win": APPROVAL_WINDOW_MINUTES},
            )
        ).fetchone()
        if row is not None:
            await session.execute(
                text(
                    "UPDATE approval_requests SET status = 'used' WHERE id = :rid"
                ),
                {"rid": row.id},
            )
            await session.commit()
            return True
        return False
    finally:
        await session.close()


async def request_approval(
    organization_id: UUID,
    agent_id: UUID | None,
    run_id: UUID,
    tool: str,
    summary: str,
) -> None:
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO approval_requests "
                "(id, organization_id, agent_id, run_id, tool, summary) "
                "VALUES (gen_random_uuid(), :oid, :aid, :rid, :tool, :summary)"
            ),
            {
                "oid": organization_id,
                "aid": agent_id,
                "rid": run_id,
                "tool": tool[:60],
                "summary": summary[:500],
            },
        )
        await session.commit()
    finally:
        await session.close()


async def list_approvals(organization_id: UUID, status: str | None = None) -> list[dict]:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id, agent_id, run_id, tool, summary, status, "
                    "decided_by, decided_at, created_at FROM approval_requests "
                    "WHERE organization_id = :oid AND "
                    "(CAST(:status AS varchar) IS NULL OR status = CAST(:status AS varchar)) "
                    "ORDER BY created_at DESC LIMIT 100"
                ),
                {"oid": organization_id, "status": status},
            )
        ).fetchall()
    finally:
        await session.close()
    return [
        {
            "id": str(r.id),
            "agent_id": str(r.agent_id) if r.agent_id else None,
            "run_id": str(r.run_id) if r.run_id else None,
            "tool": r.tool,
            "summary": r.summary,
            "status": r.status,
            "decided_by": str(r.decided_by) if r.decided_by else None,
            "decided_at": r.decided_at.isoformat() if r.decided_at else None,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


async def decide_approval(
    organization_id: UUID, approval_id: UUID, approved: bool, decided_by: UUID | None
) -> bool:
    session = await get_async_session()
    try:
        result = await session.execute(
            text(
                "UPDATE approval_requests SET status = :status, decided_by = :by, "
                "decided_at = NOW() "
                "WHERE id = :rid AND organization_id = :oid AND status = 'pending'"
            ),
            {
                "status": "approved" if approved else "rejected",
                "by": decided_by,
                "rid": approval_id,
                "oid": organization_id,
            },
        )
        await session.commit()
        return result.rowcount > 0
    finally:
        await session.close()


# ---------------------------------------------------------------------------
# Workspace collaboration (S15): tasks + activity (foundation)
# ---------------------------------------------------------------------------
async def create_task(
    organization_id: UUID,
    workspace_id: UUID,
    title: str,
    created_by: UUID | None,
    agent_id: UUID | None = None,
) -> dict:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO workspace_tasks "
                    "(id, workspace_id, title, created_by, agent_id) "
                    "VALUES (gen_random_uuid(), :wid, :title, :by, :aid) "
                    "RETURNING id, workspace_id, title, status, created_at"
                ),
                {"wid": workspace_id, "title": title[:300], "by": created_by, "aid": agent_id},
            )
        ).fetchone()
        await session.execute(
            text(
                "INSERT INTO workspace_activity (workspace_id, event_type, detail, actor_user_id) "
                "VALUES (:wid, 'task.created', :detail, :by)"
            ),
            {"wid": workspace_id, "detail": f"Tarea creada: {title[:200]}", "by": created_by},
        )
        await session.commit()
    finally:
        await session.close()
    return {"id": str(row.id), "title": row.title, "status": row.status}


async def update_task_status(
    organization_id: UUID, task_id: UUID, status: str, actor: UUID | None
) -> bool:
    session = await get_async_session()
    try:
        result = await session.execute(
            text(
                "UPDATE workspace_tasks t SET status = :status, completed_at = "
                "CASE WHEN :status = 'done' THEN NOW() ELSE NULL END "
                "FROM workspaces w WHERE t.id = :tid AND w.id = t.workspace_id "
                "AND w.organization_id = :oid AND t.status <> :status"
            ),
            {"status": status, "tid": task_id, "oid": organization_id},
        )
        await session.commit()
        return result.rowcount > 0
    finally:
        await session.close()


async def list_tasks(workspace_id: UUID) -> list[dict]:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id, workspace_id, title, status, assignee_user_id, "
                    "agent_id, created_by, created_at, completed_at "
                    "FROM workspace_tasks WHERE workspace_id = :wid ORDER BY created_at DESC"
                ),
                {"wid": workspace_id},
            )
        ).fetchall()
    finally:
        await session.close()
    return [
        {
            "id": str(r.id),
            "workspace_id": str(r.workspace_id),
            "title": r.title,
            "status": r.status,
            "assignee_user_id": str(r.assignee_user_id) if r.assignee_user_id else None,
            "agent_id": str(r.agent_id) if r.agent_id else None,
            "created_by": str(r.created_by) if r.created_by else None,
            "created_at": r.created_at.isoformat(),
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        }
        for r in rows
    ]


async def workspace_activity(workspace_id: UUID, limit: int = 50) -> list[dict]:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id, event_type, detail, actor_user_id, agent_id, created_at "
                    "FROM workspace_activity WHERE workspace_id = :wid "
                    "ORDER BY created_at DESC LIMIT :limit"
                ),
                {"wid": workspace_id, "limit": min(limit, 200)},
            )
        ).fetchall()
    finally:
        await session.close()
    return [
        {
            "id": str(r.id),
            "event_type": r.event_type,
            "detail": r.detail,
            "actor_user_id": str(r.actor_user_id) if r.actor_user_id else None,
            "agent_id": str(r.agent_id) if r.agent_id else None,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]
