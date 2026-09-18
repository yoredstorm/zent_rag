"""Exponer tablas materializadas — permisos `sources:sql` y `tool:query_database`.

P4 (A+B+C): visor de datos y consola SQL read-only por fuente en el portal,
y SQL para agentes sobre la Managed DB. Antes no existía ningún permiso para
SQL de usuario/agente: el tool `query_database` pedía `tool:query_database`
(inexistente) y nunca pasaba el gate RBAC.

Se otorgan a owner/admin. member/customer no reciben SQL libre.

Revision ID: 119
Revises: 118
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision: str = "119"
down_revision: str = "118"
branch_labels = None
depends_on = None

_PERMISSIONS = [
    (
        "40000000-0000-0000-0000-000000000102",
        "sources:sql",
        "Consultar por SQL (solo lectura) las tablas materializadas de una fuente",
    ),
    (
        "40000000-0000-0000-0000-000000000103",
        "tool:query_database",
        "Ejecutar el tool query_database (Text-to-SQL) de los agentes",
    ),
]

_SQL_ROLES = ("owner", "admin")


def upgrade() -> None:
    bind = op.get_bind()
    for pid, code, desc in _PERMISSIONS:
        bind.execute(
            text(
                "INSERT INTO permissions (id, code, description) VALUES (:pid, :code, :desc) "
                "ON CONFLICT (code) DO NOTHING"
            ),
            {"pid": pid, "code": code, "desc": desc},
        )
    role_list = ", ".join(f"'{role}'" for role in _SQL_ROLES)
    for _pid, code, _desc in _PERMISSIONS:
        bind.execute(
            text(
                "INSERT INTO role_permissions (role_id, permission_id) "
                "SELECT r.id, p.id FROM roles r CROSS JOIN permissions p "
                f"WHERE r.organization_id IS NULL AND r.name IN ({role_list}) "
                "AND p.code = :perm ON CONFLICT DO NOTHING"
            ),
            {"perm": code},
        )


def downgrade() -> None:
    bind = op.get_bind()
    for _pid, code, _desc in _PERMISSIONS:
        bind.execute(
            text(
                "DELETE FROM role_permissions WHERE permission_id IN "
                "(SELECT id FROM permissions WHERE code = :perm)"
            ),
            {"perm": code},
        )
        bind.execute(text("DELETE FROM permissions WHERE code = :perm"), {"perm": code})
