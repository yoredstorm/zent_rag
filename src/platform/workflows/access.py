# =============================================================================
# Workflow resource access — autorización por recurso, no solo por tenant.
#
# Un UUID no concede acceso. Toda ruta que recibe run_id/instance_id/approval_id
# resuelve el recurso hasta su workflow y workspace antes de devolver datos.
# Reglas:
#   * recurso con workspace NULL = global de la organización (legacy documentado);
#   * recurso con workspace = request sin workspace activo -> 400;
#   * workspace distinto -> 404 (no revela existencia);
#   * el RBAC de acción lo exige la ruta antes de llegar aquí.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.postgres.session import get_async_session


class WorkflowAccessDenied(Exception):
    """Recurso inexistente para este tenant/workspace."""

    def __init__(self, code: str, message: str, *, status_code: int = 404):
        self.code = code
        self.status_code = status_code
        super().__init__(message)


@dataclass(frozen=True)
class ResourceScope:
    resource_id: str
    organization_id: str
    workspace_id: str | None
    workflow_id: str
    parent_id: str | None = None
    org_global: bool = False


def _check_scope(scope: ResourceScope, request_workspace_id: UUID | None) -> None:
    if scope.org_global or scope.workspace_id is None:
        return
    if request_workspace_id is None:
        raise WorkflowAccessDenied(
            "workspace_required",
            "X-Workspace-Id requerido para este recurso.",
            status_code=400,
        )
    if str(scope.workspace_id) != str(request_workspace_id):
        raise WorkflowAccessDenied("not_found", "Recurso no encontrado.")


async def workflow_scope(
    organization_id: UUID, workflow_id: UUID
) -> ResourceScope | None:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT id, organization_id, workspace_id FROM workflows "
                    "WHERE id = :wid AND organization_id = :oid"
                ),
                {"wid": str(workflow_id), "oid": str(organization_id)},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        return None
    return ResourceScope(
        resource_id=str(row.id),
        organization_id=str(row.organization_id),
        workspace_id=str(row.workspace_id) if row.workspace_id else None,
        workflow_id=str(row.id),
        org_global=row.workspace_id is None,
    )


async def run_scope(organization_id: UUID, run_id: UUID) -> ResourceScope | None:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT r.id, r.organization_id, r.workspace_id, r.workflow_id, "
                    "       w.workspace_id AS workflow_workspace_id, w.organization_id AS wf_org "
                    "FROM workflow_runs r JOIN workflows w ON w.id = r.workflow_id "
                    "WHERE r.id = :rid"
                ),
                {"rid": str(run_id)},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None or str(row.organization_id) != str(organization_id):
        return None
    if str(row.wf_org) != str(organization_id):
        return None
    ws = row.workspace_id or row.workflow_workspace_id
    return ResourceScope(
        resource_id=str(row.id),
        organization_id=str(row.organization_id),
        workspace_id=str(ws) if ws else None,
        workflow_id=str(row.workflow_id),
        org_global=ws is None,
    )


async def approval_scope(
    organization_id: UUID, approval_id: UUID
) -> ResourceScope | None:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT a.id, a.organization_id, a.workspace_id, a.workflow_id, "
                    "       a.run_id FROM workflow_approvals a "
                    "WHERE a.id = :aid AND a.organization_id = :oid"
                ),
                {"aid": str(approval_id), "oid": str(organization_id)},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        return None
    run = await run_scope(organization_id, UUID(str(row.run_id)))
    if run is None:
        return None
    ws = row.workspace_id or run.workspace_id
    return ResourceScope(
        resource_id=str(row.id),
        organization_id=str(row.organization_id),
        workspace_id=str(ws) if ws else None,
        workflow_id=str(row.workflow_id),
        parent_id=str(row.run_id),
        org_global=ws is None,
    )


async def assert_workflow_access(
    organization_id: UUID, workflow_id: UUID, request_workspace_id: UUID | None
) -> ResourceScope:
    scope = await workflow_scope(organization_id, workflow_id)
    if scope is None:
        raise WorkflowAccessDenied("not_found", "Workflow no encontrado.")
    _check_scope(scope, request_workspace_id)
    return scope


async def assert_run_access(
    organization_id: UUID, run_id: UUID, request_workspace_id: UUID | None
) -> ResourceScope:
    scope = await run_scope(organization_id, run_id)
    if scope is None:
        raise WorkflowAccessDenied("not_found", "Run no encontrado.")
    _check_scope(scope, request_workspace_id)
    return scope


async def assert_approval_access(
    organization_id: UUID, approval_id: UUID, request_workspace_id: UUID | None
) -> ResourceScope:
    scope = await approval_scope(organization_id, approval_id)
    if scope is None:
        raise WorkflowAccessDenied("not_found", "Aprobación no encontrada.")
    _check_scope(scope, request_workspace_id)
    return scope


__all__ = [
    "ResourceScope",
    "WorkflowAccessDenied",
    "approval_scope",
    "assert_approval_access",
    "assert_run_access",
    "assert_workflow_access",
    "run_scope",
    "workflow_scope",
]
