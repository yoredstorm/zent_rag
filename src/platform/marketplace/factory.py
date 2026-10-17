# =============================================================================
# Phase 33A — Marketplace Factory: composición, instalación con resolución
# de dependencias tipadas, readiness, test lab y migración legacy.
#
# Refes tipados: dependency.integration.<alias>.install_id,
#                 dependency.workflow.<alias>.workflow_id,
#                 dependency.agent.<alias>.agent_id,
#                 dependency.action.<alias>.action_id,
#                 answers.<question_key>
# =============================================================================
from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session
from src.platform.marketplace.products import (
    ProductError,
    ensure_zend_provider,
    get_product,
    normalize_pricing,
    save_product,
)

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Paleta de assets disponibles para el builder (Control Center)
# ---------------------------------------------------------------------------
async def assets_palette() -> dict:
    """Todo lo que el Product Studio puede incluir en un producto."""
    session = await get_async_session()
    try:
        integrations = (
            await session.execute(
                text(
                    "SELECT m.slug, m.name, m.description, m.category, m.status "
                    "FROM integration_manifests m ORDER BY m.category, m.name"
                )
            )
        ).fetchall()
        actions = (
            await session.execute(
                text(
                    "SELECT a.action_id, a.display_name, a.description, a.read_only, "
                    "a.requires_approval, a.risk_level, m.slug AS integration_slug "
                    "FROM integration_actions a "
                    "JOIN integration_manifests m ON m.id = a.integration_id "
                    "WHERE a.status = 'ACTIVE' ORDER BY a.action_id"
                )
            )
        ).fetchall()
        wf_templates = (
            await session.execute(
                text("SELECT slug, name, description, trigger_type FROM workflow_templates ORDER BY name")
            )
        ).fetchall()
        agents = (
            await session.execute(
                text(
                    "SELECT id, name FROM agents ORDER BY created_at DESC LIMIT 200"
                )
            )
        ).fetchall()
        products = (
            await session.execute(
                text(
                    "SELECT slug, name, product_type, status FROM marketplace_products "
                    "WHERE status IN ('PUBLISHED', 'READY') ORDER BY name"
                )
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "integrations": [
            {"slug": i.slug, "name": i.name, "description": i.description, "category": i.category, "status": i.status}
            for i in integrations
        ],
        "actions": [
            {
                "action_id": a.action_id,
                "display_name": a.display_name,
                "read_only": bool(a.read_only),
                "requires_approval": bool(a.requires_approval),
                "risk_level": a.risk_level,
                "integration_slug": a.integration_slug,
            }
            for a in actions
        ],
        "workflow_templates": [
            {"slug": w.slug, "name": w.name, "description": w.description, "trigger_type": w.trigger_type}
            for w in wf_templates
        ],
        "agents": [{"id": str(a.id), "name": a.name} for a in agents],
        "products": [
            {"slug": p.slug, "name": p.name, "product_type": p.product_type, "status": p.status}
            for p in products
        ],
    }


# ---------------------------------------------------------------------------
# Test lab — normalización de salida sin llamadas externas
# ---------------------------------------------------------------------------
def test_output_normalizer(output_map: dict, sample: dict) -> dict:
    """Aplica el output_map declarativo a un sample del proveedor (lab)."""
    normalized: dict[str, Any] = {}
    for field, source_path in (output_map or {}).items():
        cur = sample
        for part in str(source_path).split("."):
            if isinstance(cur, dict):
                cur = cur.get(part)
            else:
                cur = None
                break
        if cur is not None:
            normalized[field] = cur
    return normalized


# ---------------------------------------------------------------------------
# Dependencias capability-first y readiness de instalación
# ---------------------------------------------------------------------------
_INTEGRATION_DEP_KINDS = ("integration", "capability", "action")


def _integration_asset_ids(configured: dict[str, str]) -> dict[str, str]:
    """alias -> integration install_id desde las refs dependency.*.install_id."""
    out: dict[str, str] = {}
    for key, value in (configured or {}).items():
        if not key.startswith("dependency.") or not key.endswith(".install_id"):
            continue
        parts = key.split(".")
        if len(parts) >= 4 and parts[1] in _INTEGRATION_DEP_KINDS:
            out[parts[2]] = str(value)
    return out


async def _resolve_product_dependencies(
    organization_id: UUID,
    product: dict,
    *,
    workspace_id: UUID | None,
    created_by: UUID | None,
    answers: dict,
    purpose: str | None = None,
) -> tuple[dict[str, str], dict[str, str], list[dict[str, str]]]:
    """Resuelve dependencias tipadas capability-first.

    Reuso primero: si el tenant ya tiene la instalación, se referencia. Si no,
    se instala el provider elegido. Devuelve (mapping, configured, issues).
    """
    from src.platform.marketplace.resolver import resolve_dependency
    from src.platform.marketplace.runtime import install_integration

    mapping: dict[str, str] = {}
    configured: dict[str, str] = {}
    issues: list[dict[str, str]] = []
    for dep in product.get("dependencies") or []:
        kind = str(dep.get("kind") or "").strip().lower()
        if kind not in _INTEGRATION_DEP_KINDS:
            continue
        requirement = str(dep.get("requirement") or "required")
        ref = str(dep.get("ref") or "")
        alias = str(dep.get("alias") or ref or kind)
        try:
            resolved = await resolve_dependency(
                organization_id, dep, workspace_id=workspace_id
            )
        except Exception as exc:  # noqa: BLE001
            resolved = {"resolved": False, "reason": str(exc)[:160]}
        if not resolved.get("resolved"):
            message = (
                f"dependencia '{ref}' ({kind}) no resoluble: "
                f"{resolved.get('reason', 'sin provider publicado')}"
            )
            if requirement == "required":
                issues.append({"kind": kind, "ref": ref, "message": message})
            else:
                logger.info("optional dependency unresolved", kind=kind, ref=ref)
            continue
        slug = str(resolved.get("integration_slug") or "")
        install_id = resolved.get("install_id")
        if not install_id and slug:
            try:
                install = await install_integration(
                    organization_id,
                    slug,
                    workspace_id=workspace_id,
                    created_by=created_by,
                    purpose=purpose,
                )
                install_id = install["install_id"]
            except Exception as exc:  # noqa: BLE001
                if requirement == "required":
                    issues.append({"kind": kind, "ref": slug, "message": str(exc)[:200]})
                continue
        if install_id:
            mapping[f"dependency.{kind}.{alias}.install_id"] = str(install_id)
            configured[f"dependency.{kind}.{alias}.install_id"] = str(install_id)
            if kind != "capability":
                mapping[f"dependency.integration.{slug}.install_id"] = str(install_id)
                configured[f"dependency.integration.{slug}.install_id"] = str(install_id)
    _ = answers  # reservado: respuestas pueden parametrizar deps en el futuro
    return mapping, configured, issues


async def _apply_product_assets(
    organization_id: UUID,
    product: dict,
    *,
    workspace_id: UUID | None,
    created_by: UUID | None,
    answers: dict,
    purpose: str | None = None,
) -> tuple[dict[str, str], dict[str, str], list[str], list[str], list[dict[str, str]]]:
    """Instala/resuelve todos los assets de un producto con reuso.

    Devuelve (mapping, configured, workflow_ids, agent_ids, issues).
    """
    from src.platform.marketplace.runtime import install_integration

    mapping, configured, issues = await _resolve_product_dependencies(
        organization_id,
        product,
        workspace_id=workspace_id,
        created_by=created_by,
        answers=answers,
        purpose=purpose,
    )
    workflow_ids: list[str] = []
    agent_ids: list[str] = []

    for asset in product.get("included_assets") or []:
        kind = str(asset.get("kind") or "")
        ref = str(asset.get("ref") or "")
        alias = str(asset.get("alias") or ref)
        try:
            if kind in ("integration", "capability"):
                install = await install_integration(
                    organization_id,
                    ref,
                    workspace_id=workspace_id,
                    created_by=created_by,
                    purpose=purpose,
                )
                iid = install["install_id"]
                mapping[f"dependency.integration.{alias}.install_id"] = str(iid)
                configured[f"dependency.integration.{alias}.install_id"] = str(iid)
            elif kind == "action":
                # La acción viene con su integración (ref = integration slug)
                install = await install_integration(
                    organization_id,
                    ref,
                    workspace_id=workspace_id,
                    created_by=created_by,
                    purpose=purpose,
                )
                iid = install["install_id"]
                mapping[f"dependency.integration.{ref}.install_id"] = str(iid)
                configured[f"dependency.action.{alias}.action_id"] = str(asset.get("action_id") or "")
                configured[f"dependency.integration.{ref}.install_id"] = str(iid)
            elif kind == "workflow_template":
                from src.platform.workflows.engine import create_from_template

                wf = await create_from_template(
                    organization_id, ref, workspace_id=workspace_id
                )
                wid = wf["workflow_id"]
                mapping[f"dependency.workflow.{alias}.workflow_id"] = wid
                configured[f"dependency.workflow.{alias}.workflow_id"] = wid
                workflow_ids.append(str(wid))
            elif kind == "agent":
                agent_id = await _create_agent_from_template(
                    organization_id, workspace_id, asset, created_by
                )
                mapping[f"dependency.agent.{alias}.agent_id"] = str(agent_id)
                configured[f"dependency.agent.{alias}.agent_id"] = str(agent_id)
                agent_ids.append(str(agent_id))
            elif kind == "semantic":
                ready = await _semantic_ready(organization_id, ref)
                configured[f"dependency.semantic.{alias}.ready"] = "true" if ready else "false"
                if not ready:
                    issues.append(
                        {
                            "kind": "semantic",
                            "ref": ref,
                            "message": f"concepto '{ref}' no resuelto; requiere mapeo",
                        }
                    )
            elif kind == "product":
                sub = await install_product(
                    organization_id,
                    UUID(ref),
                    workspace_id=workspace_id,
                    created_by=created_by,
                    install_answers=answers,
                )
                configured[f"dependency.product.{alias}.install_id"] = str(sub["install_id"])
        except Exception as exc:  # noqa: BLE001
            issues.append({"kind": kind, "ref": ref, "message": str(exc)[:200]})
    return mapping, configured, workflow_ids, agent_ids, issues


async def _compute_readiness_and_health(
    organization_id: UUID,
    product_status: str,
    configured: dict[str, str],
) -> tuple[str, dict]:
    """Readiness + salud reales de una instalación (nunca fabricados)."""
    assets = _integration_asset_ids(configured)
    workflow_ids = [
        v
        for k, v in (configured or {}).items()
        if k.startswith("dependency.workflow.") and k.endswith(".workflow_id")
    ]
    agent_ids = [
        v
        for k, v in (configured or {}).items()
        if k.startswith("dependency.agent.") and k.endswith(".agent_id")
    ]
    children: list[dict] = []
    missing_aliases = list(assets.keys())
    last_used_at = None
    if assets:
        asset_uuids = [UUID(v) for v in assets.values()]
        session = await get_async_session()
        try:
            rows = (
                await session.execute(
                    text(
                        "SELECT i.id, i.status, i.credential_ref, i.purpose, "
                        "m.slug, m.name, m.auth_modes, m.data_policy "
                        "FROM installed_integrations i "
                        "JOIN integration_manifests m ON m.id = i.integration_id "
                        "WHERE i.organization_id = :oid "
                        "AND i.id = ANY(:ids)"
                    ),
                    {"oid": organization_id, "ids": asset_uuids},
                )
            ).fetchall()
            ledger = (
                await session.execute(
                    text(
                        "SELECT install_id, MAX(created_at) AS last_used "
                        "FROM integration_usage_ledger "
                        "WHERE organization_id = :oid "
                        "AND install_id = ANY(:ids) "
                        "GROUP BY install_id"
                    ),
                    {"oid": organization_id, "ids": asset_uuids},
                )
            ).fetchall()
        finally:
            await session.close()
        found = {str(r.id): r for r in rows}
        last_used = {str(r.install_id): r.last_used for r in ledger}
        for alias, iid in assets.items():
            row = found.get(iid)
            if row is None:
                continue
            missing_aliases = [a for a in missing_aliases if a != alias]
            modes = [str(x) for x in (row.auth_modes or []) if str(x).upper() != "NONE"]
            lu = last_used.get(iid)
            if lu is not None and (last_used_at is None or lu > last_used_at):
                last_used_at = lu
            children.append(
                {
                    "alias": alias,
                    "install_id": iid,
                    "slug": row.slug,
                    "name": row.name,
                    "status": row.status,
                    "connected": bool(row.credential_ref),
                    "needs_credentials": bool(modes) and not row.credential_ref,
                    "needs_purpose": bool((row.data_policy or {}).get("purpose_required"))
                    and not row.purpose,
                    "last_used_at": lu.isoformat() if lu else None,
                }
            )
    health: dict[str, Any] = {
        "children": children,
        "workflows": len(workflow_ids),
        "agents": len(agent_ids),
        "last_used_at": last_used_at.isoformat() if last_used_at else None,
    }
    if str(product_status) == "PAUSED":
        readiness = "DISABLED"
        health["state"] = "disabled"
    elif missing_aliases:
        readiness = "MISSING_DEPENDENCY"
        health["state"] = "error"
        health["missing"] = missing_aliases
    elif any(c.get("needs_credentials") for c in children):
        readiness = "NEEDS_CREDENTIALS"
        health["state"] = "attention"
    elif any(c.get("needs_purpose") for c in children):
        readiness = "NEEDS_CONFIGURATION"
        health["state"] = "attention"
    elif any(str(c.get("status")) not in ("installed", "connected", "active") for c in children):
        readiness = "ERROR"
        health["state"] = "error"
    else:
        readiness = "READY"
        health["state"] = "ok"
    return readiness, health


# ---------------------------------------------------------------------------
# Instalación de producto para un tenant
# ---------------------------------------------------------------------------
def _rewrite_placeholders_in_value(value: Any, mapping: dict[str, str]) -> Any:
    if isinstance(value, str):
        out = value
        for ph, replacement in mapping.items():
            out = out.replace("{{" + ph + "}}", replacement).replace("{" + ph + "}", replacement)
        return out
    if isinstance(value, dict):
        return {k: _rewrite_placeholders_in_value(v, mapping) for k, v in value.items()}
    if isinstance(value, list):
        return [_rewrite_placeholders_in_value(v, mapping) for v in value]
    return value


async def _rewrite_workflow_placeholders(workflow_id: UUID, mapping: dict[str, str]) -> None:
    """Reescribe refs tipados (dependency.* / answers.*) en el grafo del workflow."""
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text("SELECT organization_id, graph FROM workflows WHERE id = :wid"),
                {"wid": workflow_id},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None or not row.graph:
        return
    graph = json.loads(json.dumps(row.graph))
    changed = False
    for node in graph.get("nodes") or []:
        new_cfg = _rewrite_placeholders_in_value(node.get("config") or {}, mapping)
        if json.dumps(new_cfg, default=str) != json.dumps(node.get("config") or {}, default=str):
            node["config"] = new_cfg
            changed = True
    if changed:
        from src.platform.workflows.engine import update_workflow

        await update_workflow(UUID(str(row.organization_id)), workflow_id, graph=graph, workflow_version=2)


async def install_product(
    organization_id: UUID,
    product_id: UUID,
    *,
    workspace_id: UUID | None = None,
    created_by: UUID | None = None,
    install_answers: dict[str, Any] | None = None,
    purpose: str | None = None,
) -> dict:
    """Instala un producto resolviendo sus assets con REUSO de instalaciones.

    Nunca instala parcialmente sin explicar: si un asset falla, revierte y
    reporta el configure requerido (ej. credenciales).
    """
    product = await get_product(product_id=product_id)
    if product is None or product["status"] not in ("PUBLISHED", "READY"):
        raise ProductError("producto no publicado o inexistente")

    session = await get_async_session()
    try:
        existing = (
            await session.execute(
                text(
                    "SELECT id, status, readiness, installed_assets "
                    "FROM marketplace_product_installations "
                    "WHERE organization_id = :oid AND workspace_id IS NOT DISTINCT FROM :ws "
                    "AND product_id = :pid"
                ),
                {"oid": organization_id, "ws": workspace_id, "pid": product_id},
            )
        ).fetchone()
    finally:
        await session.close()
    if existing is not None:
        return {
            "install_id": str(existing.id),
            "reused": True,
            "status": existing.status,
            "readiness": existing.readiness or "installed",
            "installed_assets": existing.installed_assets or {},
        }

    answers = dict(install_answers or {})
    mapping, configured, workflow_ids, agent_ids, issues = await _apply_product_assets(
        organization_id,
        product,
        workspace_id=workspace_id,
        created_by=created_by,
        answers=answers,
        purpose=purpose,
    )

    # Reescritura de placeholders tipados en los workflows creados.
    for wid in workflow_ids:
        try:
            await _rewrite_workflow_placeholders(UUID(wid), mapping)
        except Exception as exc:  # noqa: BLE001
            logger.warning("placeholder rewrite failed", workflow_id=wid, error=str(exc)[:150])

    if issues:
        # Nunca instalar parcialmente sin explicar → revertimos los assets creados.
        for wid in workflow_ids:
            try:
                from src.platform.workflows.engine import delete_workflow

                await delete_workflow(organization_id, UUID(wid))
            except Exception:  # noqa: BLE001
                pass
        raise ProductError(
            "instalación incompleta — pendientes: " + "; ".join(i["message"] for i in issues)
        )

    readiness, health = await _compute_readiness_and_health(
        organization_id, str(product.get("status") or ""), configured
    )
    install_id = uuid4()
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO marketplace_product_installations "
                "(id, organization_id, workspace_id, product_id, product_version, status, "
                "readiness, health, last_used_at, install_answers, installed_assets, created_by) "
                "VALUES (:id, :oid, :ws, :pid, :ver, 'active', :readiness, "
                "CAST(:health AS jsonb), :last_used, CAST(:answers AS jsonb), "
                "CAST(:assets AS jsonb), :by)"
            ),
            {
                "id": install_id,
                "oid": organization_id,
                "ws": workspace_id,
                "pid": product_id,
                "ver": int(product["version"]),
                "readiness": readiness,
                "health": json.dumps(health),
                "last_used": health.get("last_used_at"),
                "answers": json.dumps(answers),
                "assets": json.dumps(configured),
                "by": created_by,
            },
        )
        await session.commit()
    finally:
        await session.close()
    return {
        "install_id": str(install_id),
        "reused": False,
        "status": "active",
        "readiness": readiness,
        "health": health,
        "installed_assets": configured,
        "workflows": workflow_ids,
        "agents": agent_ids,
        "mapping": mapping,
    }


