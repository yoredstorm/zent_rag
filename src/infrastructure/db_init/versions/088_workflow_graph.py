"""Phase 32A — Workflow Graph IR, workspace isolation, RBAC, event triggers, approvals.

Revision ID: 088
Revises: 087
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision: str = "088"
down_revision: str = "087"
branch_labels = None
depends_on = None

# IDs de permisos nuevos (rango 40000000-…-60..72 libre tras workspaces 46/47
# y catalog 51/52).
_WORKFLOW_PERMISSIONS = [
    ("40000000-0000-0000-0000-000000000060", "workflows:read", "Ver workflows de la organización"),
    ("40000000-0000-0000-0000-000000000061", "workflows:create", "Crear workflows"),
    ("40000000-0000-0000-0000-000000000062", "workflows:update", "Editar workflows"),
    ("40000000-0000-0000-0000-000000000063", "workflows:delete", "Eliminar workflows"),
    ("40000000-0000-0000-0000-000000000064", "workflows:run", "Ejecutar workflows"),
    ("40000000-0000-0000-0000-000000000065", "workflows:activate", "Activar/pausar workflows"),
    ("40000000-0000-0000-0000-000000000066", "workflow_runs:read", "Ver runs y pasos de workflows"),
    ("40000000-0000-0000-0000-000000000067", "integrations:read", "Ver integraciones disponibles"),
    ("40000000-0000-0000-0000-000000000068", "integrations:use", "Usar integraciones en workflows"),
    ("40000000-0000-0000-0000-000000000069", "external_actions:execute", "Ejecutar acciones externas (API/connectors)"),
    ("40000000-0000-0000-0000-000000000070", "workflow_secrets:manage", "Gestionar secretos de workflows"),
    ("40000000-0000-0000-0000-000000000071", "workflow_approvals:approve", "Aprobar/rechazar aprobaciones de workflows"),
    ("40000000-0000-0000-0000-000000000072", "workflow_events:subscribe", "Registrar triggers de eventos"),
]

# Roles que pueden ver/leer (incluye miembros técnicos y analistas).
_READER_ROLES = ("owner", "admin", "member", "viewer", "ai_engineer", "data_engineer", "developer", "analyst")
# Roles con capacidades de escritura/ejecución.
_MANAGER_ROLES = ("owner", "admin", "member")
# Lecturas de integraciones: técnicos también.
_INTEGRATION_READER_ROLES = ("owner", "admin", "member", "ai_engineer", "data_engineer", "developer", "analyst", "viewer")


def upgrade() -> None:
    # --- Workspace isolation en workflows/runs/run_steps -------------------
    op.execute(
        "ALTER TABLE workflows ADD COLUMN IF NOT EXISTS workspace_id UUID "
        "REFERENCES workspaces(id) ON DELETE SET NULL"
    )
    op.execute(
        "ALTER TABLE workflows ADD COLUMN IF NOT EXISTS graph JSONB, "
        "ADD COLUMN IF NOT EXISTS workflow_version INT NOT NULL DEFAULT 1, "
        "ADD COLUMN IF NOT EXISTS graph_source VARCHAR(16) NOT NULL DEFAULT 'legacy'"
    )
    op.execute(
        "ALTER TABLE workflow_runs ADD COLUMN IF NOT EXISTS workspace_id UUID "
        "REFERENCES workspaces(id) ON DELETE SET NULL"
    )
    op.execute(
        "ALTER TABLE workflow_runs ADD COLUMN IF NOT EXISTS correlation_id VARCHAR(128), "
        "ADD COLUMN IF NOT EXISTS actor_type VARCHAR(20) NOT NULL DEFAULT 'system', "
        "ADD COLUMN IF NOT EXISTS actor_id UUID, "
        "ADD COLUMN IF NOT EXISTS simulate BOOLEAN NOT NULL DEFAULT false"
    )
    op.execute(
        "ALTER TABLE workflow_run_steps ADD COLUMN IF NOT EXISTS node_id VARCHAR(80), "
        "ADD COLUMN IF NOT EXISTS node_type VARCHAR(40), "
        "ADD COLUMN IF NOT EXISTS attempt INT NOT NULL DEFAULT 0, "
        "ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(160)"
    )
    # Backfill: workflows huérfanos de workspace → workspace default del org.
    op.execute(
        "UPDATE workflows SET workspace_id = ws.id FROM workspaces ws "
        "WHERE workflows.workspace_id IS NULL "
        "AND ws.organization_id = workflows.organization_id AND ws.slug = 'default'"
    )
    op.execute(
        "UPDATE workflow_runs SET workspace_id = w.workspace_id "
        "FROM workflows w WHERE workflow_runs.workflow_id = w.id "
        "AND workflow_runs.workspace_id IS NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_workflows_org_ws "
        "ON workflows(organization_id, workspace_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_workflow_runs_org_ws "
        "ON workflow_runs(organization_id, workspace_id, started_at DESC)"
    )

    # --- Event triggers (event bus → workflows) ----------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_event_triggers (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            workspace_id UUID REFERENCES workspaces(id) ON DELETE SET NULL,
            workflow_id UUID NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
            event_type VARCHAR(120) NOT NULL,
            filters JSONB NOT NULL DEFAULT '{}',
            status VARCHAR(20) NOT NULL DEFAULT 'active',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (workflow_id, event_type)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_workflow_event_triggers_match "
        "ON workflow_event_triggers(event_type, status)"
    )

    # --- Approbaciones humanas ---------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_approvals (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            run_id UUID NOT NULL REFERENCES workflow_runs(id) ON DELETE CASCADE,
            workflow_id UUID NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
            organization_id UUID NOT NULL,
            workspace_id UUID,
            node_id VARCHAR(80) NOT NULL,
            action VARCHAR(120) NOT NULL,
            summary TEXT,
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            requested_by UUID,
            decided_by UUID,
            decision_comment TEXT,
            requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            decided_at TIMESTAMPTZ,
            expires_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_workflow_approvals_org_status "
        "ON workflow_approvals(organization_id, status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_workflow_approvals_run "
        "ON workflow_approvals(run_id)"
    )

    # --- RBAC: permisos nuevos + asignación a roles sistema ----------------
    bind = op.get_bind()
    for pid, code, desc in _WORKFLOW_PERMISSIONS:
        bind.execute(
            text(
                "INSERT INTO permissions (id, code, description) VALUES (:pid, :code, :desc) "
                "ON CONFLICT (code) DO NOTHING"
            ),
            {"pid": pid, "code": code, "desc": desc},
        )

    def _grant(permission: str, roles: tuple[str, ...]) -> None:
        # Literales inline (constantes del modelo); evita bind expanding en text().
        role_list = ", ".join(f"'{r}'" for r in roles)
        bind.execute(
            text(
                "INSERT INTO role_permissions (role_id, permission_id) "
                "SELECT r.id, p.id FROM roles r CROSS JOIN permissions p "
                f"WHERE r.organization_id IS NULL AND r.name IN ({role_list}) "
                "AND p.code = :perm ON CONFLICT DO NOTHING"
            ),
            {"perm": permission},
        )

    _grant("workflows:read", _READER_ROLES)
    _grant("workflow_runs:read", _READER_ROLES)
    _grant("workflows:create", _MANAGER_ROLES)
    _grant("workflows:update", _MANAGER_ROLES)
    _grant("workflows:delete", _MANAGER_ROLES)
    _grant("workflows:run", _MANAGER_ROLES)
    _grant("workflows:activate", _MANAGER_ROLES)
    _grant("workflow_events:subscribe", _MANAGER_ROLES)
    _grant("integrations:read", _INTEGRATION_READER_ROLES)
    _grant("integrations:use", _MANAGER_ROLES)
    _grant("external_actions:execute", _MANAGER_ROLES)
    _grant("workflow_secrets:manage", _MANAGER_ROLES)
    _grant("workflow_approvals:approve", ("owner", "admin"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS workflow_approvals")
    op.execute("DROP TABLE IF EXISTS workflow_event_triggers")
    op.execute("DROP INDEX IF EXISTS idx_workflows_org_ws")
    op.execute("DROP INDEX IF EXISTS idx_workflow_runs_org_ws")
    op.execute("ALTER TABLE workflows DROP COLUMN IF EXISTS workspace_id")
    op.execute("ALTER TABLE workflows DROP COLUMN IF EXISTS graph")
    op.execute("ALTER TABLE workflows DROP COLUMN IF EXISTS workflow_version")
    op.execute("ALTER TABLE workflows DROP COLUMN IF EXISTS graph_source")
    op.execute("ALTER TABLE workflow_runs DROP COLUMN IF EXISTS workspace_id")
    op.execute("ALTER TABLE workflow_runs DROP COLUMN IF EXISTS correlation_id")
    op.execute("ALTER TABLE workflow_runs DROP COLUMN IF EXISTS actor_type")
    op.execute("ALTER TABLE workflow_runs DROP COLUMN IF EXISTS actor_id")
    op.execute("ALTER TABLE workflow_runs DROP COLUMN IF EXISTS simulate")
    op.execute("ALTER TABLE workflow_run_steps DROP COLUMN IF EXISTS node_id")
    op.execute("ALTER TABLE workflow_run_steps DROP COLUMN IF EXISTS node_type")
    op.execute("ALTER TABLE workflow_run_steps DROP COLUMN IF EXISTS attempt")
    op.execute("ALTER TABLE workflow_run_steps DROP COLUMN IF EXISTS idempotency_key")
    for pid, _code, _desc in _WORKFLOW_PERMISSIONS:
        op.execute(text("DELETE FROM permissions WHERE id = :pid"), {"pid": pid})

