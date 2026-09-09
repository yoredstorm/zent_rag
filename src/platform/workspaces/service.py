# =============================================================================
# Workspaces — Tenant → Workspace → {Agents, KBs, Connectors}
# =============================================================================
from __future__ import annotations

import re
from uuid import UUID

from src.core.domain.entities import Workspace, WorkspaceKind
from src.core.ports import WorkspaceRepository

_SLUG_RE = re.compile(r"[^a-z0-9-]+")
_DEFAULT_NAME = "Default Workspace"
_DEFAULT_SLUG = "default"
_DEMO_NAME = "Demo Workspace"
_DEMO_SLUG = "demo"


def workspace_slugify(name: str) -> str:
    slug = _SLUG_RE.sub("-", (name or "").lower()).strip("-")
    return slug[:64] or "workspace"


async def ensure_default_workspace(
    repo: WorkspaceRepository,
    organization_id: UUID,
    *,
    kind: str = "business",
) -> Workspace:
    """Crea el workspace por defecto si no existe (idempotente)."""
    from src.platform.workspaces.context import ensure_workspace_schema

    await ensure_workspace_schema()
    existing = await repo.get_workspace_by_slug(organization_id, _DEFAULT_SLUG)
    if existing is not None:
        return existing
    return await repo.create_workspace(
        organization_id, _DEFAULT_NAME, _DEFAULT_SLUG, kind=kind
    )


async def ensure_demo_workspace(
    repo: WorkspaceRepository,
    organization_id: UUID,
    created_by: UUID | None = None,
) -> Workspace:
    """Workspace demo del trial. Idempotente."""
    from src.platform.workspaces.context import ensure_workspace_schema

    await ensure_workspace_schema()
    demo = await repo.get_workspace_by_slug(organization_id, _DEMO_SLUG)
    if demo is not None:
        return demo
    default = await repo.get_workspace_by_slug(organization_id, _DEFAULT_SLUG)
    if default is None:
        return await repo.create_workspace(
            organization_id,
            _DEMO_NAME,
            _DEFAULT_SLUG,
            kind="demo",
            created_by=created_by,
        )
    if default.kind == WorkspaceKind.DEMO:
        return default
    return await repo.create_workspace(
        organization_id,
        _DEMO_NAME,
        _DEMO_SLUG,
        kind="demo",
        created_by=created_by,
    )


async def choose_trial_start_mode(
    repo: WorkspaceRepository,
    organization_id: UUID,
    user_id: UUID,
    mode: str,
) -> tuple[Workspace, bool]:
    """Crea el primer workspace del trial. Idempotente si ya existe alguno.

    Returns (workspace, created). created=False si la org ya tenía workspace.
    """
    if mode not in ("demo", "blank"):
        raise ValueError("mode must be demo or blank")
    from src.platform.workspaces.context import (
        ensure_workspace_schema,
        get_active_workspace_id,
        set_active_workspace,
    )

    await ensure_workspace_schema()
    existing = await repo.list_workspaces(organization_id)
    if existing:
        active_id = await get_active_workspace_id(organization_id, user_id)
        if active_id is not None:
            for ws in existing:
                if ws.id == active_id:
                    return ws, False
        return existing[0], False

    if mode == "demo":
        ws = await ensure_demo_workspace(
            repo, organization_id, created_by=user_id
        )
    else:
        ws = await ensure_default_workspace(
            repo, organization_id, kind="business"
        )
    await set_active_workspace(organization_id, user_id, ws.id)
    return ws, True


async def require_own_workspace(
    repo: WorkspaceRepository,
    organization_id: UUID,
    workspace_id: UUID | None,
) -> Workspace | None:
    """Valida pertenencia: None si el workspace no existe o es de otra org."""
    if workspace_id is None:
        return None
    workspace = await repo.get_workspace(organization_id, workspace_id)
    if workspace is None:
        raise ValueError(f"Workspace {workspace_id} not found in this organization")
    return workspace
