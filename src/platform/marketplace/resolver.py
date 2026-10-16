# =============================================================================
# Marketplace dependency resolver — capability-first.
#
# Un producto o workflow expresa QUÉ necesita ("payments.checkout.create"),
# no qué plugin específico. El resolver mapea:
#   capability -> providers publicados -> instalación concreta del tenant
# prefiriendo SIEMPRE una instalación existente (reuso real entre superficies).
#
# No crea catálogo ni runtime: lee integration_capabilities / manifests y usa
# el runtime existente para instalar.
# =============================================================================
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.postgres.session import get_async_session

_INSTALLED_STATUSES = ("installed", "connected", "active")


async def providers_for_capability(capability_ref: str) -> list[dict[str, Any]]:
    """Providers publicados que exponen una capability (orden estable)."""
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT m.id, m.slug, m.name, m.status "
                    "FROM integration_capabilities c "
                    "JOIN integration_manifests m ON m.id = c.integration_id "
                    "WHERE c.slug = :cap AND m.status IN ('PUBLISHED', 'DEPRECATED') "
                    "ORDER BY (m.status = 'PUBLISHED') DESC, m.slug"
                ),
                {"cap": capability_ref},
            )
        ).fetchall()
    finally:
        await session.close()
    return [
        {
            "integration_id": str(r.id),
            "slug": r.slug,
            "name": r.name,
            "status": r.status,
        }
        for r in rows
    ]


async def _installed_for(
    organization_id: UUID,
    workspace_id: UUID | None,
    integration_ids: list[str],
) -> dict[str, dict[str, Any]]:
    """integration_id -> {install_id,status} para el tenant/workspace."""
    if not integration_ids:
        return {}
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id, integration_id, status FROM installed_integrations "
                    "WHERE organization_id = :oid "
                    "AND workspace_id IS NOT DISTINCT FROM :ws "
                    "AND integration_id = ANY(:ids) "
                    "AND status = ANY(:ok) "
                    "ORDER BY created_at DESC"
                ),
                {
                    "oid": organization_id,
                    "ws": workspace_id,
                    "ids": [UUID(i) for i in integration_ids],
                    "ok": list(_INSTALLED_STATUSES),
                },
            )
        ).fetchall()
    finally:
        await session.close()
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        out.setdefault(
            str(r.integration_id),
            {"install_id": str(r.id), "status": r.status},
        )
    return out


async def resolve_capability(
    organization_id: UUID,
    capability_ref: str,
    *,
    workspace_id: UUID | None = None,
) -> dict[str, Any]:
    """Resuelve una capability a una instalación concreta o a un provider elegible.

    Resultado:
      resolved    — existe al menos un provider publicado
      installed   — ya hay instalación del tenant (reuso)
      integration_slug — provider elegido (instalado, si existe)
    """
    result: dict[str, Any] = {"capability": capability_ref, "resolved": False}
    candidates = await providers_for_capability(capability_ref)
    if not candidates:
        result["reason"] = "no_provider"
        return result
    installed = await _installed_for(
        organization_id, workspace_id, [c["integration_id"] for c in candidates]
    )
    for c in candidates:
        hit = installed.get(c["integration_id"])
        if hit:
            return {
                **result,
                "resolved": True,
                "installed": True,
                "install_id": hit["install_id"],
                "integration_slug": c["slug"],
                "provider_name": c["name"],
                "provider_id": c["integration_id"],
            }
    first = candidates[0]
    return {
        **result,
        "resolved": True,
        "installed": False,
        "install_id": None,
        "integration_slug": first["slug"],
        "provider_name": first["name"],
        "provider_id": first["integration_id"],
        "alternatives": [c["slug"] for c in candidates],
    }


async def _manifest_for_integration(integration_slug: str) -> dict[str, Any] | None:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT id, slug, name, status FROM integration_manifests "
                    "WHERE slug = :slug AND status IN ('PUBLISHED', 'DEPRECATED')"
                ),
                {"slug": integration_slug},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        return None
    return {
        "integration_id": str(row.id),
        "slug": row.slug,
        "name": row.name,
        "status": row.status,
    }


async def _manifest_for_action(action_id: str) -> dict[str, Any] | None:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT m.id, m.slug, m.name, m.status FROM integration_actions a "
                    "JOIN integration_manifests m ON m.id = a.integration_id "
                    "WHERE a.action_id = :aid AND m.status IN ('PUBLISHED', 'DEPRECATED')"
                ),
                {"aid": action_id},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        return None
    return {
        "integration_id": str(row.id),
        "slug": row.slug,
        "name": row.name,
        "status": row.status,
    }


async def resolve_dependency(
    organization_id: UUID,
    dep: dict[str, Any],
    *,
    workspace_id: UUID | None = None,
) -> dict[str, Any]:
    """Resuelve una dependencia tipada (kind, ref) a un estado concreto.

    kinds soportados aquí: capability, integration, action.
    Otros kinds (workflow_template, agent_template, product, semantic) se
    resuelven en factory.install_product porque instalan assets.
    """
    kind = str(dep.get("kind") or "").strip().lower()
    ref = str(dep.get("ref") or "").strip()
    base = {"kind": kind, "ref": ref, "requirement": dep.get("requirement") or "required"}
    if not kind or not ref:
        return {**base, "resolved": False, "reason": "dep_inválida"}
    if kind == "capability":
        out = await resolve_capability(organization_id, ref, workspace_id=workspace_id)
        return {**base, **out}
    if kind in ("integration", "action"):
        manifest = (
            await _manifest_for_integration(ref)
            if kind == "integration"
            else await _manifest_for_action(ref)
        )
        if manifest is None:
            return {**base, "resolved": False, "reason": "no_provider"}
        installed = await _installed_for(
            organization_id, workspace_id, [manifest["integration_id"]]
        )
        hit = installed.get(manifest["integration_id"])
        return {
            **base,
            "resolved": True,
            "installed": hit is not None,
            "install_id": hit["install_id"] if hit else None,
            "integration_slug": manifest["slug"],
            "provider_name": manifest["name"],
        }
    return {**base, "resolved": False, "reason": "kind_no_soportado"}