async def _semantic_ready(organization_id: UUID, concept: str) -> bool:
    """Readiness semántica: concepto aprobado en business_definitions."""
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT 1 FROM business_definitions "
                    "WHERE organization_id = :oid AND lower(concept) = lower(:concept) "
                    "AND status = 'approved' LIMIT 1"
                ),
                {"oid": organization_id, "concept": concept},
            )
        ).fetchone()
        return row is not None
    except Exception:  # noqa: BLE001 — tabla opcional si no existe
        return False
    finally:
        await session.close()


async def _create_agent_from_template(
    organization_id: UUID,
    workspace_id: UUID | None,
    asset: dict,
    created_by: UUID | None,
) -> UUID:
    """Crea un agente desde los datos del template del producto.

    Los templates legacy (marketplace_agents) traen prompt_template y
    config_template: se propagan para que el agente instalado sea útil
    (no un agente vacío).
    """
    name = str(asset.get("name") or asset.get("ref") or "Agente de producto")[:150]
    config = asset.get("config_template")
    config = config if isinstance(config, dict) else {}
    model = str(asset.get("model") or config.get("model") or "")[:100] or None
    system_prompt = asset.get("system_prompt") or asset.get("prompt_template")
    tools = asset.get("tools") if isinstance(asset.get("tools"), list) else []
    agent_id = uuid4()
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO agents (id, organization_id, workspace_id, name, status, "
                "is_active, external_id, description, system_prompt, model, tools, "
                "config_json, created_by) "
                "VALUES (:id, :oid, :ws, :name, 'draft', false, :ext, :desc, :prompt, "
                ":model, CAST(:tools AS jsonb), CAST(:config AS jsonb), :by)"
            ),
            {
                "id": agent_id,
                "oid": organization_id,
                "ws": workspace_id,
                "name": name,
                "ext": f"product-agent-{agent_id.hex[:12]}",
                "desc": str(asset.get("description") or ""),
                "prompt": str(system_prompt) if system_prompt else None,
                "model": model,
                "tools": json.dumps(tools),
                "config": json.dumps(config),
                "by": created_by,
            },
        )
        await session.commit()
    finally:
        await session.close()
    return agent_id


