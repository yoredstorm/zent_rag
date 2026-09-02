"""Enterprise — SCIM provisioning + OIDC SSO + key policy.

Revision ID: 031
Revises: 030
Create Date: 2026-08-31
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "031"
down_revision: Union[str, None] = "030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # API keys v2: política de expiración forzada por organización.
    op.execute("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS key_max_age_days INT")
    # SCIM provisioning.
    op.execute(
        "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS scim_enabled BOOLEAN "
        "NOT NULL DEFAULT false"
    )
    op.execute(
        "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS scim_token_hash VARCHAR(64)"
    )
    # SSO OIDC (secreto cifrado en reposo).
    op.execute(
        "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS sso_enabled BOOLEAN "
        "NOT NULL DEFAULT false"
    )
    op.execute(
        "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS sso_oidc_issuer VARCHAR(300)"
    )
    op.execute(
        "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS sso_oidc_client_id VARCHAR(200)"
    )
    op.execute(
        "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS sso_oidc_client_secret_enc VARCHAR(600)"
    )
    op.execute(
        "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS sso_oidc_roles_claim VARCHAR(50) "
        "DEFAULT 'roles'"
    )
    # Grupos SCIM → rol de tenant.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS scim_groups (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            display_name VARCHAR(200) NOT NULL,
            role_name VARCHAR(50) NOT NULL DEFAULT 'member',
            members JSONB NOT NULL DEFAULT '[]',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (organization_id, display_name)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS scim_groups")
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS sso_oidc_roles_claim")
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS sso_oidc_client_secret_enc")
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS sso_oidc_client_id")
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS sso_oidc_issuer")
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS sso_enabled")
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS scim_token_hash")
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS scim_enabled")
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS key_max_age_days")
