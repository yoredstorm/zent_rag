"""Connector Secrets — tabla de credenciales cifradas (fallback a Vault).

Revision ID: 007
Revises: 006
Create Date: 2026-08-21

Ciphertext AES-256-GCM (nonce prefijado). Nunca texto plano.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS connector_secrets (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            connector_id UUID NOT NULL,
            ciphertext BYTEA NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (organization_id, connector_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_connector_secrets_org "
        "ON connector_secrets(organization_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS connector_secrets")
