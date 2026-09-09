# =============================================================================
# Phase 33A — Marketplace Products (modelo unificado + factory service)
#
# Un solo MarketplaceProduct agrupa: integrations, workflows, agentes,
# packs de inteligencia y composiciones — con versionado, dependencias
# tipadas, publishing gate, rollout, collections y analytics.
# =============================================================================
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

PRODUCT_TYPES = (
    "INTEGRATION", "WORKFLOW_TEMPLATE", "AGENT_TEMPLATE", "INTELLIGENCE_PACK",
    "BUSINESS_PACK", "SEMANTIC_PACK", "COMPOSITE_PACK",
)
PRODUCT_STATUSES = (
    "DRAFT", "INTERNAL_TEST", "SECURITY_REVIEW", "PRODUCT_REVIEW", "READY",
    "PUBLISHED", "PAUSED", "DEPRECATED", "END_OF_LIFE",
)
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "DRAFT": {"INTERNAL_TEST", "SECURITY_REVIEW", "PRODUCT_REVIEW", "READY", "DEPRECATED"},
    "INTERNAL_TEST": {"SECURITY_REVIEW", "READY", "PAUSED", "DRAFT"},
    "SECURITY_REVIEW": {"PRODUCT_REVIEW", "READY", "PAUSED", "DRAFT", "INTERNAL_TEST"},
    "PRODUCT_REVIEW": {"READY", "PAUSED", "SECURITY_REVIEW", "DRAFT"},
    "READY": {"PUBLISHED", "PAUSED", "DRAFT"},
    "PUBLISHED": {"PAUSED", "DEPRECATED", "READY"},
    "PAUSED": {"READY", "DRAFT", "DEPRECATED"},
    "DEPRECATED": {"END_OF_LIFE", "PAUSED"},
    "END_OF_LIFE": {"DRAFT"},
}


class ProductError(ValueError):
    pass


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


async def create_provider(
    *,
    slug: str,
    name: str,
    legal_entity: str | None = None,
    contact: dict | None = None,
    allowed_countries: list[str] | None = None,
    revenue_share: int = 0,
    support_sla: str | None = None,
) -> dict:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO marketplace_providers "
                    "(slug, name, legal_entity, contact, allowed_countries, revenue_share, support_sla) "
                    "VALUES (:slug, :name, :le, CAST(:contact AS jsonb), "
                    "CAST(:countries AS jsonb), :share, :sla) "
                    "ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name RETURNING id"
                ),
                {
                    "slug": slug,
                    "name": name,
                    "le": legal_entity,
                    "contact": json.dumps(contact or {}),
                    "countries": json.dumps(allowed_countries or []),
                    "share": int(revenue_share),
                    "sla": support_sla,
                },
            )
        ).scalar()
        await session.commit()
    finally:
        await session.close()
    return {"provider_id": str(row), "slug": slug}


async def ensure_zend_provider() -> UUID:
    """El provider por defecto (Zent) — idempotente."""
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text("SELECT id FROM marketplace_providers WHERE slug = 'zent'")
            )
        ).fetchone()
        if row is not None:
            return row.id
        saved = await create_provider(slug="zent", name="Zent", legal_entity="Zent", revenue_share=0)
        return UUID(saved["provider_id"])
    finally:
        await session.close()


def validate_product(payload: dict) -> list[str]:
    """Validación del publishing gate (estructural + negocio)."""
    errors: list[str] = []
    slug = str(payload.get("slug") or "")
    if not slug or len(slug) > 100:
        errors.append("slug requerido (<=100)")
    if not str(payload.get("name") or "").strip():
        errors.append("name requerido")
    ptype = str(payload.get("product_type") or "")
    if ptype not in PRODUCT_TYPES:
        errors.append(f"product_type inválido: {ptype}")
    status = str(payload.get("status") or "DRAFT")
    if status not in PRODUCT_STATUSES:
        errors.append(f"status inválido: {status}")
    if status == "PUBLISHED":
        if not (payload.get("included_assets") or []) and ptype not in (
            "INTEGRATION", "WORKFLOW_TEMPLATE", "AGENT_TEMPLATE"
        ):
            errors.append("un producto publicado necesita included_assets")
        pricing = payload.get("pricing") or {}
        if not pricing.get("model"):
            errors.append("publishing: pricing.model requerido")
        if not payload.get("short_description"):
            errors.append("publishing: short_description requerido")
    deps = payload.get("dependencies") or []
    if deps and not isinstance(deps, list):
        errors.append("dependencies debe ser lista")
    return errors


