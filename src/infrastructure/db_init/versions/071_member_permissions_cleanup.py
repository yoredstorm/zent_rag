"""RBAC — Restringe role_permissions del rol global 'member' a su lista canónica.

La migración 024 (y su espejo SQL 27-workspaces) otorgó al rol 'member'
TODOS los permisos existentes al momento de ejecutarse (CROSS JOIN sin filtro
de código), incluyendo permisos de plataforma (admin:sql, tenant.write,
deployments:promote, platform.settings.manage, …). En bases nuevas con el
baseline SQL (CI, docker volumes vacíos), el espejo 27 corría DESPUÉS de
26-platform-rbac.sql, por lo que 'member' heredaba también los permisos de
plataforma — elevación de privilegios silenciosa.

Las bases nuevas ya no tienen el bug (024/27 corregidas); esta migración
limpia bases existentes (volúmenes docker, deploys previos). Idempotente:
en una base sin el bug no borra nada.

Revision ID: 071
Revises: 070
Create Date: 2026-09-04
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "071"
down_revision: Union[str, None] = "070"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_MEMBER_CANONICAL_PERMISSIONS = (
    "org:read",
    "users:read",
    "apikeys:read",
    "projects:read",
    "projects:write",
    "kbs:read",
    "kbs:write",
    "agents:read",
    "agents:write",
    "agents:version",
    "agents:execute",
    "connectors:read",
    "connectors:write",
    "sources:read",
    "sources:write",
    "usage:read",
    "billing:read",
    "audit:read",
    "rag:query",
    "rag:ingest",
    "rag:read",
    "rag:write",
    "deployments:read",
    "workspaces:read",
    "workspaces:write",
)


def upgrade() -> None:
    codes = ", ".join(f"'{c}'" for c in _MEMBER_CANONICAL_PERMISSIONS)
    op.execute(
        f"""
        DELETE FROM role_permissions
        WHERE role_id = (
                SELECT id FROM roles
                WHERE organization_id IS NULL AND name = 'member'
            )
          AND permission_id IN (
                SELECT id FROM permissions WHERE code NOT IN ({codes})
            )
        """
    )


def downgrade() -> None:
    """No reversible: el grant excesivo era un bug; no se restaura."""
