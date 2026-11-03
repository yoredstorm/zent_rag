"""Requerimientos de cambio con token temporal.

Revision ID: 183
Revises: 182

Todo cambio de configuración de una organización necesita un requerimiento
abierto. Al tomarlo, el operador recibe un token temporal (hash en la tabla)
limitado a esa organización; al resolverlo, el token se revoca.

La auditoría no gana columna: cada mutación registra `change_request_id` en el
`metadata` de `audit_logs`, que ya es JSONB.
"""
from __future__ import annotations

from alembic import op

revision: str = "188"
down_revision: str = "187"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS change_requests (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            kind VARCHAR(30) NOT NULL DEFAULT 'other',
            title VARCHAR(200) NOT NULL,
            description TEXT NOT NULL,
            scopes JSONB NOT NULL DEFAULT '["tenant.write"]'::jsonb,
            status VARCHAR(20) NOT NULL DEFAULT 'open'
                CHECK (status IN ('open', 'taken', 'resolved', 'cancelled', 'expired')),
            opened_by UUID REFERENCES users(id) ON DELETE SET NULL,
            taken_by UUID REFERENCES users(id) ON DELETE SET NULL,
            taken_at TIMESTAMPTZ,
            grant_token_hash VARCHAR(64),
            grant_expires_at TIMESTAMPTZ,
            revoked_at TIMESTAMPTZ,
            resolved_by UUID REFERENCES users(id) ON DELETE SET NULL,
            resolved_at TIMESTAMPTZ,
            resolution_note TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_change_requests_org "
        "ON change_requests(organization_id, status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_change_requests_grant "
        "ON change_requests(grant_token_hash) WHERE grant_token_hash IS NOT NULL"
    )
    op.execute(
        "INSERT INTO screens (code, name, category, path, sort_order) VALUES "
        "('change-requests', 'Requerimientos', 'General', "
        "'/control-center/change-requests', 30) ON CONFLICT (code) DO NOTHING"
    )


def downgrade() -> None:
    op.execute("DELETE FROM screens WHERE code = 'change-requests'")
    op.execute("DROP TABLE IF EXISTS change_requests")