async def save_product(
    payload: dict,
    *,
    created_by: UUID | None = None,
) -> dict:
    """Crea o actualiza un producto (v1) y guarda el snapshot de versión."""
    errors = validate_product(payload)
    if errors:
        raise ProductError("; ".join(errors[:8]))
    slug = payload["slug"]
    session = await get_async_session()
    try:
        existing = (
            await session.execute(
                text("SELECT id, status, version FROM marketplace_products WHERE slug = :slug"),
                {"slug": slug},
            )
        ).fetchone()
        if existing is None:
            pid = (
                await session.execute(
                    text(
                        "INSERT INTO marketplace_products "
                        "(id, slug, name, short_description, long_description, product_type, "
                        "publisher, version, status, category, subcategories, tags, countries, "
                        "industries, logo, screenshots, documentation, pricing, entitlements, "
                        "dependencies, included_assets, installation_flow, configuration_schema, "
                        "result_surfaces, support, security, privacy, certification, release_notes, "
                        "rollout, featured, collections, legacy_source, legacy_ref, created_by) "
                        "VALUES (gen_random_uuid(), :slug, :name, :short, :long, :ptype, :pub, 1, "
                        ":status, :cat, CAST(:sub AS jsonb), CAST(:tags AS jsonb), "
                        "CAST(:countries AS jsonb), CAST(:ind AS jsonb), :logo, CAST(:shots AS jsonb), "
                        ":docs, CAST(:pricing AS jsonb), CAST(:ent AS jsonb), CAST(:deps AS jsonb), "
                        "CAST(:assets AS jsonb), CAST(:flow AS jsonb), CAST(:cfg AS jsonb), "
                        "CAST(:surfaces AS jsonb), CAST(:support AS jsonb), CAST(:sec AS jsonb), "
                        "CAST(:priv AS jsonb), :cert, CAST(:notes AS jsonb), CAST(:rollout AS jsonb), "
                        "CAST(:featured AS jsonb), CAST(:collections AS jsonb), :lsrc, :lref, :by) "
                        "RETURNING id"
                    ),
                    {
                        "slug": slug,
                        "name": payload["name"][:180],
                        "short": payload.get("short_description"),
                        "long": payload.get("long_description"),
                        "ptype": payload.get("product_type", "INTEGRATION"),
                        "pub": str(uuid.UUID(str(payload.get("publisher")))) if payload.get("publisher") else None,
                        "status": payload.get("status", "DRAFT"),
                        "cat": payload.get("category", "data")[:60],
                        "sub": json.dumps(payload.get("subcategories") or []),
                        "tags": json.dumps(payload.get("tags") or []),
                        "countries": json.dumps(payload.get("countries") or []),
                        "ind": json.dumps(payload.get("industries") or []),
                        "logo": payload.get("logo"),
                        "shots": json.dumps(payload.get("screenshots") or []),
                        "docs": payload.get("documentation"),
                        "pricing": json.dumps(payload.get("pricing") or {}),
                        "ent": json.dumps(payload.get("entitlements") or {}),
                        "deps": json.dumps(payload.get("dependencies") or []),
                        "assets": json.dumps(payload.get("included_assets") or []),
                        "flow": json.dumps(payload.get("installation_flow") or []),
                        "cfg": json.dumps(payload.get("configuration_schema") or {}),
                        "surfaces": json.dumps(payload.get("result_surfaces") or []),
                        "support": json.dumps(payload.get("support") or {}),
                        "sec": json.dumps(payload.get("security") or {}),
                        "priv": json.dumps(payload.get("privacy") or {}),
                        "cert": payload.get("certification"),
                        "notes": json.dumps(payload.get("release_notes") or []),
                        "rollout": json.dumps(payload.get("rollout") or {}),
                        "featured": json.dumps(payload.get("featured") or {}),
                        "collections": json.dumps(payload.get("collections") or []),
                        "lsrc": payload.get("legacy_source"),
                        "lref": payload.get("legacy_ref"),
                        "by": created_by,
                    },
                )
            ).scalar()
            version = 1
        else:
            pid = existing.id
            version = int(existing.version)
            sets = [
                "name = :name",
                "short_description = :short",
                "long_description = :long",
                "product_type = :ptype",
                "category = :cat",
                "subcategories = CAST(:sub AS jsonb)",
                "tags = CAST(:tags AS jsonb)",
                "countries = CAST(:countries AS jsonb)",
                "industries = CAST(:ind AS jsonb)",
                "logo = :logo",
                "screenshots = CAST(:shots AS jsonb)",
                "documentation = :docs",
                "pricing = CAST(:pricing AS jsonb)",
                "entitlements = CAST(:ent AS jsonb)",
                "dependencies = CAST(:deps AS jsonb)",
                "included_assets = CAST(:assets AS jsonb)",
                "installation_flow = CAST(:flow AS jsonb)",
                "configuration_schema = CAST(:cfg AS jsonb)",
                "result_surfaces = CAST(:surfaces AS jsonb)",
                "support = CAST(:support AS jsonb)",
                "security = CAST(:sec AS jsonb)",
                "privacy = CAST(:priv AS jsonb)",
                "certification = :cert",
                "release_notes = CAST(:notes AS jsonb)",
                "rollout = CAST(:rollout AS jsonb)",
                "featured = CAST(:featured AS jsonb)",
                "collections = CAST(:collections AS jsonb)",
                "updated_at = NOW()",
            ]
            params: dict[str, Any] = {
                "pid": pid,
                "name": payload["name"][:180],
                "short": payload.get("short_description"),
                "long": payload.get("long_description"),
                "ptype": payload.get("product_type", "INTEGRATION"),
                "cat": payload.get("category", "data")[:60],
                "sub": json.dumps(payload.get("subcategories") or []),
                "tags": json.dumps(payload.get("tags") or []),
                "countries": json.dumps(payload.get("countries") or []),
                "ind": json.dumps(payload.get("industries") or []),
                "logo": payload.get("logo"),
                "shots": json.dumps(payload.get("screenshots") or []),
                "docs": payload.get("documentation"),
                "pricing": json.dumps(payload.get("pricing") or {}),
                "ent": json.dumps(payload.get("entitlements") or {}),
                "deps": json.dumps(payload.get("dependencies") or []),
                "assets": json.dumps(payload.get("included_assets") or []),
                "flow": json.dumps(payload.get("installation_flow") or []),
                "cfg": json.dumps(payload.get("configuration_schema") or {}),
                "surfaces": json.dumps(payload.get("result_surfaces") or []),
                "support": json.dumps(payload.get("support") or {}),
                "sec": json.dumps(payload.get("security") or {}),
                "priv": json.dumps(payload.get("privacy") or {}),
                "cert": payload.get("certification"),
                "notes": json.dumps(payload.get("release_notes") or []),
                "rollout": json.dumps(payload.get("rollout") or {}),
                "featured": json.dumps(payload.get("featured") or {}),
                "collections": json.dumps(payload.get("collections") or []),
            }
            await session.execute(
                text("UPDATE marketplace_products SET " + ", ".join(sets) + " WHERE id = :pid"),  # noqa: S608
                params,
            )
        # Versión snapshot.
        await session.execute(
            text(
                "INSERT INTO marketplace_product_versions "
                "(id, product_id, version, status, payload, created_by) "
                "VALUES (gen_random_uuid(), :pid, :ver, :status, CAST(:payload AS jsonb), :by) "
                "ON CONFLICT (product_id, version) DO UPDATE SET "
                "payload = EXCLUDED.payload, status = EXCLUDED.status, created_at = NOW()"
            ),
            {
                "pid": pid,
                "ver": version,
                "status": payload.get("status", "DRAFT"),
                "payload": json.dumps(payload),
                "by": created_by,
            },
        )
        # Dependencias normalizadas.
        await session.execute(
            text("DELETE FROM marketplace_product_dependencies WHERE product_id = :pid"),
            {"pid": pid},
        )
        for dep in payload.get("dependencies") or []:
            await session.execute(
                text(
                    "INSERT INTO marketplace_product_dependencies "
                    "(product_id, kind, ref, requirement, alias) "
                    "VALUES (:pid, :kind, :ref, :req, :alias)"
                ),
                {
                    "pid": pid,
                    "kind": str(dep.get("kind") or "")[:40],
                    "ref": str(dep.get("ref") or "")[:160],
                    "req": str(dep.get("requirement") or "required")[:20],
                    "alias": (str(dep.get("alias") or "")[:80]) or None,
                },
            )
        await session.commit()
    finally:
        await session.close()
    return {"product_id": str(pid), "slug": slug, "version": version}


