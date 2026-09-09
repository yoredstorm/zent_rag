-- =============================================================================
-- Workflow studio — scheduler, editor_state, plantilla low-stock (espejo 087)
-- =============================================================================

ALTER TABLE workflows ADD COLUMN IF NOT EXISTS last_run_at TIMESTAMPTZ;
ALTER TABLE workflows ADD COLUMN IF NOT EXISTS editor_state JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE workflow_templates ADD COLUMN IF NOT EXISTS trigger_config
    JSONB NOT NULL DEFAULT '{}'::jsonb;

INSERT INTO workflow_templates (slug, name, description, category, trigger_type, trigger_config, steps)
VALUES (
    'low-stock-alert',
    'Alerta de stock bajo',
    'Consulta stock cada 5 minutos, cruza con la KB y avisa por email y webhook.',
    'operations',
    'schedule',
    '{"every_minutes": 5}'::jsonb,
    '[{"type":"api_call","config":{"url":"https://stock.example.com/qty","method":"GET","json_path":"quantity"}},{"type":"kb_query","config":{"query":"politica de reposicion","limit":5}},{"type":"condition","config":{"field":"steps.0.output.extracted","operator":"<","value":"10"},"then":[{"type":"notify","config":{"channel":"email","title":"Stock bajo","message":"bajo"}}],"else":[{"type":"notify","config":{"channel":"in_app","title":"Stock OK","message":"ok"}}]}]'::jsonb
)
ON CONFLICT (slug) DO NOTHING;
