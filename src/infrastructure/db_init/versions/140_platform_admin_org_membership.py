"""Allow platform admins to belong to an organization (dual Control Center + portal).

Revision ID: 140
Revises: 139
Create Date: 2026-10-03

La restricción original exigía ``organization_id IS NULL`` para los platform
admins, lo que impedía que una misma fila (un mismo email) operara en el
Control Center y en el portal de cliente. Se relaja: un platform admin puede
además pertenecer a una organización; los usuarios no-admin siguen
requiriendo organización.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "140"
down_revision: Union[str, None] = "139"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE users DROP CONSTRAINT IF EXISTS users_platform_admin_org_chk"
    )
    op.execute(
        """
        ALTER TABLE users ADD CONSTRAINT users_platform_admin_org_chk
            CHECK (is_platform_admin = true OR organization_id IS NOT NULL)
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE users DROP CONSTRAINT IF EXISTS users_platform_admin_org_chk"
    )
    op.execute(
        """
        ALTER TABLE users ADD CONSTRAINT users_platform_admin_org_chk
            CHECK (
                (is_platform_admin = true AND organization_id IS NULL)
                OR (is_platform_admin = false AND organization_id IS NOT NULL)
            )
        """
    )