_INSTALL_SELECT = (
    "SELECT i.id, i.product_id, i.product_version, i.status, i.readiness, i.health, "
    "i.last_used_at, i.installed_assets, i.install_answers, i.created_at, i.updated_at, "
    "p.slug, p.name, p.product_type, p.short_description, p.category, p.applies_to, "
    "p.logo, p.version AS product_latest, p.status AS product_status "
    "FROM marketplace_product_installations i "
    "JOIN marketplace_products p ON p.id = i.product_id "
)


def _install_payload(r) -> dict:
    return {
        "id": str(r.id),
        "product_id": str(r.product_id),
        "product_version": int(r.product_version or 1),
        "status": r.status,
        "readiness": r.readiness or "installed",
        "health": r.health or {},
        "last_used_at": r.last_used_at.isoformat() if r.last_used_at else None,
        "update_available": int(r.product_latest or 1) > int(r.product_version or 1),
        "latest_version": int(r.product_latest or 1),
        "installed_assets": r.installed_assets or {},
        "install_answers": r.install_answers or {},
        "created_at": r.created_at.isoformat(),
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        "product": {
            "slug": r.slug,
            "name": r.name,
            "product_type": r.product_type,
            "short_description": r.short_description,
            "category": r.category,
            "applies_to": r.applies_to or [],
            "logo": r.logo,
            "status": r.product_status,
        },
    }


