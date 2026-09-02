"""AI Trust & Safety Center — AUP versionado, moderación de contenido,
incidentes de seguridad.

Revision ID: 053
Revises: 052
Create Date: 2026-09-01
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "053"
down_revision: Union[str, None] = "052"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS aup_terms (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            version INT NOT NULL UNIQUE,
            title VARCHAR(200) NOT NULL,
            content TEXT NOT NULL,
            effective_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        INSERT INTO aup_terms (version, title, content) VALUES
        (1, 'Política de Uso Aceptable v1',
         '1. No usarás la plataforma para generar contenido ilegal, malicioso o que infrinja derechos de terceros.\n'
         '2. No intentarás evadir controles de seguridad, límites de uso ni la moderación de contenido.\n'
         '3. No usarás la plataforma para asesoría financiera, legal o médica profesional sin supervisión calificada.\n'
         '4. Los datos de clientes se tratan conforme a la política de retención y exportación vigente.\n'
         '5. El incumplimiento puede derivar en suspensión del servicio y reporte a las autoridades.')
        ON CONFLICT (version) DO NOTHING
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS aup_consents (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL UNIQUE,
            terms_version INT NOT NULL,
            consented_by UUID,
            consented_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS content_moderation_rules (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID,
            name VARCHAR(120) NOT NULL,
            category VARCHAR(40) NOT NULL DEFAULT 'prohibited_topics',
            patterns JSONB NOT NULL DEFAULT '[]',
            min_score DOUBLE PRECISION NOT NULL DEFAULT 0.6,
            action VARCHAR(10) NOT NULL DEFAULT 'block',
            enabled BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        INSERT INTO content_moderation_rules (organization_id, name, category, patterns, min_score, action) VALUES
        (NULL, 'Malware y exploits', 'malware',
         '["keylogger", "ransomware", "exploit", "cmd.exe", "meterpreter", "inyeccion sql", "reverse shell"]',
         0.5, 'block'),
        (NULL, 'Asesoría financiera', 'financial_advice',
         '["invertir en", "acciones de", "rendimiento garantizado", "esquema piramidal", "forex sin riesgo"]',
         0.6, 'warn'),
        (NULL, 'Temas prohibidos base', 'prohibited_topics',
         '["fabricar armas", "recetas de drogas", "hackear cuenta", "fraude de identidad"]',
         0.5, 'block'),
        (NULL, 'Toxicidad', 'toxicity',
         '["idiota", "estupido", "mierda"]',
         0.6, 'warn')
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS safety_incidents (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            direction VARCHAR(10) NOT NULL DEFAULT 'input',
            rule_id UUID,
            rule_name VARCHAR(120) NOT NULL,
            score DOUBLE PRECISION NOT NULL DEFAULT 0,
            snippet TEXT,
            action VARCHAR(10) NOT NULL DEFAULT 'block',
            status VARCHAR(20) NOT NULL DEFAULT 'open',
            resolved_by UUID,
            resolved_at TIMESTAMPTZ,
            resolution_note TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_safety_incidents_org_time "
        "ON safety_incidents(organization_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_safety_incidents_status "
        "ON safety_incidents(status, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS safety_incidents")
    op.execute("DROP TABLE IF EXISTS content_moderation_rules")
    op.execute("DROP TABLE IF EXISTS aup_consents")
    op.execute("DROP TABLE IF EXISTS aup_terms")
