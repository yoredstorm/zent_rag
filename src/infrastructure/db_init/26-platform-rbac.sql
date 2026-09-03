-- =============================================================================
-- Platform RBAC — roles de plataforma granulares + roles de tenant nuevos
-- Espejo SQL de la migración alembic 023_platform_rbac (bases nuevas).
-- =============================================================================

CREATE TABLE IF NOT EXISTS platform_roles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    is_system BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS platform_role_permissions (
    role_id UUID NOT NULL REFERENCES platform_roles(id) ON DELETE CASCADE,
    permission_id UUID NOT NULL REFERENCES permissions(id) ON DELETE CASCADE,
    PRIMARY KEY (role_id, permission_id)
);

CREATE TABLE IF NOT EXISTS user_platform_roles (
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id UUID NOT NULL REFERENCES platform_roles(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, role_id)
);

CREATE INDEX IF NOT EXISTS idx_user_platform_roles_user ON user_platform_roles(user_id);

INSERT INTO permissions (id, code, description) VALUES
    ('40000000-0000-0000-0000-000000000032', 'tenant.read',
     'Ver tenants (listado y ficha 360)'),
    ('40000000-0000-0000-0000-000000000033', 'tenant.write',
     'Modificar datos de tenants'),
    ('40000000-0000-0000-0000-000000000034', 'tenant.suspend',
     'Pausar/suspender/cancelar tenants'),
    ('40000000-0000-0000-0000-000000000035', 'billing.read',
     'Ver billing global de la plataforma'),
    ('40000000-0000-0000-0000-000000000036', 'billing.manage',
     'Gestionar planes, precios y suscripciones'),
    ('40000000-0000-0000-0000-000000000037', 'models.read',
     'Ver modelos y providers'),
    ('40000000-0000-0000-0000-000000000038', 'models.manage',
     'Gestionar modelos y providers'),
    ('40000000-0000-0000-0000-000000000039', 'operations.read',
     'Ver operaciones (jobs, workers, errores)'),
    ('40000000-0000-0000-0000-000000000040', 'operations.write',
     'Ejecutar operaciones de plataforma'),
    ('40000000-0000-0000-0000-000000000041', 'support.impersonate',
     'Iniciar sesiones de soporte (impersonación)'),
    ('40000000-0000-0000-0000-000000000042', 'audit.read',
     'Ver audit logs globales'),
    ('40000000-0000-0000-0000-000000000043', 'platform.settings.manage',
     'Gestionar configuración de plataforma'),
    ('40000000-0000-0000-0000-000000000044', 'platform.users.manage',
     'Gestionar usuarios y roles de plataforma'),
    ('40000000-0000-0000-0000-000000000045', 'analytics.read',
     'Ver métricas y analítica de plataforma')
ON CONFLICT (code) DO NOTHING;

INSERT INTO platform_roles (id, name, description, is_system) VALUES
    ('60000000-0000-0000-0000-000000000001', 'super_admin',
     'Control total de la plataforma', true),
    ('60000000-0000-0000-0000-000000000002', 'platform_admin',
     'Administra la plataforma salvo settings globales', true),
    ('60000000-0000-0000-0000-000000000003', 'operations',
     'Operaciones: tenants, jobs y monitoreo', true),
    ('60000000-0000-0000-0000-000000000004', 'support',
     'Soporte: lectura de tenants e impersonación', true),
    ('60000000-0000-0000-0000-000000000005', 'finance',
     'Finanzas: billing y analítica económica', true),
    ('60000000-0000-0000-0000-000000000006', 'security_auditor',
     'Auditoría: lectura de tenants y audit logs', true),
    ('60000000-0000-0000-0000-000000000007', 'read_only',
     'Solo lectura operativa de la plataforma', true)
ON CONFLICT (name) DO NOTHING;

INSERT INTO platform_role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM platform_roles r CROSS JOIN permissions p
WHERE r.name = 'super_admin'
ON CONFLICT DO NOTHING;

INSERT INTO platform_role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM platform_roles r CROSS JOIN permissions p
WHERE r.name = 'platform_admin' AND p.code <> 'platform.settings.manage'
ON CONFLICT DO NOTHING;

