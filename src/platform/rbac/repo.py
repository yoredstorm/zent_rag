# =============================================================================
# Platform RBAC — repositorio de roles de plataforma (Control Center)
# =============================================================================
from __future__ import annotations

from uuid import UUID

from sqlalchemy import text

from src.infrastructure.postgres.session import get_async_session


async def get_platform_roles_for_user(user_id: UUID) -> tuple[list[str], set[str]]:
    """(nombres de rol, permisos) de un usuario de plataforma."""
    session = await get_async_session()
    try:
        result = await session.execute(
            text(
                "SELECT pr.name AS role_name, p.code AS permission "
                "FROM user_platform_roles upr "
                "JOIN platform_roles pr ON pr.id = upr.role_id "
                "LEFT JOIN platform_role_permissions prp ON prp.role_id = pr.id "
                "LEFT JOIN permissions p ON p.id = prp.permission_id "
                "WHERE upr.user_id = :uid"
            ),
            {"uid": user_id},
        )
        rows = result.fetchall()
    finally:
        await session.close()
    roles: list[str] = []
    permissions: set[str] = set()
    for row in rows:
        if row.role_name and row.role_name not in roles:
            roles.append(row.role_name)
        if row.permission:
            permissions.add(row.permission)
    return roles, permissions


async def list_platform_roles() -> list[dict]:
    """Roles de plataforma con sus permisos (para la UI del Control Center)."""
    session = await get_async_session()
    try:
        result = await session.execute(
            text(
                "SELECT pr.id, pr.name, pr.description, pr.is_system, "
                "COALESCE(array_agg(p.code ORDER BY p.code) FILTER (WHERE p.code IS NOT NULL), '{}') AS perms "
                "FROM platform_roles pr "
                "LEFT JOIN platform_role_permissions prp ON prp.role_id = pr.id "
                "LEFT JOIN permissions p ON p.id = prp.permission_id "
                "GROUP BY pr.id, pr.name, pr.description, pr.is_system "
                "ORDER BY pr.is_system DESC, pr.name"
            )
        )
        rows = result.fetchall()
    finally:
        await session.close()
    return [
        {
            "id": str(row.id),
            "name": row.name,
            "description": row.description,
            "is_system": row.is_system,
            "permissions": list(row.perms),
        }
        for row in rows
    ]


async def list_platform_users() -> list[dict]:
    """Usuarios de plataforma (email + roles)."""
    session = await get_async_session()
    try:
        result = await session.execute(
            text(
                "SELECT u.id, u.email, u.is_platform_admin, "
                "COALESCE(array_agg(pr.name ORDER BY pr.name) FILTER (WHERE pr.name IS NOT NULL), '{}') AS roles "
                "FROM users u "
                "LEFT JOIN user_platform_roles upr ON upr.user_id = u.id "
                "LEFT JOIN platform_roles pr ON pr.id = upr.role_id "
                "WHERE u.is_platform_admin OR upr.user_id IS NOT NULL "
                "GROUP BY u.id, u.email, u.is_platform_admin "
                "ORDER BY u.email"
            )
        )
        rows = result.fetchall()
    finally:
        await session.close()
    return [
        {
            "id": str(row.id),
            "email": row.email,
            "is_platform_admin": row.is_platform_admin,
            "roles": list(row.roles),
        }
        for row in rows
    ]


async def assign_platform_role(user_id: UUID, role_name: str) -> bool:
    """Asigna un rol de plataforma a un usuario. True si cambió algo."""
    session = await get_async_session()
    try:
        result = await session.execute(
            text(
                "INSERT INTO user_platform_roles (user_id, role_id) "
                "SELECT :uid, id FROM platform_roles WHERE name = :role "
                "ON CONFLICT DO NOTHING"
            ),
            {"uid": user_id, "role": role_name},
        )
        await session.execute(
            text("UPDATE users SET is_platform_admin = true WHERE id = :uid"),
            {"uid": user_id},
        )
        await session.commit()
        return result.rowcount > 0
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def revoke_platform_role(user_id: UUID, role_name: str) -> bool:
    """Revoca un rol de plataforma. True si cambió algo."""
    session = await get_async_session()
    try:
        result = await session.execute(
            text(
                "DELETE FROM user_platform_roles "
                "WHERE user_id = :uid AND role_id IN "
                "(SELECT id FROM platform_roles WHERE name = :role)"
            ),
            {"uid": user_id, "role": role_name},
        )
        remaining = await session.execute(
            text("SELECT COUNT(*) FROM user_platform_roles WHERE user_id = :uid"),
            {"uid": user_id},
        )
        if remaining.scalar() == 0:
            await session.execute(
                text("UPDATE users SET is_platform_admin = false WHERE id = :uid"),
                {"uid": user_id},
            )
        await session.commit()
        return result.rowcount > 0
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def role_name_exists(role_name: str, organization_id: UUID | None = None) -> bool:
    """¿Existe un rol (sistema o de la organización) asignable a un miembro?"""
    session = await get_async_session()
    try:
        result = await session.execute(
            text(
                "SELECT COUNT(*) FROM roles "
                "WHERE name = :name AND (organization_id IS NULL OR organization_id = :org)"
            ),
            {"name": role_name, "org": organization_id},
        )
        return result.scalar() > 0
    finally:
        await session.close()
