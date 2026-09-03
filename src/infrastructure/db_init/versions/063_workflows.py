"""AI Workflow Automation Studio v2 — workflows, runs y pasos trazables.

Revision ID: 063
Revises: 062
Create Date: 2026-09-02
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "063"
down_revision: Union[str, None] = "062"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workflows (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            name VARCHAR(150) NOT NULL,
            description TEXT,
            trigger_type VARCHAR(20) NOT NULL DEFAULT 'webhook',
            trigger_config JSONB NOT NULL DEFAULT '{}',
            steps JSONB NOT NULL DEFAULT '[]',
            status VARCHAR(20) NOT NULL DEFAULT 'draft',
            created_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_workflows_org "
        "ON workflows(organization_id, created_at DESC)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_runs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workflow_id UUID NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'running',
            started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            completed_at TIMESTAMPTZ,
            duration_ms INT,
            error TEXT,
            trigger_payload JSONB NOT NULL DEFAULT '{}'
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_workflow_runs_wf "
        "ON workflow_runs(workflow_id, started_at DESC)"
    )
    # workflow_runs pre-existió en la fase v1 — ampliar esquema v2.
    op.execute(
        "ALTER TABLE workflow_runs "
        "ADD COLUMN IF NOT EXISTS trigger_payload JSONB NOT NULL DEFAULT '{}', "
        "ADD COLUMN IF NOT EXISTS duration_ms INT"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_run_steps (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            run_id UUID NOT NULL,
            step_index INT NOT NULL,
            step_type VARCHAR(20) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            input JSONB NOT NULL DEFAULT '{}',
            output JSONB NOT NULL DEFAULT '{}',
            error TEXT,
            retries INT NOT NULL DEFAULT 0,
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            duration_ms INT
        )
        """
    )
    # workflow_run_steps v1 usaba otra forma (columnas name/order/result).
    op.execute(
        "ALTER TABLE workflow_run_steps "
        "ADD COLUMN IF NOT EXISTS step_index INT, "
        "ADD COLUMN IF NOT EXISTS step_type VARCHAR(20) NOT NULL DEFAULT 'llm', "
        "ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'pending', "
        "ADD COLUMN IF NOT EXISTS input JSONB NOT NULL DEFAULT '{}', "
        "ADD COLUMN IF NOT EXISTS output JSONB NOT NULL DEFAULT '{}', "
        "ADD COLUMN IF NOT EXISTS error TEXT, "
        "ADD COLUMN IF NOT EXISTS retries INT NOT NULL DEFAULT 0, "
        "ADD COLUMN IF NOT EXISTS duration_ms INT"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_workflow_run_steps_run "
        "ON workflow_run_steps(run_id, step_index)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_templates (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            slug VARCHAR(80) NOT NULL UNIQUE,
            name VARCHAR(150) NOT NULL,
            description TEXT,
            category VARCHAR(40) NOT NULL DEFAULT 'general',
            trigger_type VARCHAR(20) NOT NULL DEFAULT 'webhook',
            steps JSONB NOT NULL DEFAULT '[]',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )

    # Seed de plantillas.
    op.execute(
        """
        INSERT INTO workflow_templates (slug, name, description, category, trigger_type, steps) VALUES
        ('kb-digest', 'Resumen de base de conocimiento',
            'Revisa documentos recientes de la KB y notifica un resumen al equipo.',
            'knowledge', 'schedule',
            '[{"type": "kb_query", "config": {"query": "reciente", "limit": 5}},
              {"type": "llm", "config": {"prompt": "Resume estos documentos en 3 bullets: {{steps.0.output.documents}}", "model": "gpt-4o-mini"}},
              {"type": "notify", "config": {"channel": "in_app", "title": "Resumen KB", "message": "{{steps.1.output.text}}"}}]'),
        ('lead-alert', 'Alerta de leads calificados',
            'Detecta mensajes de leads con intención de compra y notifica a ventas.',
            'sales', 'webhook',
            '[{"type": "condition", "config": {"field": "trigger.message", "operator": "contains", "value": "precio"}},
              {"type": "llm", "config": {"prompt": "Clasifica la intención de: {{trigger.message}}", "model": "gpt-4o-mini"}},
              {"type": "notify", "config": {"channel": "email", "title": "Lead calificado", "message": "{{steps.1.output.text}}"}}]'),
        ('incident-escalate', 'Escalamiento de incidentes',
            'Escala incidentes abiertos con severidad alta al canal de operaciones.',
            'operations', 'event',
            '[{"type": "condition", "config": {"field": "trigger.severity", "operator": ">=", "value": "high"}},
              {"type": "notify", "config": {"channel": "in_app", "title": "Incidente escalado", "message": "Incidente {{trigger.id}} requiere atención"}}]'),
        ('daily-report', 'Reporte diario de uso',
            'Genera un reporte diario de uso y métricas del tenant.',
            'analytics', 'schedule',
            '[{"type": "llm", "config": {"prompt": "Genera un reporte de uso para: {{trigger.date}}", "model": "gpt-4o"}},
              {"type": "notify", "config": {"channel": "email", "title": "Reporte diario", "message": "{{steps.0.output.text}}"}}]')
        ON CONFLICT (slug) DO NOTHING
        """
    )


def downgrade() -> None:
    for table in ("workflow_templates", "workflow_run_steps", "workflow_runs", "workflows"):
        op.execute(f"DROP TABLE IF EXISTS {table}")
