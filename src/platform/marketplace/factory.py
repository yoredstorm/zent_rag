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
) -> dict:
    """Instala un producto resolviendo sus assets con REUSO de instalaciones.

    Nunca instala parcialmente sin explicar: si un asset falla, revierte y
    reporta el configure requerido (ej. credenciales).
    """
    from src.platform.marketplace.runtime import install_integration

    product = await get_product(product_id=product_id)
    if product is None or product["status"] not in ("PUBLISHED", "READY"):
        raise ProductError("producto no publicado o inexistente")

    session = await get_async_session()
    try:
        existing = (
            await session.execute(
                text(
                    "SELECT id, status, installed_assets FROM marketplace_product_installations "
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
            "installed_assets": existing.installed_assets or {},
        }

    answers = dict(install_answers or {})
    mapping: dict[str, str] = {f"answers.{k}": str(v) for k, v in answers.items()}
    configured: dict[str, str] = {}
    issues: list[dict[str, str]] = []
    workflow_ids: list[str] = []
    agent_ids: list[str] = []

    for asset in product.get("included_assets") or []:
        kind = str(asset.get("kind") or "")
        ref = str(asset.get("ref") or "")
        alias = str(asset.get("alias") or ref)
        try:
            if kind in ("integration", "capability"):
                install = await install_integration(
                    organization_id, ref, workspace_id=workspace_id, created_by=created_by
                )
                iid = install["install_id"]
                mapping[f"dependency.integration.{alias}.install_id"] = str(iid)
                configured[f"dependency.integration.{alias}.install_id"] = str(iid)
            elif kind == "action":
                # La acción viene con su integración (ref = integration slug)
                install = await install_integration(
                    organization_id, ref, workspace_id=workspace_id, created_by=created_by
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

    install_id = uuid4()
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO marketplace_product_installations "
                "(id, organization_id, workspace_id, product_id, product_version, status, "
                "install_answers, installed_assets, created_by) "
                "VALUES (:id, :oid, :ws, :pid, :ver, 'active', CAST(:answers AS jsonb), "
                "CAST(:assets AS jsonb), :by)"
            ),
            {
                "id": install_id,
                "oid": organization_id,
                "ws": workspace_id,
                "pid": product_id,
                "ver": int(product["version"]),
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
    """Crea un agente desde los datos del template del producto."""
    name = str(asset.get("name") or asset.get("ref") or "Agente de producto")[:150]
    agent_id = uuid4()
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO agents (id, organization_id, workspace_id, name, status, "
                "is_active, external_id, description, created_by) "
                "VALUES (:id, :oid, :ws, :name, 'draft', false, :ext, :desc, :by)"
            ),
            {
                "id": agent_id,
                "oid": organization_id,
                "ws": workspace_id,
                "name": name,
                "ext": f"product-agent-{agent_id.hex[:12]}",
                "desc": str(asset.get("description") or ""),
                "by": created_by,
            },
        )
        await session.commit()
    finally:
        await session.close()
    return agent_id


async def list_tenant_installs(
    organization_id: UUID, workspace_id: UUID | None = None
) -> dict:
    session = await get_async_session()
    try:
        sql = (
            "SELECT i.id, i.product_id, i.product_version, i.status, i.installed_assets, "
            "i.install_answers, i.created_at, p.slug, p.name, p.product_type, p.short_description "
            "FROM marketplace_product_installations i "
            "JOIN marketplace_products p ON p.id = i.product_id "
            "WHERE i.organization_id = :oid"
        )
        params: dict[str, Any] = {"oid": organization_id}
        if workspace_id is not None:
            sql += " AND (i.workspace_id = :ws OR i.workspace_id IS NULL)"
            params["ws"] = workspace_id
        rows = (await session.execute(text(sql + " ORDER BY i.created_at DESC"), params)).fetchall()
    finally:
        await session.close()
    return {
        "installs": [
            {
                "id": str(r.id),
                "product_id": str(r.product_id),
                "product_version": int(r.product_version),
                "status": r.status,
                "installed_assets": r.installed_assets or {},
                "install_answers": r.install_answers or {},
                "created_at": r.created_at.isoformat(),
                "product": {
                    "slug": r.slug,
                    "name": r.name,
                    "product_type": r.product_type,
                    "short_description": r.short_description,
                },
            }
            for r in rows
        ]
    }


async def uninstall_product(organization_id: UUID, install_id: UUID) -> bool:
    session = await get_async_session()
    try:
        result = await session.execute(
            text(
                "DELETE FROM marketplace_product_installations "
                "WHERE id = :iid AND organization_id = :oid"
            ),
            {"iid": install_id, "oid": organization_id},
        )
        await session.commit()
        return result.rowcount > 0
    finally:
        await session.close()


# ---------------------------------------------------------------------------
# Migración legacy → MarketplaceProduct (no destruye nada, solo crea)
# ---------------------------------------------------------------------------
async def migrate_legacy_to_products(*, created_by: UUID | None = None) -> dict:
    """Crea productos unificados desde integration manifests y workflow templates."""
    from src.platform.marketplace.products import get_product

    await ensure_zend_provider()
    created, skipped = 0, []
    session = await get_async_session()
    try:
        ints = (
            await session.execute(
                text(
                    "SELECT m.slug, m.name, m.description, m.category, m.pricing, "
                    "m.data_policy, m.status, m.id FROM integration_manifests m"
                )
            )
        ).fetchall()
        wfs = (
            await session.execute(
                text(
                    "SELECT slug, name, description, category, trigger_type, trigger_config "
                    "FROM workflow_templates"
                )
            )
        ).fetchall()
    finally:
        await session.close()

    for m in ints:
        slug = f"product-{m.slug}"[:100]
        if await get_product(slug=slug) is None:
            await save_product(
                {
                    "slug": slug,
                    "name": m.name,
                    "short_description": m.description or m.name,
                    "product_type": "INTEGRATION",
                    "category": m.category,
                    "pricing": m.pricing
                    if isinstance(m.pricing, dict)
                    else {"model": "CUSTOM"},
                    "privacy": {"purpose_required": bool((m.data_policy or {}).get("purpose_required"))},
                    "included_assets": [{"kind": "integration", "ref": m.slug, "alias": m.slug}],
                    "dependencies": [],
                    "status": "PUBLISHED" if m.status == "PUBLISHED" else "DRAFT",
                    "legacy_source": "integration_manifest",
                    "legacy_ref": m.slug,
                },
                created_by=created_by,
            )
            created += 1
        else:
            skipped.append(f"integration:{m.slug}")

    for w in wfs:
        slug = f"product-{w.slug}"[:100]
        if await get_product(slug=slug) is None:
            ptype = "BUSINESS_PACK" if w.category in ("analytics", "operations") else "WORKFLOW_TEMPLATE"
            await save_product(
                {
                    "slug": slug,
                    "name": w.name,
                    "short_description": w.description or w.name,
                    "product_type": ptype,
                    "category": w.category,
                    "pricing": {"model": "FREE"},
                    "included_assets": [{"kind": "workflow_template", "ref": w.slug, "alias": w.slug}],
                    "dependencies": [],
                    "status": "PUBLISHED",
                    "legacy_source": "workflow_template",
                    "legacy_ref": w.slug,
                },
                created_by=created_by,
            )
            created += 1
        else:
            skipped.append(f"workflow:{w.slug}")
    return {"created": created, "skipped": skipped}
