"""AI Risk & Compliance Center v2.

Revision ID: 066
Revises: 065
Create Date: 2026-09-03
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "066"
down_revision: Union[str, None] = "065"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_risks (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            agent_id UUID,
            risk_type VARCHAR(30) NOT NULL,
            severity VARCHAR(15) NOT NULL DEFAULT 'low',
            likelihood DOUBLE PRECISION NOT NULL DEFAULT 0,
            impact DOUBLE PRECISION NOT NULL DEFAULT 0,
            score DOUBLE PRECISION NOT NULL DEFAULT 0,
            status VARCHAR(15) NOT NULL DEFAULT 'open',
            source VARCHAR(10) NOT NULL DEFAULT 'auto',
            evidence JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            mitigated_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_risks_org "
        "ON ai_risks(organization_id, status, score DESC)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS risk_mitigations (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            risk_id UUID NOT NULL,
            action_type VARCHAR(20) NOT NULL DEFAULT 'mitigation',
            description TEXT,
            performed_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS compliance_posture_snapshots (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            date DATE NOT NULL,
            framework VARCHAR(20) NOT NULL,
            score DOUBLE PRECISION NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (organization_id, date, framework)
        )
        """
    )
    # Vincular controles existentes a tipos de riesgo + framework IA Act.
    op.execute(
        "ALTER TABLE compliance_controls "
        "ADD COLUMN IF NOT EXISTS risk_type VARCHAR(30)"
    )
    op.execute(
        "INSERT INTO compliance_controls (id, framework, control_id, title, category, "
        "required_evidence, risk_type) VALUES "
        "('00000000-0000-0000-0000-00000000a101', 'eu_ai_act', 'EUAI-01', "
        "'Evaluación de riesgo del sistema de IA', 'governance', 'AI risk assessment document', 'hallucination'), "
        "('00000000-0000-0000-0000-00000000a102', 'eu_ai_act', 'EUAI-02', "
        "'Supervisión humana de decisiones automatizadas', 'governance', 'Human oversight log', 'bias'), "
        "('00000000-0000-0000-0000-00000000a103', 'eu_ai_act', 'EUAI-03', "
        "'Calidad de datos de entrenamiento', 'data', 'Data quality report', 'bias'), "
        "('00000000-0000-0000-0000-00000000a104', 'eu_ai_act', 'EUAI-04', "
        "'Trazabilidad y registro de decisiones', 'transparency', 'Decision trace logs', 'hallucination'), "
        "('00000000-0000-0000-0000-00000000a105', 'eu_ai_act', 'EUAI-05', "
        "'Transparencia hacia los usuarios finales', 'transparency', 'Disclosure templates', 'safety'), "
        "('00000000-0000-0000-0000-00000000a106', 'eu_ai_act', 'EUAI-06', "
        "'Robustez ante errores y fallos', 'security', 'Robustness test results', 'security'), "
        "('00000000-0000-0000-0000-00000000a107', 'eu_ai_act', 'EUAI-07', "
        "'Protección de datos personales (GDPR)', 'data', 'DPIA record', 'pii_leak'), "
        "('00000000-0000-0000-0000-00000000a108', 'eu_ai_act', 'EUAI-08', "
        "'Gestión de incidentes de seguridad', 'security', 'Incident response plan', 'security') "
        "ON CONFLICT (framework, control_id) DO NOTHING"
    )


def downgrade() -> None:
    for table in ("compliance_posture_snapshots", "risk_mitigations", "ai_risks"):
        op.execute(f"DROP TABLE IF EXISTS {table}")
