# =============================================================================
# Demo → business transition
# =============================================================================
from __future__ import annotations

from uuid import UUID

from src.core.domain.entities import TenantContext, Workspace
from src.core.ports import WorkspaceRepository
from src.infrastructure.postgres.relational_db import PostgresAuditLogRepository
from src.platform.audit.service import AuditLogService
from src.platform.demo_purge.service import DemoPurgeService
from src.platform.workspaces.context import set_active_workspace
from src.platform.workspaces.service import workspace_slugify


class DemoTransitionService:
    def __init__(self, workspace_repo: WorkspaceRepository) -> None:
        self._workspaces = workspace_repo
        self._purge = DemoPurgeService(AuditLogService(PostgresAuditLogRepository()))

    async def start_business_workspace(
        self, ctx: TenantContext, *, name: str = "My Business"
    ) -> Workspace:
        slug = workspace_slugify(name)
        existing = await self._workspaces.get_workspace_by_slug(
            ctx.organization_id, slug
        )
        if existing is not None:
            ws = existing
        else:
            ws = await self._workspaces.create_workspace(
                ctx.organization_id,
                name,
                slug,
                kind="business",
                created_by=ctx.user_id,
            )
        if ctx.user_id is not None:
            await set_active_workspace(ctx.organization_id, ctx.user_id, ws.id)
        return ws

    async def replace_demo(
        self, ctx: TenantContext, workspace_id: UUID, confirmation: str
    ) -> dict:
        if confirmation.strip().upper() != "DELETE DEMO":
            raise ValueError("confirmation must be DELETE DEMO")
        ws = await self._workspaces.get_workspace(ctx.organization_id, workspace_id)
        if ws is None:
            raise ValueError("Workspace not found")
        result = await self._purge.purge(ctx, workspace_id)
        updated = await self._workspaces.update_workspace(
            ctx.organization_id, workspace_id, kind="business"
        )
        result["business_workspace_id"] = str(workspace_id)
        if updated is not None:
            result["workspace"] = {
                "id": str(updated.id),
                "name": updated.name,
                "kind": updated.kind.value,
            }
        return result
