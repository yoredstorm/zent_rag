-- =============================================================================
-- RBAC Schema — Roles, Permissions, Memberships
-- =============================================================================
-- Modelo RBAC multi-tenant:
--   organizations -> memberships(organization_id, user_id, role_id) -> roles
--   roles -> role_permissions -> permissions
--
-- Regla de seguridad: los roles de sistema (organization_id IS NULL) son
-- inmutables. Las organizaciones pueden crear roles propios heredando de
-- permisos del catálogo.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Tabla: roles — Roles de sistema (organization_id NULL) y por organización
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS roles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,  -- NULL = rol de sistema
    name VARCHAR(100) NOT NULL,
    description TEXT,
    is_system BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_roles_system_name
    ON roles(name) WHERE organization_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_roles_org_name
    ON roles(organization_id, name) WHERE organization_id IS NOT NULL;

-- Roles de sistema con UUIDs estables
INSERT INTO roles (id, organization_id, name, description, is_system) VALUES
    ('50000000-0000-0000-0000-000000000001', NULL, 'owner',
     'Dueño de la organización. Control total incluyendo billing y API keys.', true),
    ('50000000-0000-0000-0000-000000000002', NULL, 'admin',
     'Administrador: gestiona recursos, usuarios y configuración.', true),
    ('50000000-0000-0000-0000-000000000003', NULL, 'member',
     'Miembro: usa RAG, crea y edita recursos de su proyecto.', true),
    ('50000000-0000-0000-0000-000000000004', NULL, 'viewer',
     'Solo lectura: consulta RAG y ve configuración.', true)
ON CONFLICT DO NOTHING;

-- -----------------------------------------------------------------------------
-- Tabla: permissions — Catálogo global de permisos
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS permissions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    code VARCHAR(100) NOT NULL UNIQUE,
    description TEXT
);

-- Catálogo de permisos con UUIDs estables
INSERT INTO permissions (id, code, description) VALUES
    ('40000000-0000-0000-0000-000000000001', 'org:read',       'Ver datos de la organización'),
    ('40000000-0000-0000-0000-000000000002', 'org:write',      'Modificar datos de la organización'),
    ('40000000-0000-0000-0000-000000000003', 'users:read',     'Listar usuarios y roles'),
    ('40000000-0000-0000-0000-000000000004', 'users:write',    'Invitar/eliminar usuarios y cambiar roles'),
    ('40000000-0000-0000-0000-000000000005', 'apikeys:read',   'Ver API keys'),
    ('40000000-0000-0000-0000-000000000006', 'apikeys:write',  'Crear/rotar/revocar API keys'),
    ('40000000-0000-0000-0000-000000000007', 'projects:read',  'Ver proyectos'),
    ('40000000-0000-0000-0000-000000000008', 'projects:write', 'Crear/editar/borrar proyectos'),
    ('40000000-0000-0000-0000-000000000009', 'kbs:read',       'Ver knowledge bases'),
    ('40000000-0000-0000-0000-000000000010', 'kbs:write',      'Crear/editar/borrar knowledge bases'),
    ('40000000-0000-0000-0000-000000000011', 'agents:read',    'Ver agentes'),
    ('40000000-0000-0000-0000-000000000012', 'agents:write',   'Crear/editar/borrar agentes'),
    ('40000000-0000-0000-0000-000000000013', 'connectors:read',  'Ver conectores'),
    ('40000000-0000-0000-0000-000000000014', 'connectors:write', 'Crear/editar/borrar conectores'),
    ('40000000-0000-0000-0000-000000000015', 'usage:read',     'Ver métricas de uso'),
    ('40000000-0000-0000-0000-000000000016', 'billing:read',   'Ver suscripción y cuota'),
    ('40000000-0000-0000-0000-000000000017', 'billing:write',  'Gestionar plan y facturación'),
    ('40000000-0000-0000-0000-000000000018', 'audit:read',     'Leer audit logs de la organización'),
    ('40000000-0000-0000-0000-000000000019', 'rag:query',      'Ejecutar consultas RAG'),
    ('40000000-0000-0000-0000-000000000020', 'rag:ingest',     'Sincronizar datos (ingestion)'),
    ('40000000-0000-0000-0000-000000000021', 'sources:read',   'Ver fuentes de datos'),
    ('40000000-0000-0000-0000-000000000022', 'sources:write',  'Crear/editar/sincronizar fuentes de datos'),
    ('40000000-0000-0000-0000-000000000023', 'rag:read',       'Leer / consultar RAG (chat)'),
    ('40000000-0000-0000-0000-000000000024', 'rag:write',      'Escribir en RAG (ingestion, fuentes, KBs)'),
    ('40000000-0000-0000-0000-000000000025', 'agents:execute', 'Ejecutar agentes'),
    ('40000000-0000-0000-0000-000000000026', 'admin:sql',      'Ejecutar SQL de solo lectura (consola admin)'),
    ('40000000-0000-0000-0000-000000000027', 'prompt:read',    'Ver system prompts de la organización'),
    ('40000000-0000-0000-0000-000000000028', 'prompt:write',   'Editar system prompts de la organización')