async def list_tenant_installs(
    organization_id: UUID,
    workspace_id: UUID | None = None,
    *,
    only_updates: bool = False,
) -> dict:
    session = await get_async_session()
    try:
        sql = _INSTALL_SELECT + "WHERE i.organization_id = :oid"
        params: dict[str, Any] = {"oid": organization_id}
        if workspace_id is not None:
            sql += " AND (i.workspace_id = :ws OR i.workspace_id IS NULL)"
            params["ws"] = workspace_id
        if only_updates:
            sql += " AND p.version > i.product_version"
        rows = (
            await session.execute(text(sql + " ORDER BY i.created_at DESC"), params)
        ).fetchall()
    finally:
        await session.close()
    return {"installs": [_install_payload(r) for r in rows]}


async def refresh_installation_health(
    organization_id: UUID, install_id: UUID
) -> dict | None:
    """Recalcula readiness/health reales y los persiste (sin inventar datos)."""
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(_INSTALL_SELECT + "WHERE i.id = :iid AND i.organization_id = :oid"),
                {"iid": install_id, "oid": organization_id},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        return None
    readiness, health = await _compute_readiness_and_health(
        organization_id, str(row.product_status), row.installed_assets or {}
    )
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE marketplace_product_installations SET readiness = :readiness, "
                "health = CAST(:health AS jsonb), last_used_at = :last_used, "
                "updated_at = NOW() WHERE id = :iid AND organization_id = :oid"
            ),
            {
                "readiness": readiness,
                "health": json.dumps(health),
                "last_used": health.get("last_used_at"),
                "iid": install_id,
                "oid": organization_id,
            },
        )
        await session.commit()
    finally:
        await session.close()
    payload = _install_payload(row)
    payload["readiness"] = readiness
    payload["health"] = health
    payload["last_used_at"] = health.get("last_used_at")
    return payload


