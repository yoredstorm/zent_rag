"""Aplicaciones como origen del acceso: Organización → Aplicación → Agente.

Revision ID: 177
Revises: 176

Aditiva. Una aplicación identifica al producto o canal que consume Zent en
nombre de una organización (Mentora, OMNIO+, futuras). `api_keys.application_id`
NULL representa el acceso directo: el contrato de agente directo del cliente.
`partners` sigue siendo la relación comercial; la aplicación puede referenciarla.
"""
from __future__ import annotations

from alembic import op

revision: str = "182"
down_revision: str = "181"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS applications (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            code VARCHAR(60) NOT NULL UNIQUE,
            name VARCHAR(200) NOT NULL,
            kind VARCHAR(40) NOT NULL DEFAULT 'product',
            status VARCHAR(20) NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'suspended', 'retired')),
            partner_id UUID REFERENCES partners(id) ON DELETE SET NULL,
            description TEXT,
            config_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_applications_partner "
        "ON applications(partner_id)"
    )
    op.execute(
        "ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS application_id UUID "
        "REFERENCES applications(id) ON DELETE SET NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_api_keys_application "
        "ON api_keys(application_id)"
    )
    op.execute(
        "ALTER TABLE usage_events ADD COLUMN IF NOT EXISTS application_id UUID "
        "REFERENCES applications(id) ON DELETE SET NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_usage_events_application "
        "ON usage_events(organization_id, application_id, created_at DESC)"
    )
    op.execute(
        "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS application_id UUID "
        "REFERENCES applications(id) ON DELETE SET NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE audit_logs DROP COLUMN IF EXISTS application_id")
    op.execute("DROP INDEX IF EXISTS idx_usage_events_application")
    op.execute("ALTER TABLE usage_events DROP COLUMN IF EXISTS application_id")
    op.execute("DROP INDEX IF EXISTS idx_api_keys_application")
    op.execute("ALTER TABLE api_keys DROP COLUMN IF EXISTS application_id")
    op.execute("DROP INDEX IF EXISTS idx_applications_partner")
    op.execute("DROP TABLE IF EXISTS applications")