ON CONFLICT (code) DO NOTHING;

-- -----------------------------------------------------------------------------
-- Tabla: role_permissions — Mapeo rol -> permisos
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS role_permissions (
    role_id UUID NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    permission_id UUID NOT NULL REFERENCES permissions(id) ON DELETE CASCADE,
    PRIMARY KEY (role_id, permission_id)
);

-- Seeds de permisos por rol de sistema.
-- owner: todos. admin: todo menos billing:write (decisión de dueño).
-- member: uso + gestión de recursos. viewer: solo lectura + rag:query.
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
WHERE r.organization_id IS NULL AND r.name = 'owner'
ON CONFLICT DO NOTHING;

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
WHERE r.organization_id IS NULL AND r.name = 'admin'
  AND p.code <> 'billing:write'
ON CONFLICT DO NOTHING;

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
WHERE r.organization_id IS NULL AND r.name = 'member'
  AND p.code IN (
    'org:read', 'users:read', 'apikeys:read',
    'projects:read', 'projects:write',
    'kbs:read', 'kbs:write',
    'agents:read', 'agents:write',
    'connectors:read', 'connectors:write',
    'sources:read', 'sources:write',
    'usage:read', 'billing:read', 'audit:read', 'rag:query', 'rag:ingest',
    'rag:read', 'rag:write', 'agents:execute')
ON CONFLICT DO NOTHING;

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
WHERE r.organization_id IS NULL AND r.name = 'viewer'
  AND p.code IN (
    'org:read', 'users:read', 'apikeys:read',
    'projects:read', 'kbs:read', 'agents:read', 'connectors:read',
    'sources:read',
    'usage:read', 'billing:read', 'audit:read', 'rag:query', 'rag:read')
ON CONFLICT DO NOTHING;

-- -----------------------------------------------------------------------------
-- Tabla: memberships — Usuario pertenece a una organización con un rol
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS memberships (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id UUID NOT NULL REFERENCES roles(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (organization_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_memberships_organization ON memberships(organization_id);
CREATE INDEX IF NOT EXISTS idx_memberships_user ON memberships(user_id);

-- Backfill: usuarios seed como owner de su organización
INSERT INTO memberships (organization_id, user_id, role_id)
SELECT u.organization_id, u.id, r.id
FROM users u
JOIN roles r ON r.organization_id IS NULL AND r.name = 'owner'
WHERE u.external_id = 'default-admin'
ON CONFLICT (organization_id, user_id) DO NOTHING;

INSERT INTO memberships (organization_id, user_id, role_id)
SELECT u.organization_id, u.id,
       CASE WHEN u.role = 'admin' THEN
         (SELECT id FROM roles WHERE organization_id IS NULL AND name = 'admin')
       ELSE
         (SELECT id FROM roles WHERE organization_id IS NULL AND name = 'member')
       END
FROM users u
WHERE NOT EXISTS (
    SELECT 1 FROM memberships m WHERE m.user_id = u.id AND m.organization_id = u.organization_id
);
