-- =============================================================================
-- Deployments Go Live — deployment_events + permisos granulares de deploy
-- Espejo SQL de la migración alembic 027_deployment_events (bases nuevas).
-- =============================================================================

CREATE TABLE IF NOT EXISTS deployment_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    deployment_id UUID NOT NULL REFERENCES deployments(id) ON DELETE CASCADE,
    event VARCHAR(30) NOT NULL,
    actor_user_id UUID,
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_deployment_events_deployment
    ON deployment_events(deployment_id, created_at ASC);
CREATE INDEX IF NOT EXISTS idx_deployment_events_org
    ON deployment_events(organization_id, created_at DESC);

INSERT INTO permissions (id, code, description) VALUES
    ('40000000-0000-0000-0000-000000000048', 'deployments:deploy',
     'Crear deployments (desplegar versiones en entornos)'),
    ('40000000-0000-0000-0000-000000000049', 'deployments:rollback',
     'Ejecutar rollback de deployments'),
    ('40000000-0000-0000-0000-000000000050', 'deployments:promote',
     'Promover versiones a production')
ON CONFLICT (code) DO NOTHING;

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
WHERE r.organization_id IS NULL AND r.name IN ('owner', 'admin')
ON CONFLICT DO NOTHING;