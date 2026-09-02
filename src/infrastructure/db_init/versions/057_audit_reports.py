"""Tenant Audit & Compliance Reports v2 — audit_reports con hash encadenado,
compliance controls por framework.

Revision ID: 057
Revises: 056
Create Date: 2026-09-02
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "057"
down_revision: Union[str, None] = "056"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_reports (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            report_type VARCHAR(30) NOT NULL,
            period_start DATE NOT NULL,
            period_end DATE NOT NULL,
            format VARCHAR(10) NOT NULL DEFAULT 'csv',
            file_key VARCHAR(300) NOT NULL,
            size_bytes BIGINT NOT NULL DEFAULT 0,
            integrity_hash VARCHAR(64) NOT NULL,
            prev_hash VARCHAR(64),
            created_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at TIMESTAMPTZ NOT NULL DEFAULT NOW() + interval '90 days'
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_reports_org_time "
        "ON audit_reports(organization_id, created_at DESC)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS compliance_controls (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            framework VARCHAR(30) NOT NULL,
            control_id VARCHAR(40) NOT NULL,
            title VARCHAR(200) NOT NULL,
            category VARCHAR(60) NOT NULL DEFAULT 'general',
            required_evidence VARCHAR(120),
            enabled BOOLEAN NOT NULL DEFAULT true,
            UNIQUE (framework, control_id)
        )
        """
    )
    op.execute(
        """
        INSERT INTO compliance_controls (framework, control_id, title, category, required_evidence) VALUES
        ('soc2', 'CC2.1', 'Acceso a datos de clientes registrado y revisado', 'logical_access', 'audit_logs'),
        ('soc2', 'CC6.1', 'Cuentas con credenciales únicas y gestión de accesos', 'logical_access', 'users + api_keys'),
        ('soc2', 'CC7.2', 'Monitoreo de actividades anómalas del sistema', 'monitoring', 'incidents + alerts'),
        ('soc2', 'CC8.1', 'Detección y respuesta a incidentes de seguridad', 'incident_response', 'incidents'),
        ('soc2', 'A1.2', 'Disponibilidad: backups y DR probados', 'availability', 'dr_backups'),
        ('soc2', 'A1.3', 'Revisión de capacidad y rendimiento', 'availability', 'capacity'),
        ('soc2', 'C1.1', 'Información de configuración protegida', 'confidentiality', 'config'),
        ('soc2', 'C1.2', 'Retención de datos conforme a la política', 'confidentiality', 'retention'),
        ('gdpr', 'A.5', 'Minimización de datos personales', 'data_protection', 'pii'),
        ('gdpr', 'A.7', 'Claridad de propósitos de tratamiento', 'data_protection', 'aup'),
        ('gdpr', 'A.15', 'Derecho de acceso y portabilidad', 'data_subject', 'exports'),
        ('gdpr', 'A.16', 'Derecho de supresión (DSR)', 'data_subject', 'dsr'),
        ('gdpr', 'A.17', 'Consentimiento registrado', 'data_subject', 'aup_consents'),
        ('gdpr', 'A.24', 'Seguridad del tratamiento', 'security', 'guardrails'),
        ('gdpr', 'A.32', 'Pseudonimización y cifrado', 'security', 'kms + anonymization'),
        ('gdpr', 'A.33', 'Notificación de violaciones', 'breach', 'incidents'),
        ('iso27001', 'A.5.1', 'Políticas de seguridad de la información', 'policy', 'aup'),
        ('iso27001', 'A.6.1', 'Responsabilidades de roles y accesos', 'organization', 'rbac'),
        ('iso27001', 'A.8.2', 'Clasificación y etiquetado de información', 'assets', 'tags'),
        ('iso27001', 'A.9.1', 'Gestión de acceso de usuarios', 'access', 'keys'),
        ('iso27001', 'A.12.4', 'Registro de eventos y monitoreo', 'operations', 'audit_logs'),
        ('iso27001', 'A.13.1', 'Seguridad de la red', 'communications', 'rate_limits'),
        ('iso27001', 'A.16.1', 'Gestión de incidentes de seguridad', 'incident', 'incidents'),
        ('iso27001', 'A.18.1', 'Cumplimiento legal y contractual', 'compliance', 'retention')
        ON CONFLICT (framework, control_id) DO NOTHING
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS compliance_status (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            framework VARCHAR(30) NOT NULL,
            control_id VARCHAR(40) NOT NULL,
            status VARCHAR(10) NOT NULL DEFAULT 'review',
            evidence TEXT,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (organization_id, framework, control_id)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS compliance_status")
    op.execute("DROP TABLE IF EXISTS compliance_controls")
    op.execute("DROP TABLE IF EXISTS audit_reports")
