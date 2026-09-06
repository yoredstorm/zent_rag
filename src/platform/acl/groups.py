"""ACL documental por grupos (FASE 15): resolución de grupos de un usuario.

El pipeline retrieval filtra en Qdrant ANTES de entregar contexto al LLM:
visibility (public/admin) + acl_users + acl_groups. Esta resolución
provee los grupos del usuario autenticado para armar el filtro.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import text

from src.infrastructure.postgres.session import get_async_session


async def user_group_names(organization_id: UUID, user_id: UUID) -> list[str]:
    """Nombres de grupos del usuario en la org (para el filtro acl_groups)."""
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT g.name FROM org_groups g "
                    "JOIN org_group_memberships m ON m.group_id = g.id "
                    "WHERE g.organization_id = :oid AND m.user_id = :uid"
                ),
                {"oid": organization_id, "uid": user_id},
            )
        ).fetchall()
    except Exception:
        # Tabla opcional: sin grupos → lista vacía (org-wide por defecto).
        return []
    finally:
        await session.close()
    return [str(r.name) for r in rows if r.name]
