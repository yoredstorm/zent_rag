"""Published workflow definition pointer.

Revision ID: 170
Revises: 169

Aditiva. Separa la fila editable (`workflows`) de la definición productiva
(`workflow_versions`). Los workflows activos anteriores a este corte conservan
su comportamiento mediante un baseline congelado, marcado `legacy_baseline` y
sin certificado; toda publicación nueva sigue el gate estándar.
"""
from __future__ import annotations

from alembic import op

revision: str = "170"
down_revision: str = "169"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Una sola versión `production` por workflow antes de crear el índice único.
    op.execute(
        """
        WITH ranked AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY workflow_id ORDER BY version_number DESC
                   ) AS rn
            FROM workflow_versions
            WHERE status = 'production'
        )
        UPDATE workflow_versions v
        SET status = 'ready'
        FROM ranked r
        WHERE v.id = r.id AND r.rn > 1
        """
    )

    op.execute(
        "ALTER TABLE workflows "
        "ADD COLUMN IF NOT EXISTS published_version_id UUID, "
        "ADD COLUMN IF NOT EXISTS published_certificate_id UUID, "
        "ADD COLUMN IF NOT EXISTS published_graph_hash VARCHAR(64), "
        "ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ, "
        "ADD COLUMN IF NOT EXISTS published_by UUID, "
        "ADD COLUMN IF NOT EXISTS deployment_generation BIGINT NOT NULL DEFAULT 0, "
        "ADD COLUMN IF NOT EXISTS draft_revision BIGINT NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE workflow_versions "
        "ADD COLUMN IF NOT EXISTS workspace_id UUID, "
        "ADD COLUMN IF NOT EXISTS graph_hash VARCHAR(64) NOT NULL DEFAULT '', "
        "ADD COLUMN IF NOT EXISTS trigger_hash VARCHAR(64) NOT NULL DEFAULT '', "
        "ADD COLUMN IF NOT EXISTS policy_version VARCHAR(40) NOT NULL DEFAULT 'v1', "
        "ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ, "
        "ADD COLUMN IF NOT EXISTS published_by UUID, "
        "ADD COLUMN IF NOT EXISTS legacy_baseline BOOLEAN NOT NULL DEFAULT false"
    )
    op.execute(
        "ALTER TABLE workflow_certificates "
        "ADD COLUMN IF NOT EXISTS binding_fingerprint VARCHAR(64) NOT NULL DEFAULT '', "
        "ADD COLUMN IF NOT EXISTS trigger_hash VARCHAR(64) NOT NULL DEFAULT ''"
    )
    op.execute(
        "ALTER TABLE workflow_instances "
        "ADD COLUMN IF NOT EXISTS published_version_id UUID, "
        "ADD COLUMN IF NOT EXISTS certificate_id UUID, "
        "ADD COLUMN IF NOT EXISTS graph_hash VARCHAR(64), "
        "ADD COLUMN IF NOT EXISTS deployment_generation BIGINT"
    )
    op.execute(
        "ALTER TABLE workflow_runs "
        "ADD COLUMN IF NOT EXISTS published_version_id UUID, "
        "ADD COLUMN IF NOT EXISTS certificate_id UUID, "
        "ADD COLUMN IF NOT EXISTS graph_hash VARCHAR(64), "
        "ADD COLUMN IF NOT EXISTS policy_version VARCHAR(40), "
        "ADD COLUMN IF NOT EXISTS deployment_generation BIGINT, "
        "ADD COLUMN IF NOT EXISTS definition_source VARCHAR(20)"
    )

    op.execute(
        """
        UPDATE workflow_versions v
        SET workspace_id = w.workspace_id
        FROM workflows w
        WHERE v.workflow_id = w.id AND v.workspace_id IS NULL
        """
    )
    # Los workflows que recibirán un baseline congelado no pueden conservar una
    # producción previa: el baseline debe reflejar exactamente la fila viva.
    op.execute(
        """
        UPDATE workflow_versions v
        SET status = 'ready'
        FROM workflows w
        WHERE v.workflow_id = w.id
          AND v.status = 'production'
          AND w.status = 'active'
          AND w.published_version_id IS NULL
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_wf_versions_production "
        "ON workflow_versions(workflow_id) WHERE status = 'production'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_wf_versions_status "
        "ON workflow_versions(workflow_id, status, version_number DESC)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_deployments (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            workspace_id UUID,
            workflow_id UUID NOT NULL,
            version_id UUID,
            certificate_id UUID,
            graph_hash VARCHAR(64) NOT NULL DEFAULT '',
            deployment_generation BIGINT NOT NULL,
            action VARCHAR(30) NOT NULL,
            actor_id UUID,
            actor_type VARCHAR(30) NOT NULL DEFAULT 'system',
            correlation_id VARCHAR(128),
            reason TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_wf_deploy_generation "
        "ON workflow_deployments(workflow_id, deployment_generation)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_wf_deployments_org "
        "ON workflow_deployments(organization_id, workflow_id, created_at DESC)"
    )

    # Baseline auditable para workflows activos sin puntero. No es un
    # certificado: conserva el grafo que ya estaba ejecutándose.
    op.execute(
        """
        INSERT INTO workflow_versions (
            organization_id, workflow_id, workspace_id, version_number, status,
            config_snapshot, notes, created_at, published_at, legacy_baseline
        )
        SELECT
            w.organization_id,
            w.id,
            w.workspace_id,
            COALESCE((
                SELECT MAX(v.version_number) FROM workflow_versions v
                WHERE v.workflow_id = w.id
            ), 0) + 1,
            'production',
            jsonb_build_object(
                'schema_version', 1,
                'name', w.name,
                'description', w.description,
                'trigger_type', w.trigger_type,
                'trigger_config', COALESCE(w.trigger_config, '{}'::jsonb) - 'hook_secret_hash',
                'steps', COALESCE(w.steps, '[]'::jsonb),
                'graph', w.graph,
                'workflow_version', w.workflow_version,
                'graph_source', w.graph_source,
                'editor_state', COALESCE(w.editor_state, '{}'::jsonb)
            ),
            'baseline P13 congelado desde fila viva; sin certificado',
            NOW(),
            NOW(),
            true
        FROM workflows w
        WHERE w.status = 'active'
          AND w.published_version_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE workflows w
        SET published_version_id = v.id,
            published_at = NOW(),
            deployment_generation = 1
        FROM workflow_versions v
        WHERE v.workflow_id = w.id
          AND v.legacy_baseline = true
          AND w.status = 'active'
          AND w.published_version_id IS NULL
        """
    )
    op.execute(
        """
        INSERT INTO workflow_deployments (
            organization_id, workspace_id, workflow_id, version_id,
            deployment_generation, action, actor_type, reason
        )
        SELECT w.organization_id, w.workspace_id, w.id, w.published_version_id,
               1, 'legacy_baseline', 'migration', 'migración 170: baseline congelado'
        FROM workflows w
        WHERE w.published_version_id IS NOT NULL
        ON CONFLICT (workflow_id, deployment_generation) DO NOTHING
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_workflows_published_version'
            ) THEN
                ALTER TABLE workflows
                ADD CONSTRAINT fk_workflows_published_version
                FOREIGN KEY (published_version_id)
                REFERENCES workflow_versions(id)
                ON DELETE SET NULL;
            END IF;
        END $$
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_wf_published_pointer "
        "ON workflows(organization_id, workspace_id, published_version_id)"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE workflow_versions SET status = 'ready' "
        "WHERE legacy_baseline = true AND status = 'production'"
    )
    op.execute("DROP INDEX IF EXISTS idx_wf_published_pointer")
    op.execute(
        "ALTER TABLE workflows DROP CONSTRAINT IF EXISTS fk_workflows_published_version"
    )
    op.execute("DROP TABLE IF EXISTS workflow_deployments")
    op.execute("DROP INDEX IF EXISTS idx_wf_versions_status")
    op.execute("DROP INDEX IF EXISTS uq_wf_versions_production")
    op.execute(
        "ALTER TABLE workflow_instances "
        "DROP COLUMN IF EXISTS deployment_generation, "
        "DROP COLUMN IF EXISTS graph_hash, "
        "DROP COLUMN IF EXISTS certificate_id, "
        "DROP COLUMN IF EXISTS published_version_id"
    )
    op.execute(
        "ALTER TABLE workflow_runs "
        "DROP COLUMN IF EXISTS definition_source, "
        "DROP COLUMN IF EXISTS deployment_generation, "
        "DROP COLUMN IF EXISTS policy_version, "
        "DROP COLUMN IF EXISTS graph_hash, "
        "DROP COLUMN IF EXISTS certificate_id, "
        "DROP COLUMN IF EXISTS published_version_id"
    )
    op.execute(
        "ALTER TABLE workflow_certificates "
        "DROP COLUMN IF EXISTS binding_fingerprint, "
        "DROP COLUMN IF EXISTS trigger_hash"
    )
    op.execute(
        "ALTER TABLE workflow_versions "
        "DROP COLUMN IF EXISTS legacy_baseline, "
        "DROP COLUMN IF EXISTS published_by, "
        "DROP COLUMN IF EXISTS published_at, "
        "DROP COLUMN IF EXISTS policy_version, "
        "DROP COLUMN IF EXISTS trigger_hash, "
        "DROP COLUMN IF EXISTS graph_hash, "
        "DROP COLUMN IF EXISTS workspace_id"
    )
    op.execute(
        "ALTER TABLE workflows "
        "DROP COLUMN IF EXISTS draft_revision, "
        "DROP COLUMN IF EXISTS deployment_generation, "
        "DROP COLUMN IF EXISTS published_by, "
        "DROP COLUMN IF EXISTS published_at, "
        "DROP COLUMN IF EXISTS published_graph_hash, "
        "DROP COLUMN IF EXISTS published_certificate_id, "
        "DROP COLUMN IF EXISTS published_version_id"
    )