async def set_version(product_id: UUID, version: int, *, created_by: UUID | None = None) -> dict:
    """Clona la versión actual como nueva versión DRAFT (edit -> test -> publish)."""
    session = await get_async_session()
    try:
        prod = (
            await session.execute(
                text(
                    "SELECT id, status, version FROM marketplace_products WHERE id = :pid"
                ),
                {"pid": product_id},
            )
        ).fetchone()
        if prod is None:
            raise ProductError("producto no encontrado")
        snapshot = (
            await session.execute(
                text(
                    "SELECT payload FROM marketplace_product_versions "
                    "WHERE product_id = :pid AND version = :ver"
                ),
                {"pid": product_id, "ver": prod.version},
            )
        ).fetchone()
        payload = dict(snapshot.payload) if snapshot else {}
        payload["version"] = version
        payload["status"] = "DRAFT"
        await session.execute(
            text(
                "INSERT INTO marketplace_product_versions "
                "(id, product_id, version, status, payload, created_by) "
                "VALUES (gen_random_uuid(), :pid, :ver, 'DRAFT', CAST(:payload AS jsonb), :by)"
            ),
            {"pid": product_id, "ver": version, "payload": json.dumps(payload), "by": created_by},
        )
        await session.execute(
            text("UPDATE marketplace_products SET version = :ver WHERE id = :pid"),
            {"ver": version, "pid": product_id},
        )
        await session.commit()
    finally:
        await session.close()
    return {"product_id": str(product_id), "version": version, "status": "DRAFT"}


