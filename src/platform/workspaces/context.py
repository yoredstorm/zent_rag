# =============================================================================
# Workspace request context — resolve X-Workspace-Id / membership active
# =============================================================================
from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy import text

from src.core.domain.entities import Workspace
from src.infrastructure.postgres.relational_db import PostgresWorkspaceRepository
from src.infrastructure.postgres.session import get_async_session
from src.platform.workspaces.service import ensure_default_workspace

_SCHEMA_SQL = (
    "ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS kind VARCHAR(20) "
    "NOT NULL DEFAULT 'business'",
    "ALTER TABLE memberships ADD COLUMN IF NOT EXISTS active_workspace_id UUID "
    "REFERENCES workspaces(id) ON DELETE SET NULL",
    "ALTER TABLE kb_sources ADD COLUMN IF NOT EXISTS workspace_id UUID "
    "REFERENCES workspaces(id) ON DELETE SET NULL",
    "ALTER TABLE catalog_sources ADD COLUMN IF NOT EXISTS workspace_id UUID",
    "CREATE INDEX IF NOT EXISTS idx_kb_sources_workspace "
    "ON kb_sources(organization_id, workspace_id)",
    "CREATE INDEX IF NOT EXISTS idx_catalog_sources_workspace "
    "ON catalog_sources(organization_id, workspace_id)",
    "CREATE INDEX IF NOT EXISTS idx_memberships_active_workspace "
    "ON memberships(active_workspace_id)",
)

_schema_ready = False


async def ensure_workspace_schema() -> None:
    global _schema_ready
    if _schema_ready:
        return
    session = await get_async_session()
    try:
        for stmt in _SCHEMA_SQL:
            try:
                await session.execute(text(stmt))
                await session.commit()
            except Exception:  # noqa: BLE001
                await session.rollback()
        try:
            await session.execute(
                text(
                    "ALTER TABLE workspaces DROP CONSTRAINT IF EXISTS workspaces_kind_check"
                )
            )
            await session.execute(
                text(
                    "ALTER TABLE workspaces ADD CONSTRAINT workspaces_kind_check "
                    "CHECK (kind IN ('demo', 'business'))"
                )
            )
            await session.commit()
        except Exception:  # noqa: BLE001
            await session.rollback()
        _schema_ready = True
    finally:
        await session.close()


async def get_active_workspace_id(
    organization_id: UUID, user_id: UUID | None
) -> UUID | None:
    await ensure_workspace_schema()
    if user_id is None:
        return None
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT active_workspace_id FROM memberships "
                    "WHERE organization_id = :oid AND user_id = :uid"
                ),
                {"oid": organization_id, "uid": user_id},
            )
        ).fetchone()
        return row.active_workspace_id if row else None
    finally:
        await session.close()


async def set_active_workspace(
    organization_id: UUID, user_id: UUID, workspace_id: UUID
) -> None:
    await ensure_workspace_schema()
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE memberships SET active_workspace_id = :wid "
                "WHERE organization_id = :oid AND user_id = :uid"
            ),
            {"oid": organization_id, "uid": user_id, "wid": workspace_id},
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def resolve_workspace(request: Request) -> Workspace:
    """Header X-Workspace-Id > membership.active > default workspace.

    Invalid header UUID → 400. Header for another org → 404 (no leak).
    """
    ctx = getattr(request.state, "tenant_context", None)
    if ctx is None or ctx.tenant_id is None:
        raise HTTPException(401, "Tenant context required")
    await ensure_workspace_schema()
    repo = PostgresWorkspaceRepository()
    header = request.headers.get("X-Workspace-Id") or request.headers.get(
        "x-workspace-id"
    )
    if header:
        try:
            wid = UUID(header)
        except ValueError as exc:
            raise HTTPException(400, "X-Workspace-Id must be a valid UUID") from exc
        ws = await repo.get_workspace(ctx.organization_id, wid)
        if ws is None:
            raise HTTPException(404, "Workspace not found")
        request.state.workspace = ws
        return ws

    active_id = await get_active_workspace_id(ctx.organization_id, ctx.user_id)
    if active_id is not None:
        ws = await repo.get_workspace(ctx.organization_id, active_id)
        if ws is not None:
            request.state.workspace = ws
            return ws

    ws = await ensure_default_workspace(repo, ctx.organization_id)
    request.state.workspace = ws
    return ws


def workspace_header_or_none(request: Request) -> UUID | None:
    raw = request.headers.get("X-Workspace-Id") or request.headers.get("x-workspace-id")
    if not raw:
        return None
    return UUID(raw)
