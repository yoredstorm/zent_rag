# =============================================================================
# Workspaces — Tenant → Workspace → {Agents, KBs, Connectors}
# =============================================================================
from __future__ import annotations

import re
from uuid import UUID

from src.core.domain.entities import Workspace
from src.core.ports import WorkspaceRepository

_SLUG_RE = re.compile(r"[^a-z0-9-]+")
_DEFAULT_NAME = "Default Workspace"
_DEFAULT_SLUG = "default"


def workspace_slugify(name: str) -> str:
    slug = _SLUG_RE.sub("-", (name or "").lower()).strip("-")
    return slug[:64] or "workspace"


async def ensure_default_workspace(
    repo: WorkspaceRepository, organization_id: UUID
) -> Workspace:
    """Crea el workspace por defecto si no existe (idempotente)."""
    existing = await repo.get_workspace_by_slug(organization_id, _DEFAULT_SLUG)
    if existing is not None:
        return existing
    return await repo.create_workspace(
        organization_id, _DEFAULT_NAME, _DEFAULT_SLUG
    )


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