async def transition(product_id: UUID, target: str) -> dict:
    """Transición de estado con gate de validación al publicar."""
    session = await get_async_session()
    try:
        prod = (
            await session.execute(
                text(
                    "SELECT id, status, version, name, product_type, short_description, "
                    "included_assets, pricing FROM marketplace_products WHERE id = :pid"
                ),
                {"pid": product_id},
            )
        ).fetchone()
        if prod is None:
            raise ProductError("producto no encontrado")
        current = str(prod.status)
        if target not in ALLOWED_TRANSITIONS.get(current, set()):
            raise ProductError(f"transición inválida: {current} → {target}")
        if target in ("PUBLISHED", "READY"):
            # Publish gate: validación con el fin de negocio.
            gate_errors: list[str] = []
            payload = {
                "slug": str(prod.id),
                "name": prod.name,
                "product_type": prod.product_type,
                "status": target,
                "short_description": prod.short_description,
                "included_assets": prod.included_assets or [],
                "pricing": prod.pricing if isinstance(prod.pricing, dict) else {},
            }
            errors = validate_product(payload)
            if errors:
                raise ProductError("publishing gate: " + "; ".join(errors[:6]))
            _ = gate_errors
        await session.execute(
            text(
                "UPDATE marketplace_products SET status = :target, "
                "published_at = CASE WHEN CAST(:target AS VARCHAR) = 'PUBLISHED' "
                "THEN NOW() ELSE published_at END, "
                "updated_at = NOW() WHERE id = :pid"
            ),
            {"target": target, "pid": product_id},
        )
        await session.execute(
            text(
                "UPDATE marketplace_product_versions SET status = :target, "
                "released_at = CASE WHEN CAST(:target AS VARCHAR) = 'PUBLISHED' "
                "THEN NOW() ELSE released_at END "
                "WHERE product_id = :pid AND version = :ver"
            ),
            {"target": target, "pid": product_id, "ver": prod.version},
        )
        await session.commit()
        return {"product_id": str(product_id), "status": target, "version": int(prod.version)}
    finally:
        await session.close()