async def installation_impact(organization_id: UUID, install_id: UUID) -> dict | None:
    """Impacto real de desinstalar: workflows, agentes y otros productos."""
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT i.id, i.installed_assets, p.slug, p.name "
                    "FROM marketplace_product_installations i "
                    "JOIN marketplace_products p ON p.id = i.product_id "
                    "WHERE i.id = :iid AND i.organization_id = :oid"
                ),
                {"iid": install_id, "oid": organization_id},
            )
        ).fetchone()
        if row is None:
            return None
        assets = _integration_asset_ids(row.installed_assets or {})
        asset_ids = [v for v in assets.values() if v]
        workflows: list[dict] = []
        agents: list[dict] = []
        products: list[dict] = []
        if asset_ids:
            like_clauses = " OR ".join(
                f"graph::text LIKE :p{i}" for i in range(len(asset_ids))
            )
            params: dict[str, Any] = {"oid": organization_id}
            params.update({f"p{i}": f"%{aid}%" for i, aid in enumerate(asset_ids)})
            wf_rows = (
                await session.execute(
                    text(
                        "SELECT id, name FROM workflows WHERE organization_id = :oid "  # noqa: S608
                        f"AND ({like_clauses}) ORDER BY updated_at DESC LIMIT 50"
                    ),
                    params,
                )
            ).fetchall()
            workflows = [{"id": str(w.id), "name": w.name} for w in wf_rows]
            tools_like = " OR ".join(
                f"tools::text LIKE :p{i}" for i in range(len(asset_ids))
            )
            try:
                agent_rows = (
                    await session.execute(
                        text(
                            "SELECT id, name FROM agents WHERE organization_id = :oid "  # noqa: S608
                            f"AND ({tools_like}) ORDER BY created_at DESC LIMIT 50"
                        ),
                        params,
                    )
                ).fetchall()
                agents = [{"id": str(a.id), "name": a.name} for a in agent_rows]
            except Exception:  # noqa: BLE001 — tabla agents opcional
                agents = []
            other_like = " OR ".join(
                f"installed_assets::text LIKE :p{i}" for i in range(len(asset_ids))
            )
            prod_rows = (
                await session.execute(
                    text(
                        "SELECT i2.id, p2.slug, p2.name FROM marketplace_product_installations i2 "  # noqa: S608
                        "JOIN marketplace_products p2 ON p2.id = i2.product_id "
                        "WHERE i2.organization_id = :oid AND i2.id <> :iid "
                        f"AND ({other_like}) LIMIT 50"
                    ),
                    {**params, "iid": install_id},
                )
            ).fetchall()
            products = [
                {"install_id": str(p2.id), "slug": p2.slug, "name": p2.name}
                for p2 in prod_rows
            ]
    finally:
        await session.close()
    return {
        "install_id": str(install_id),
        "product": {"slug": row.slug, "name": row.name},
        "assets": [{"alias": a, "install_id": i} for a, i in assets.items()],
        "workflows": workflows,
        "agents": agents,
        "products": products,
        "message": (
            "Desinstalar NO elimina workflows ni agentes del tenant; "
            "solo libera la instalación del producto."
        ),
    }


