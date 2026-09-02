"""AI Ops Runbook & Incident Management v2 — runbooks, incidents, timelines,
escalation policies.

Revision ID: 049
Revises: 048
Create Date: 2026-09-01
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "049"
down_revision: Union[str, None] = "048"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS runbooks (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            trigger_type VARCHAR(60) NOT NULL,
            trigger_match VARCHAR(120) NOT NULL DEFAULT '*',
            title VARCHAR(160) NOT NULL,
            description TEXT,
            steps JSONB NOT NULL DEFAULT '[]',
            enabled BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        INSERT INTO runbooks (trigger_type, trigger_match, title, description, steps) VALUES
        ('cost_alert', '*', 'Revisar pico de costo',
         'Verificar el desglose por tag/modelo y ajustar presupuesto si es necesario.',
         '[{"action":"annotate","params":{"title":"Revisar desglose de costo por modelo"}},{"action":"send_webhook","params":{"event":"cost_spike"}},{"action":"sleep","params":{"seconds": 2}}]'),
        ('slo', '*', 'Rotar modelo por latencia',
         'Ante latencia alta, cambiar el modelo del agente al candidato más rápido.',
         '[{"action":"annotate","params":{"title":"Rotar a zent-fast"}},{"action":"send_webhook","params":{"event":"latency_high"}}]'),
        ('cost_alert', 'hallucination', 'Alerta de alucinación',
         'Revisar chunks y desactivar el modelo si la tasa supera el umbral.',
         '[{"action":"annotate","params":{"title":"Revisar chunks y desactivar modelo"}},{"action":"send_email","params":{"subject":"Alucinación detectada"}}]')
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS incidents (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            source VARCHAR(60) NOT NULL DEFAULT 'manual',
            severity VARCHAR(20) NOT NULL DEFAULT 'major',
            status VARCHAR(20) NOT NULL DEFAULT 'open',
            title VARCHAR(200) NOT NULL,
            description TEXT,
            occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            acknowledged_at TIMESTAMPTZ,
            resolved_at TIMESTAMPTZ,
            mttd_seconds DOUBLE PRECISION,
            mttr_seconds DOUBLE PRECISION,
            assigned_to VARCHAR(200),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_incidents_org_status "
        "ON incidents(organization_id, status, detected_at DESC)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS incident_events (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            incident_id UUID NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
            type VARCHAR(30) NOT NULL,
            detail TEXT,
            actor VARCHAR(200),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_incident_events_incident "
        "ON incident_events(incident_id, created_at)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS escalation_policies (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            severity VARCHAR(20) NOT NULL,
            steps JSONB NOT NULL DEFAULT '[]',
            enabled BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        INSERT INTO escalation_policies (severity, steps) VALUES
        ('severe', '[{"after_minutes": 5,"notify":["webhook"]},{"after_minutes": 15,"notify":["webhook","email"]}]'),
        ('major', '[{"after_minutes": 15,"notify":["webhook"]},{"after_minutes": 60,"notify":["webhook","email"]}]'),
        ('minor', '[{"after_minutes": 120,"notify":["webhook"]}]')
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS escalation_policies")
    op.execute("DROP TABLE IF EXISTS incident_events")
    op.execute("DROP TABLE IF EXISTS incidents")
    op.execute("DROP TABLE IF EXISTS runbooks")
