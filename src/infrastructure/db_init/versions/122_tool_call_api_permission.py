"""Permiso `tool:call_api` para ejecución directa de tools HTTP.

El tool builtin `call_api` declara `permission = "tool:call_api"`, pero el
permiso nunca se sembró (migración 119 solo creó `sources:sql` y
`tool:query_database`). Resultado: ni el Agent Runtime ni el dispatcher podían
ejecutarlo salvo wildcard `admin:*`.

Se otorga a owner/admin, igual que el SQL de usuario/agente (migración 119).

Revision ID: 122
Revises: 121
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision: str = "122"
down_revision: str = "121"
branch_labels = None
depends_on = None

_PERMISSION_ID = "40000000-0000-0000-0000-000000000104"
_PERMISSION_CODE = "tool:call_api"
_ROLES = ("owner", "admin")


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        text(
            "INSERT INTO permissions (id, code, description) VALUES (:pid, :code, :desc) "
            "ON CONFLICT (code) DO NOTHING"
        ),
        {
            "pid": _PERMISSION_ID,
            "code": _PERMISSION_CODE,
            "desc": "Ejecutar el tool call_api (HTTP saliente con guards SSRF)",
        },
    )
    role_list = ", ".join(f"'{role}'" for role in _ROLES)
    bind.execute(
        text(
            "INSERT INTO role_permissions (role_id, permission_id) "
            "SELECT r.id, p.id FROM roles r CROSS JOIN permissions p "
            f"WHERE r.organization_id IS NULL AND r.name IN ({role_list}) "
            "AND p.code = :perm ON CONFLICT DO NOTHING"
        ),
        {"perm": _PERMISSION_CODE},
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        text(
            "DELETE FROM role_permissions WHERE permission_id IN "
            "(SELECT id FROM permissions WHERE code = :perm)"
        ),
        {"perm": _PERMISSION_CODE},
    )
    bind.execute(
        text("DELETE FROM permissions WHERE code = :perm"),
        {"perm": _PERMISSION_CODE},
    )