async def list_products(
    *,
    product_type: str | None = None,
    status: str | None = None,
    include_hidden: bool = False,
) -> dict:
    session = await get_async_session()
    try:
        sql = (
            "SELECT id, slug, name, short_description, product_type, version, status, "
            "category, pricing, created_at, updated_at, published_at "
            "FROM marketplace_products"
        )
        params: dict[str, Any] = {}
        wheres: list[str] = []
        if not include_hidden:
            wheres.append("(status IN ('PUBLISHED', 'DEPRECATED', 'READY') OR status IS NULL)")
        if product_type:
            wheres.append("product_type = :ptype")
            params["ptype"] = product_type
        if status:
            wheres.append("status = :status")
            params["status"] = status
        if wheres:
            sql += " WHERE " + " AND ".join(wheres)
        rows = (
            await session.execute(text(sql + " ORDER BY created_at DESC"), params)
        ).fetchall()
    finally:
        await session.close()
    return {
        "products": [
            {
                "id": str(r.id),
                "slug": r.slug,
                "name": r.name,
                "short_description": r.short_description,
                "product_type": r.product_type,
                "version": int(r.version or 1),
                "status": r.status,
                "category": r.category,
                "pricing": json.dumps(r.pricing or {}),
                "created_at": _iso(r.created_at),
                "published_at": _iso(r.published_at),
            }
            for r in rows
        ]
    }


