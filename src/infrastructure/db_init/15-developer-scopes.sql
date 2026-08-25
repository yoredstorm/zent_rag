-- =============================================================================
-- Developer platform scopes — rag:read / rag:write / agents:execute
-- =============================================================================
-- Idempotente: seguro en bases ya inicializadas (CI, docker volumes viejos).
-- No elimina rag:query / rag:ingest (aliases de compatibilidad).
-- =============================================================================

INSERT INTO permissions (id, code, description) VALUES
    ('40000000-0000-0000-0000-000000000023', 'rag:read',       'Leer / consultar RAG (chat)'),
    ('40000000-0000-0000-0000-000000000024', 'rag:write',      'Escribir en RAG (ingestion, fuentes, KBs)'),
    ('40000000-0000-0000-0000-000000000025', 'agents:execute', 'Ejecutar agentes'),
    ('40000000-0000-0000-0000-000000000026', 'admin:sql',      'Ejecutar SQL de solo lectura (consola admin)'),
    ('40000000-0000-0000-0000-000000000027', 'prompt:read',    'Ver system prompts de la organización'),
    ('40000000-0000-0000-0000-000000000028', 'prompt:write',   'Editar system prompts de la organización')
ON CONFLICT (code) DO NOTHING;

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
  AND p.code IN ('rag:read', 'rag:write', 'agents:execute')
ON CONFLICT DO NOTHING;

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
WHERE r.organization_id IS NULL AND r.name = 'viewer'
  AND p.code IN ('rag:read')
ON CONFLICT DO NOTHING;