async def uninstall_product(
    organization_id: UUID,
    install_id: UUID,
    *,
    cascade: bool = False,
) -> dict | None:
    """Desinstala un producto mostrando impactos. cascade libera integraciones
    hijas SOLO si nadie más las referencia; nunca borra workflows/agentes."""
    impact = await installation_impact(organization_id, install_id)
    if impact is None:
        return None
    session = await get_async_session()
    disconnected: list[dict] = []
    retained: list[dict] = []
    try:
        await session.execute(
            text(
                "DELETE FROM marketplace_product_installations "
                "WHERE id = :iid AND organization_id = :oid"
            ),
            {"iid": install_id, "oid": organization_id},
        )
        if cascade and impact["assets"]:
            asset_ids = [a["install_id"] for a in impact["assets"]]
            params: dict[str, Any] = {"oid": organization_id}
            refs = " OR ".join(f"installed_assets::text LIKE :p{i}" for i in range(len(asset_ids)))
            params.update({f"p{i}": f"%{aid}%" for i, aid in enumerate(asset_ids)})
            still_used = (
                await session.execute(
                    text(
                        "SELECT 1 FROM marketplace_product_installations "  # noqa: S608
                        f"WHERE organization_id = :oid AND ({refs}) LIMIT 1"
                    ),
                    params,
                )
            ).fetchone()
            wf_refs = " OR ".join(f"graph::text LIKE :p{i}" for i in range(len(asset_ids)))
            wf_used = (
                await session.execute(
                    text(
                        "SELECT 1 FROM workflows WHERE organization_id = :oid "  # noqa: S608
                        f"AND ({wf_refs}) LIMIT 1"
                    ),
                    params,
                )
            ).fetchone()
            for asset in impact["assets"]:
                if still_used or wf_used:
                    retained.append({**asset, "reason": "en_uso"})
                    continue
                result = await session.execute(
                    text(
                        "DELETE FROM installed_integrations "
                        "WHERE id = :iid AND organization_id = :oid"
                    ),
                    {"iid": asset["install_id"], "oid": organization_id},
                )
                if result.rowcount > 0:
                    disconnected.append(asset)
                else:
                    retained.append({**asset, "reason": "no_encontrada"})
        await session.commit()
    finally:
        await session.close()
    return {
        "deleted": True,
        "impact": impact,
        "disconnected": disconnected,
        "retained": retained,
    }


async def update_product_installation(
    organization_id: UUID, install_id: UUID
) -> dict | None:
    """Aplica la versión vigente del producto reutilizando assets existentes."""
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT i.id, i.product_id, i.product_version, i.installed_assets, "
                    "i.install_answers, p.version AS product_latest "
                    "FROM marketplace_product_installations i "
                    "JOIN marketplace_products p ON p.id = i.product_id "
                    "WHERE i.id = :iid AND i.organization_id = :oid"
                ),
                {"iid": install_id, "oid": organization_id},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        return None
    if int(row.product_latest or 1) <= int(row.product_version or 1):
        return {"updated": False, "reason": "sin_cambios", "install_id": str(install_id)}
    product = await get_product(product_id=UUID(str(row.product_id)))
    if product is None or product["status"] not in ("PUBLISHED", "READY"):
        return {"updated": False, "reason": "producto_no_disponible", "install_id": str(install_id)}
    answers = row.install_answers or {}
    mapping, configured, workflow_ids, agent_ids, issues = await _apply_product_assets(
        organization_id,
        product,
        workspace_id=None,
        created_by=None,
        answers=answers,
    )
    for wid in workflow_ids:
        try:
            await _rewrite_workflow_placeholders(UUID(wid), mapping)
        except Exception as exc:  # noqa: BLE001
            logger.warning("update placeholder rewrite failed", workflow_id=wid, error=str(exc)[:150])
    if issues:
        return {
            "updated": False,
            "reason": "assets_con_pendientes",
            "install_id": str(install_id),
            "issues": issues,
        }
    merged = dict(row.installed_assets or {})
    merged.update(configured)
    readiness, health = await _compute_readiness_and_health(
        organization_id, str(product.get("status") or ""), merged
    )
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE marketplace_product_installations SET product_version = :ver, "
                "installed_assets = CAST(:assets AS jsonb), readiness = :readiness, "
                "health = CAST(:health AS jsonb), last_used_at = :last_used, "
                "updated_at = NOW() WHERE id = :iid AND organization_id = :oid"
            ),
            {
                "ver": int(product["version"]),
                "assets": json.dumps(merged),
                "readiness": readiness,
                "health": json.dumps(health),
                "last_used": health.get("last_used_at"),
                "iid": install_id,
                "oid": organization_id,
            },
        )
        await session.commit()
    finally:
        await session.close()
    return {
        "updated": True,
        "install_id": str(install_id),
        "product_version": int(product["version"]),
        "readiness": readiness,
        "health": health,
    }


