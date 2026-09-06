"""Delegated permissions del agente (FASE 03, S17/S18).

Permisos efectivos = caller ∩ agente ∩ tool ∩ policy. Compat: un agente SIN
grants explícitos conserva el comportamiento actual (permisos del caller);
con grants, la intersección se aplica (nunca hereda privilegios ilimitados).
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import text

from src.infrastructure.postgres.session import get_async_session

# Sentinel para deny-all explícito (nunca es un permiso real).
_DENY_ALL = "__zent_deny_all__"


async def get_agent_permissions(agent_id: UUID) -> frozenset[str] | None:
    """Devuelve los grants del agente o None si no tiene permisos declarados.

    None = compat (usa permisos del caller). frozenset() con el sentinel
    _DENY_ALL = deny-all explícito.
    """
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT permission FROM agent_permissions WHERE agent_id = :aid"
                ),
                {"aid": agent_id},
            )
        ).fetchall()
    finally:
        await session.close()
    return frozenset(str(r.permission) for r in rows) if rows else None


async def set_agent_permissions(
    organization_id: UUID, agent_id: UUID, permissions: list[str]
) -> None:
    """Reemplaza los grants del agente; [] = deny-all explícito (sentinel)."""
    session = await get_async_session()
    try:
        exists = (
            await session.execute(
                text(
                    "SELECT 1 FROM agents WHERE id = :aid AND organization_id = :oid"
                ),
                {"aid": agent_id, "oid": organization_id},
            )
        ).fetchone()
        if exists is None:
            raise ValueError("agent_not_found")
        await session.execute(
            text("DELETE FROM agent_permissions WHERE agent_id = :aid"),
            {"aid": agent_id},
        )
        perms = set(permissions) or {_DENY_ALL}
        for perm in perms:
            await session.execute(
                text(
                    "INSERT INTO agent_permissions (agent_id, permission) "
                    "VALUES (:aid, :perm)"
                ),
                {"aid": agent_id, "perm": perm[:60]},
            )
        await session.commit()
    finally:
        await session.close()
