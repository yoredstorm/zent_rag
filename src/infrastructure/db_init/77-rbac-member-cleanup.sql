-- =============================================================================
-- RBAC — Restringe role_permissions del rol global 'member' a su lista canónica
-- Espejo SQL de la migración alembic 071 (bases nuevas).
-- Idempotente: en una base sin el bug no borra nada.
-- =============================================================================

DELETE FROM role_permissions
WHERE role_id = (
        SELECT id FROM roles
        WHERE organization_id IS NULL AND name = 'member'
    )
  AND permission_id IN (
        SELECT id FROM permissions WHERE code NOT IN (
            'org:read', 'users:read', 'apikeys:read',
            'projects:read', 'projects:write',
            'kbs:read', 'kbs:write',
            'agents:read', 'agents:write', 'agents:version', 'agents:execute',
            'connectors:read', 'connectors:write',
            'sources:read', 'sources:write',
            'usage:read', 'billing:read', 'audit:read',
            'rag:query', 'rag:ingest', 'rag:read', 'rag:write',
            'deployments:read',
            'workspaces:read', 'workspaces:write'
        )
    );