# ---------------------------------------------------------------------------
# Proyección del catálogo: assets técnicos -> MarketplaceProduct (idempotente)
#
# marketplace_products es la ÚNICA autoridad de catálogo. integration_manifests,
# workflow_templates y agentes son assets técnicos que se proyectan aquí.
# Nunca pisa ediciones manuales: solo rellena campos vacíos y crea faltantes.
# ---------------------------------------------------------------------------
_AGENT_CATEGORY_FALLBACK = "productivity"


async def sync_catalog_from_assets(*, created_by: UUID | None = None) -> dict:
    """Sincroniza assets técnicos al catálogo único (idempotente)."""
    from src.platform.marketplace.products import default_applies_to

    provider_id = await ensure_zend_provider()
    created, updated, skipped = 0, 0, []
    session = await get_async_session()
    try:
        manifests = (
            await session.execute(
                text(
                    "SELECT m.slug, m.name, m.description, m.category, m.pricing, "
                    "m.data_policy, m.status, m.certification, m.countries, m.events, "
                    "m.applies_to, m.contract_version "
                    "FROM integration_manifests m ORDER BY m.slug"
                )
            )
        ).fetchall()
        caps = (
            await session.execute(
                text(
                    "SELECT m.slug, jsonb_agg(DISTINCT c.slug) AS caps "
                    "FROM integration_capabilities c "
                    "JOIN integration_manifests m ON m.id = c.integration_id "
                    "GROUP BY m.slug"
                )
            )
        ).fetchall()
        wfs = (
            await session.execute(
                text(
                    "SELECT slug, name, description, category FROM workflow_templates "
                    "ORDER BY slug"
                )
            )
        ).fetchall()
        agents = (
            await session.execute(
                text(
                    "SELECT slug, name, description, category, tags, prompt_template, "
                    "config_template FROM marketplace_agents "
                    "WHERE status = 'published' ORDER BY slug"
                )
            )
        ).fetchall()
        listings = (
            await session.execute(
                text(
                    "SELECT slug, name, description, category, tags, pricing_type, "
                    "price_cents, currency FROM public_listings "
                    "WHERE status = 'published' ORDER BY slug"
                )
            )
        ).fetchall()
    finally:
        await session.close()

    caps_by_slug = {str(r.slug): [str(c) for c in (r.caps or [])] for r in caps}

    async def _upsert(slug: str, payload: dict[str, Any]) -> str:
        """Crea el producto o rellena solo campos vacíos (no pisa manual)."""
        nonlocal created, updated
        existing = await get_product(slug=slug)
        if existing is None:
            stored = {**payload, "publisher": str(provider_id)}
            try:
                await save_product(stored, created_by=created_by)
            except ProductError as exc:
                logger.warning("catalog sync item failed", slug=slug, error=str(exc)[:200])
                skipped.append(f"{slug}: {str(exc)[:120]}")
                return "error"
            created += 1
            return "created"
        session2 = await get_async_session()
        try:
            result = await session2.execute(
                text(
                    "UPDATE marketplace_products SET "
                    "applies_to = CASE WHEN applies_to = '[]'::jsonb "
                    "THEN CAST(:applies AS jsonb) ELSE applies_to END, "
                    "capabilities = CASE WHEN capabilities = '[]'::jsonb "
                    "THEN CAST(:caps AS jsonb) ELSE capabilities END, "
                    "events = CASE WHEN events = '[]'::jsonb "
                    "THEN CAST(:evts AS jsonb) ELSE events END, "
                    "status = CASE WHEN status = 'DRAFT' AND :target = 'PUBLISHED' "
                    "THEN 'PUBLISHED' ELSE status END, "
                    "updated_at = NOW() WHERE slug = :slug"
                ),
                {
                    "applies": json.dumps(payload.get("applies_to") or []),
                    "caps": json.dumps(payload.get("capabilities") or []),
                    "evts": json.dumps(payload.get("events") or []),
                    "target": payload.get("status") or "DRAFT",
                    "slug": slug,
                },
            )
            await session2.commit()
        finally:
            await session2.close()
        if result.rowcount and (
            (payload.get("capabilities") and not (existing.get("capabilities") or []))
            or (payload.get("events") and not (existing.get("events") or []))
            or (payload.get("applies_to") and not (existing.get("applies_to") or []))
            or (existing.get("status") == "DRAFT" and payload.get("status") == "PUBLISHED")
        ):
            updated += 1
            return "updated"
        skipped.append(slug)
        return "skipped"

    for m in manifests:
        slug = f"product-{m.slug}"[:100]
        pricing = normalize_pricing(m.pricing if isinstance(m.pricing, dict) else {})
        await _upsert(
            slug,
            {
                "slug": slug,
                "name": m.name,
                "short_description": m.description or m.name,
                "product_type": "INTEGRATION",
                "category": m.category,
                "countries": m.countries or [],
                "pricing": pricing,
                "privacy": {
                    "purpose_required": bool((m.data_policy or {}).get("purpose_required"))
                },
                "certification": m.certification,
                "included_assets": [
                    {"kind": "integration", "ref": m.slug, "alias": m.slug}
                ],
                "dependencies": [],
                "capabilities": caps_by_slug.get(str(m.slug), []),
                "events": [str(e) for e in (m.events or [])],
                "applies_to": (
                    list(m.applies_to or [])
                    if getattr(m, "applies_to", None)
                    else default_applies_to("INTEGRATION", m.category)
                ),
                "status": "PUBLISHED" if m.status == "PUBLISHED" else (
                    "DEPRECATED" if m.status == "DEPRECATED" else "DRAFT"
                ),
                "legacy_source": "integration_manifest",
                "legacy_ref": m.slug,
            },
        )

    for w in wfs:
        slug = f"product-{w.slug}"[:100]
        ptype = "BUSINESS_PACK" if w.category in ("analytics", "operations") else "WORKFLOW_TEMPLATE"
        await _upsert(
            slug,
            {
                "slug": slug,
                "name": w.name,
                "short_description": w.description or w.name,
                "product_type": ptype,
                "category": w.category,
                "pricing": {"model": "FREE"},
                "included_assets": [
                    {"kind": "workflow_template", "ref": w.slug, "alias": w.slug}
                ],
                "dependencies": [],
                "applies_to": default_applies_to(ptype, w.category),
                "status": "PUBLISHED",
                "legacy_source": "workflow_template",
                "legacy_ref": w.slug,
            },
        )

    for a in agents:
        slug = f"product-agent-{a.slug}"[:100]
        category = a.category if a.category in (
            "sales", "support", "finance", "payments", "inventory", "ecommerce",
            "productivity", "data", "intelligence", "communication", "marketing",
            "security", "operations", "development", "erp_crm", "other",
        ) else _AGENT_CATEGORY_FALLBACK
        await _upsert(
            slug,
            {
                "slug": slug,
                "name": a.name,
                "short_description": (a.description or a.name)[:400],
                "product_type": "AGENT_TEMPLATE",
                "category": category,
                "pricing": {"model": "FREE"},
                "tags": a.tags or [],
                "included_assets": [
                    {
                        "kind": "agent",
                        "ref": a.slug,
                        "alias": a.slug,
                        "name": a.name,
                        "description": a.description or "",
                        "system_prompt": a.prompt_template,
                        "config_template": a.config_template or {},
                    }
                ],
                "dependencies": [],
                "applies_to": ["AGENTS"],
                "status": "PUBLISHED",
                "legacy_source": "marketplace_agent",
                "legacy_ref": a.slug,
            },
        )

    for listing in listings:
        slug = f"product-listing-{listing.slug}"[:100]
        if str(listing.pricing_type) == "free" or int(listing.price_cents or 0) <= 0:
            pricing: dict[str, Any] = {"model": "FREE"}
        elif str(listing.pricing_type) == "subscription":
            pricing = {
                "model": "SUBSCRIPTION",
                "amount": round(int(listing.price_cents or 0) / 100, 2),
                "currency": str(listing.currency or "USD").upper()[:3],
                "interval": "MONTH",
            }
        else:
            pricing = {
                "model": "ONE_TIME",
                "amount": round(int(listing.price_cents or 0) / 100, 2),
                "currency": str(listing.currency or "USD").upper()[:3],
            }
        await _upsert(
            slug,
            {
                "slug": slug,
                "name": listing.name,
                "short_description": (listing.description or listing.name)[:400],
                "product_type": "AGENT_TEMPLATE",
                "category": (
                    listing.category if listing.category in (
                        "sales", "support", "finance", "payments", "inventory",
                        "ecommerce", "productivity", "data", "intelligence",
                        "communication", "marketing", "security", "operations",
                        "development", "erp_crm",
                    ) else _AGENT_CATEGORY_FALLBACK
                ),
                "pricing": pricing,
                "tags": listing.tags or [],
                "dependencies": [],
                "applies_to": ["AGENTS"],
                # legacy de ecosistema: no se expone hasta revisión en CC.
                "status": "DRAFT",
                "legacy_source": "ecosystem_listing",
                "legacy_ref": listing.slug,
            },
        )

    return {"created": created, "updated": updated, "skipped": skipped}


async def migrate_legacy_to_products(*, created_by: UUID | None = None) -> dict:
    """Compat: mismo sync idempotente (se mantiene por API/tests existentes)."""
    return await sync_catalog_from_assets(created_by=created_by)