async def get_product(product_id: UUID | None = None, slug: str | None = None) -> dict | None:
    session = await get_async_session()
    try:
        if product_id is not None:
            row = (
                await session.execute(
                    text(
                        "SELECT id, slug, name, short_description, long_description, product_type, "
                        "publisher, version, status, category, subcategories, tags, countries, "
                        "industries, logo, screenshots, documentation, pricing, entitlements, "
                        "dependencies, included_assets, installation_flow, configuration_schema, "
                        "result_surfaces, support, security, privacy, certification, release_notes, "
                        "rollout, featured, collections, published_at, created_at, updated_at "
                        "FROM marketplace_products WHERE id = :pid"
                    ),
                    {"pid": product_id},
                )
            ).fetchone()
        else:
            row = (
                await session.execute(
                    text(
                        "SELECT id, slug, name, short_description, long_description, product_type, "
                        "publisher, version, status, category, subcategories, tags, countries, "
                        "industries, logo, screenshots, documentation, pricing, entitlements, "
                        "dependencies, included_assets, installation_flow, configuration_schema, "
                        "result_surfaces, support, security, privacy, certification, release_notes, "
                        "rollout, featured, collections, published_at, created_at, updated_at "
                        "FROM marketplace_products WHERE slug = :slug"
                    ),
                    {"slug": slug},
                )
            ).fetchone()
    finally:
        await session.close()
    if row is None:
        return None
    return {
        "id": str(row.id),
        "slug": row.slug,
        "name": row.name,
        "short_description": row.short_description,
        "long_description": row.long_description,
        "product_type": row.product_type,
        "publisher": str(row.publisher) if row.publisher else None,
        "version": int(row.version or 1),
        "status": row.status,
        "category": row.category,
        "subcategories": row.subcategories or [],
        "tags": json.dumps(row.tags or []),
        "countries": json.dumps(row.countries or []),
        "industries": row.industries or [],
        "logo": row.logo,
        "screenshots": row.screenshots or [],
        "documentation": row.documentation,
        "pricing": json.dumps(row.pricing or {}),
        "entitlements": row.entitlements or {},
        "dependencies": row.dependencies or [],
        "included_assets": row.included_assets or [],
        "installation_flow": row.installation_flow or [],
        "configuration_schema": row.configuration_schema or {},
        "result_surfaces": row.result_surfaces or [],
        "support": json.dumps(row.support or {}),
        "security": row.security or {},
        "privacy": row.privacy or {},
        "certification": row.certification,
        "release_notes": row.release_notes or [],
        "rollout": json.dumps(row.rollout or {}),
        "featured": json.dumps(row.featured or {}),
        "collections": json.dumps(row.collections or []),
        "published_at": _iso(row.published_at),
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


async def impact_analysis(product_id: UUID) -> dict:
    """Instalaciones, workflows, agentes y packs afectados por una acción."""
    session = await get_async_session()
    try:
        installs = (
            await session.execute(
                text(
                    "SELECT organization_id FROM marketplace_product_installations "
                    "WHERE product_id = :pid"
                ),
                {"pid": product_id},
            )
        ).scalar() or 0
        # Workflows/agentes afectados vía dependency refs de packs que usan el producto.
        packs = (
            await session.execute(
                text(
                    "SELECT mp.slug, mp.name FROM marketplace_product_dependencies d "
                    "JOIN marketplace_products mp ON mp.id = d.product_id "
                    "WHERE d.kind IN ('integration', 'action', 'workflow_template', 'agent_template') "
                    "AND d.ref IN (SELECT slug FROM marketplace_products WHERE id = :pid) "
                    "AND mp.id <> :pid"
                ),
                {"pid": product_id},
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "installations": int(installs or 0),
        "dependent_products": [{"slug": p.slug, "name": p.name} for p in packs],
        "workflows": 0,
        "agents": 0,
        "message": "impacto calculado sobre instalaciones y productos dependientes",
    }


async def product_analytics() -> dict:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT COUNT(*) AS total, "
                    "COUNT(*) FILTER (WHERE status = 'PUBLISHED') AS published, "
                    "COUNT(*) FILTER (WHERE status = 'DRAFT') AS drafts "
                    "FROM marketplace_products"
                )
            )
        ).fetchone()
        installs = (
            await session.execute(
                text(
                    "SELECT COUNT(*) AS n FROM marketplace_product_installations"
                )
            )
        ).scalar()
        cols = (
            await session.execute(
                text(
                    "SELECT (SELECT COUNT(*) FROM integration_manifests WHERE status = 'PUBLISHED') AS ints, "
                    "(SELECT COUNT(*) FROM workflow_templates) AS wfs, "
                    "(SELECT COUNT(*) FROM agents) AS agents "
                    "FROM (SELECT 1) x"
                )
            )
        ).fetchone()
    finally:
        await session.close()
    return {
        "products_total": int(row.total or 0),
        "products_published": int(row.published or 0),
        "products_drafts": int(row.drafts or 0),
        "tenant_installations": int(installs or 0),
        "library": {
            "integrations": int(cols.ints or 0),
            "workflow_templates": int(cols.wfs or 0),
            "agents": int(cols.agents or 0),
        },
    }


async def rollout_update(product_id: UUID, rollout: dict) -> dict:
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE marketplace_products SET rollout = CAST(:r AS jsonb), updated_at = NOW() "
                "WHERE id = :pid"
            ),
            {"r": json.dumps(rollout or {}), "pid": product_id},
        )
        await session.commit()
    finally:
        await session.close()
    return {"product_id": str(product_id), "rollout": rollout}
