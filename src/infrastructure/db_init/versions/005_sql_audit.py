"""SQL Audit — tabla de auditoría del motor Text-to-SQL.

Revision ID: 005
Revises: 004
Create Date: 2026-08-20

Registra question, generated_sql, tablas, tiempo, filas, costo y estado
de cada ejecución del SQL Expert. Nunca credenciales ni datos de negocio.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS sql_audit_logs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            user_id UUID,
            role VARCHAR(20) NOT NULL DEFAULT 'admin',
            question TEXT NOT NULL,
            generated_sql TEXT,
            tables JSONB NOT NULL DEFAULT '[]',
            execution_time_ms DOUBLE PRECISION DEFAULT 0,
            rows INTEGER DEFAULT 0,
            cost DOUBLE PRECISION,
            status VARCHAR(30) NOT NULL,
            error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_sql_audit_org "
        "ON sql_audit_logs(organization_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_sql_audit_status "
        "ON sql_audit_logs(organization_id, status, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS sql_audit_logs")