INSERT INTO platform_role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM platform_roles r JOIN permissions p
ON p.code IN ('tenant.read', 'operations.read', 'operations.write', 'analytics.read')
WHERE r.name = 'operations'
ON CONFLICT DO NOTHING;

INSERT INTO platform_role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM platform_roles r JOIN permissions p
ON p.code IN ('tenant.read', 'support.impersonate', 'analytics.read')
WHERE r.name = 'support'
ON CONFLICT DO NOTHING;

INSERT INTO platform_role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM platform_roles r JOIN permissions p
ON p.code IN ('tenant.read', 'billing.read', 'billing.manage', 'analytics.read')
WHERE r.name = 'finance'
ON CONFLICT DO NOTHING;

INSERT INTO platform_role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM platform_roles r JOIN permissions p
ON p.code IN ('tenant.read', 'audit.read')
WHERE r.name = 'security_auditor'
ON CONFLICT DO NOTHING;

INSERT INTO platform_role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM platform_roles r JOIN permissions p
ON p.code IN ('tenant.read', 'analytics.read')
WHERE r.name = 'read_only'
ON CONFLICT DO NOTHING;

INSERT INTO user_platform_roles (user_id, role_id)
SELECT u.id, r.id FROM users u CROSS JOIN platform_roles r
WHERE u.is_platform_admin AND r.name = 'super_admin'
ON CONFLICT DO NOTHING;

INSERT INTO roles (id, organization_id, name, description, is_system) VALUES
    ('50000000-0000-0000-0000-000000000005', NULL, 'ai_engineer',
     'Diseña agentes: prompts, knowledge, evaluación y deployments', true),
    ('50000000-0000-0000-0000-000000000006', NULL, 'data_engineer',
     'Conecta y sincroniza fuentes de datos', true),
    ('50000000-0000-0000-0000-000000000007', NULL, 'developer',
     'Desarrolla integraciones, API keys y agentes', true),
    ('50000000-0000-0000-0000-000000000008', NULL, 'analyst',
     'Consulta datos y analítica en modo lectura', true),
    ('50000000-0000-0000-0000-000000000009', NULL, 'billing',
     'Gestiona suscripción, facturación y uso', true)
ON CONFLICT DO NOTHING;

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r JOIN permissions p
ON p.code IN (
    'agents:read', 'agents:write', 'agents:version', 'agents:execute',
    'kbs:read', 'kbs:write', 'sources:read', 'sources:write',
    'rag:read', 'rag:write', 'prompt:read', 'prompt:write',
    'usage:read', 'deployments:read', 'deployments:write'
)
WHERE r.organization_id IS NULL AND r.name = 'ai_engineer'
ON CONFLICT DO NOTHING;

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r JOIN permissions p
ON p.code IN (
    'sources:read', 'sources:write', 'connectors:read', 'connectors:write',
    'kbs:read', 'kbs:write', 'rag:write', 'rag:ingest', 'usage:read'
)
WHERE r.organization_id IS NULL AND r.name = 'data_engineer'
ON CONFLICT DO NOTHING;

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r JOIN permissions p
ON p.code IN (
    'agents:read', 'agents:write', 'agents:version', 'agents:execute',
    'projects:read', 'projects:write', 'apikeys:read', 'apikeys:write',
    'rag:read', 'prompt:read', 'prompt:write',
    'deployments:read', 'deployments:write'
)
WHERE r.organization_id IS NULL AND r.name = 'developer'
ON CONFLICT DO NOTHING;

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r JOIN permissions p
ON p.code IN (
    'agents:read', 'kbs:read', 'sources:read', 'connectors:read',
    'rag:read', 'usage:read', 'deployments:read', 'audit:read'
)
WHERE r.organization_id IS NULL AND r.name = 'analyst'
ON CONFLICT DO NOTHING;

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r JOIN permissions p
ON p.code IN ('billing:read', 'billing:write', 'usage:read')
WHERE r.organization_id IS NULL AND r.name = 'billing'
ON CONFLICT DO NOTHING;

ALTER TABLE organization_invites DROP CONSTRAINT IF EXISTS organization_invites_role_check;