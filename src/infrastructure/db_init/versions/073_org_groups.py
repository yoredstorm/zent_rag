"""Grupos ACL documental (FASE 15): org_groups + org_group_memberships."""

from alembic import op

revision = "073"
down_revision = "072"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS org_groups (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            name VARCHAR(120) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (organization_id, name)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS org_group_memberships (
            group_id UUID NOT NULL REFERENCES org_groups(id) ON DELETE CASCADE,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (group_id, user_id)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS org_group_memberships")
    op.execute("DROP TABLE IF EXISTS org_groups")
