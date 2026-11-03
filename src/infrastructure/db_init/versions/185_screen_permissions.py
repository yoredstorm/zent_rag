"""Permisos de API por pantalla.

Revision ID: 180
Revises: 179

Aditiva. Cada pantalla declara qué permisos de API necesita:
- `permissions`: se otorgan con permiso de lectura sobre la pantalla.
- `write_permissions`: se otorgan solo con acceso total (`full`).

Así el menú y la API hablan el mismo idioma: si al usuario se le asigna una
pantalla, sus endpoints dejan de responder 403.
"""
from __future__ import annotations

from alembic import op

revision: str = "185"
down_revision: str = "184"
branch_labels = None
depends_on = None

# code, permisos de lectura, permisos de escritura
_MAP: list[tuple[str, list[str], list[str]]] = [
    ("overview", ["tenant.read", "analytics.read", "operations.read"], []),
    ("tenants", ["tenant.read"], ["tenant.write"]),
    ("applications", ["tenant.read"], ["platform.settings.manage"]),
    ("customers", ["tenant.read"], []),
    ("subscriptions", ["billing.read"], ["billing.manage"]),
    ("revenue", ["analytics.read", "billing.read"], []),
    ("partners", ["tenant.read"], ["platform.settings.manage"]),
    ("staff", [], ["platform.users.manage"]),
    ("settings", [], ["platform.settings.manage"]),
    ("notifications", ["operations.read"], []),
    ("usage", ["analytics.read"], []),
    ("costs", ["analytics.read", "billing.read"], []),
    ("capacity", ["analytics.read", "operations.read"], []),
    ("status", ["operations.read"], []),
    ("operations", ["operations.read"], []),
    ("ops-center", ["operations.read"], []),
    ("regions", ["operations.read"], []),
    ("dr", ["operations.read"], []),
    ("migrations", ["operations.read"], ["tenant.write"]),
    ("releases", ["tenant.read"], []),
    ("data-export", ["tenant.read"], ["tenant.write"]),
    ("audit", ["audit.read"], []),
    ("audit-intel", ["audit.read"], []),
    ("security", [], ["platform.users.manage"]),
    ("marketplace", ["tenant.read"], []),
    ("marketplace-factory", ["tenant.read"], ["platform.settings.manage"]),
    ("ecosystem", ["tenant.read"], []),
    ("onboarding", ["tenant.read"], []),
    ("trust", ["audit.read", "operations.read"], []),
    ("security-center", ["audit.read", "operations.read"], []),
    ("trust-safety", ["audit.read", "operations.read"], []),
    ("risk-center", ["audit.read", "operations.read"], []),
    ("governance", ["audit.read", "operations.read"], []),
    ("compliance", ["audit.read", "operations.read"], []),
]


def _json(values: list[str]) -> str:
    return "[" + ", ".join(f'"{value}"' for value in values) + "]"


def upgrade() -> None:
    op.execute(
        "ALTER TABLE screens ADD COLUMN IF NOT EXISTS "
        "permissions JSONB NOT NULL DEFAULT '[]'::jsonb"
    )
    op.execute(
        "ALTER TABLE screens ADD COLUMN IF NOT EXISTS "
        "write_permissions JSONB NOT NULL DEFAULT '[]'::jsonb"
    )
    for code, permissions, write_permissions in _MAP:
        op.execute(
            "UPDATE screens SET permissions = '{perms}'::jsonb, "
            "write_permissions = '{writes}'::jsonb WHERE code = '{code}'".format(
                perms=_json(permissions),
                writes=_json(write_permissions),
                code=code,
            )
        )


def downgrade() -> None:
    op.execute("ALTER TABLE screens DROP COLUMN IF EXISTS write_permissions")
    op.execute("ALTER TABLE screens DROP COLUMN IF EXISTS permissions")
