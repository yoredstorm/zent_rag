# =============================================================================
# Phase 32B — Marketplace catalog (manifests + actions versionados)
# =============================================================================
from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session
from src.platform.marketplace.models import (
    ManifestValidationError,
    can_transition,
    validate_integration_manifest,
)

logger = get_logger(__name__)

_CATALOG_SELECT = (
    "SELECT id, slug, name, provider, version, description, category, logo_ref, "
    "countries, auth_modes, scopes, pricing, rate_limits, data_policy, support, "
    "certification, status FROM integration_manifests"
)


async def list_catalog(
    *,
    category: str | None = None,
    include_draft: bool = False,
) -> dict:
    session = await get_async_session()
    try:
        if category:
            rows = (
                await session.execute(
                    text(
                        _CATALOG_SELECT
                        + " WHERE status IN ('PUBLISHED', 'DEPRECATED')"
                        + " AND category = :cat ORDER BY category, name"
                    ),
                    {"cat": category},
                )
            ).fetchall()
        else:
            rows = (
                await session.execute(
                    text(
                        _CATALOG_SELECT
                        + " WHERE status IN ('PUBLISHED', 'DEPRECATED')"
                        + " ORDER BY category, name"
                    )
                )
            ).fetchall()
    finally:
        await session.close()
    out: list[dict] = []
    for r in rows:
        item = _row_to_manifest(r)
        item["action_count"] = await _count_actions(r.id)
        out.append(item)
    return {"catalog": out}


async def _count_actions(integration_id: UUID) -> int:
    session = await get_async_session()
    try:
        n = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM integration_actions "
                    "WHERE integration_id = :iid AND status = 'ACTIVE'"
                ),
                {"iid": integration_id},
            )
        ).scalar()
    finally:
        await session.close()
    return int(n or 0)


def _row_to_manifest(r) -> dict:
    return {
        "id": str(r.id),
        "slug": r.slug,
        "name": r.name,
        "provider": r.provider,
        "version": int(r.version or 1),
        "description": r.description,
        "category": r.category,
        "logo_ref": r.logo_ref,
        "countries": r.countries,
        "auth_modes": r.auth_modes,
        "scopes": r.scopes,
        "pricing": r.pricing,
        "rate_limits": r.rate_limits,
        "data_policy": r.data_policy,
        "support": r.support,
        "certification": r.certification,
        "status": r.status,
    }


async def get_manifest(slug: str) -> dict | None:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(_CATALOG_SELECT + " WHERE slug = :slug"),
                {"slug": slug},
            )
        ).fetchone()
        if row is None:
            return None
        caps = (
            await session.execute(
                text(
                    "SELECT slug, name, description FROM integration_capabilities "
                    "WHERE integration_id = :iid ORDER BY slug"
                ),
                {"iid": row.id},
            )
        ).fetchall()
        actions = (
            await session.execute(
                text(
                    "SELECT capability_slug, action_id, display_name, description, input_schema, "
                    "output_schema, risk_level, read_only, requires_approval, "
                    "contains_personal_data, sensitive_data_classes, retention_policy, "
                    "cache_policy, timeout_ms, retry_policy, idempotency_support, "
                    "cost_model, version, status "
                    "FROM integration_actions WHERE integration_id = :iid ORDER BY action_id"
                ),
                {"iid": row.id},
            )
        ).fetchall()
    finally:
        await session.close()
    manifest = _row_to_manifest(row)
    manifest["capabilities"] = [
        {
            "slug": c.slug,
            "name": c.name,
            "description": c.description,
            "actions": [
                {
                    "action_id": a.action_id,
                    "display_name": a.display_name,
                    "description": a.description,
                    "input_schema": a.input_schema,
                    "output_schema": a.output_schema,
                    "risk_level": a.risk_level,
                    "read_only": bool(a.read_only),
                    "requires_approval": bool(a.requires_approval),
                    "contains_personal_data": bool(a.contains_personal_data),
                    "sensitive_data_classes": a.sensitive_data_classes,
                    "retention_policy": a.retention_policy,
                    "cache_policy": a.cache_policy,
                    "timeout_ms": int(a.timeout_ms),
                    "retry_policy": a.retry_policy,
                    "idempotency_support": bool(a.idempotency_support),
                    "cost_model": a.cost_model,
                    "version": int(a.version),
                    "status": a.status,
                }
                for a in actions
                if a.capability_slug == c.slug
            ],
        }
        for c in caps
    ]
    return manifest


async def get_action(action_id: str) -> dict | None:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT a.action_id, a.display_name, a.description, a.input_schema, "
                    "a.output_schema, a.risk_level, a.read_only, a.requires_approval, "
                    "a.contains_personal_data, a.sensitive_data_classes, a.retention_policy, "
                    "a.cache_policy, a.timeout_ms, a.retry_policy, a.idempotency_support, "
                    "a.cost_model, a.version, a.status, a.provider_config, a.integration_id, "
                    "m.slug AS integration_slug, m.name AS integration_name "
                    "FROM integration_actions a "
                    "JOIN integration_manifests m ON m.id = a.integration_id "
                    "WHERE a.action_id = :aid"
                ),
                {"aid": action_id},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        return None
    return {
        "action_id": row.action_id,
        "display_name": row.display_name,
        "description": row.description,
        "input_schema": row.input_schema,
        "output_schema": row.output_schema,
        "risk_level": row.risk_level,
        "read_only": bool(row.read_only),
        "requires_approval": bool(row.requires_approval),
        "contains_personal_data": bool(row.contains_personal_data),
        "sensitive_data_classes": row.sensitive_data_classes,
        "retention_policy": row.retention_policy,
        "cache_policy": row.cache_policy,
        "timeout_ms": int(row.timeout_ms),
        "retry_policy": row.retry_policy,
        "idempotency_support": bool(row.idempotency_support),
        "cost_model": row.cost_model,
        "version": int(row.version),
        "status": row.status,
        "provider_config": row.provider_config,
        "integration_id": str(row.integration_id),
        "integration_slug": row.integration_slug,
        "integration_name": row.integration_name,
    }


async def register_manifest(manifest: dict, created_by: UUID | None = None) -> dict:
    """Registra/actualiza un manifest (workflow de publishing: DRAFT → …)."""
    errors = validate_integration_manifest(manifest)
    if errors:
        raise ManifestValidationError("; ".join(errors[:10]))
    session = await get_async_session()
    try:
        existing = (
            await session.execute(
                text("SELECT id, status FROM integration_manifests WHERE slug = :slug"),
                {"slug": manifest["slug"]},
            )
        ).fetchone()
        status = str(manifest.get("status") or "DRAFT")
        if existing is not None and not can_transition(existing.status, status):
            raise ManifestValidationError(f"transición inválida: {existing.status} → {status}")
        if existing is None:
            mid = (
                await session.execute(
                    text(
                        "INSERT INTO integration_manifests "
                        "(slug, name, provider, version, description, category, logo_ref, "
                        "countries, auth_modes, scopes, pricing, rate_limits, data_policy, "
                        "support, certification, status, created_by) "
                        "VALUES (:slug, :name, :provider, 1, :desc, :cat, :logo, "
                        "CAST(:countries AS jsonb), CAST(:auth AS jsonb), CAST(:scopes AS jsonb), "
                        "CAST(:pricing AS jsonb), CAST(:rl AS jsonb), CAST(:dp AS jsonb), "
                        "CAST(:support AS jsonb), :cert, :status, :by) RETURNING id"
                    ),
                    {
                        "slug": manifest["slug"],
                        "name": manifest["name"],
                        "provider": manifest.get("provider", "Partner"),
                        "desc": manifest.get("description"),
                        "cat": manifest.get("category", "other"),
                        "logo": manifest.get("logo_ref"),
                        "countries": json.dumps(manifest.get("countries") or []),
                        "auth": json.dumps(manifest.get("auth_modes") or ["BYOC"]),
                        "scopes": json.dumps(manifest.get("scopes") or []),
                        "pricing": json.dumps(manifest.get("pricing") or {}),
                        "rl": json.dumps(manifest.get("rate_limits") or {}),
                        "dp": json.dumps(manifest.get("data_policy") or {}),
                        "support": json.dumps(manifest.get("support") or {}),
                        "cert": manifest.get("certification"),
                        "status": status,
                        "by": created_by,
                    },
                )
            ).scalar()
            for cap in manifest.get("capabilities") or []:
                cap_row = (
                    await session.execute(
                        text(
                            "INSERT INTO integration_capabilities "
                            "(integration_id, slug, name, description) "
                            "VALUES (:iid, :slug, :name, :desc) RETURNING id"
                        ),
                        {
                            "iid": mid,
                            "slug": cap["slug"],
                            "name": cap.get("name", cap["slug"]),
                            "desc": cap.get("description"),
                        },
                    )
                ).scalar()
                for act in cap.get("actions") or []:
                    await _insert_action(session, mid, cap["slug"], act)
                _ = cap_row
        else:
            await session.execute(
                text(
                    "UPDATE integration_manifests SET status = :status, updated_at = NOW(), "
                    "pricing = CAST(:pricing AS jsonb) WHERE id = :mid"
                ),
                {
                    "status": status,
                    "pricing": json.dumps(manifest.get("pricing") or {}),
                    "mid": existing.id,
                },
            )
            mid = existing.id
        await session.commit()
    finally:
        await session.close()
    return {"slug": manifest["slug"], "status": status, "id": str(mid)}


async def _insert_action(session, integration_id: UUID, capability_slug: str, act: dict) -> None:
    await session.execute(
        text(
            "INSERT INTO integration_actions "
            "(integration_id, capability_slug, action_id, display_name, description, "
            "input_schema, output_schema, risk_level, read_only, requires_approval, "
            "contains_personal_data, sensitive_data_classes, retention_policy, cache_policy, "
            "timeout_ms, retry_policy, idempotency_support, cost_model, provider_config) "
            "VALUES (:iid, :cap, :aid, :dn, :desc, CAST(:ins AS jsonb), CAST(:outs AS jsonb), "
            ":risk, :ro, :ra, :pd, CAST(:sdc AS jsonb), CAST(:rp AS jsonb), "
            "CAST(:cp AS jsonb), :tmo, CAST(:retry AS jsonb), :idem, CAST(:cost AS jsonb), "
            "CAST(:pc AS jsonb)) ON CONFLICT (action_id) DO NOTHING"
        ),
        {
            "iid": integration_id,
            "cap": capability_slug,
            "aid": act["action_id"],
            "dn": act.get("display_name", act["action_id"]),
            "desc": act.get("description"),
            "ins": json.dumps(act.get("input_schema") or {}),
            "outs": json.dumps(act.get("output_schema") or {}),
            "risk": act.get("risk_level", "info"),
            "ro": bool(act.get("read_only", True)),
            "ra": bool(act.get("requires_approval", False)),
            "pd": bool(act.get("contains_personal_data", False)),
            "sdc": json.dumps(act.get("sensitive_data_classes") or []),
            "rp": json.dumps(act.get("retention_policy") or {}),
            "cp": json.dumps(act.get("cache_policy") or {}),
            "tmo": int(act.get("timeout_ms", 5_000)),
            "retry": json.dumps(act.get("retry_policy") or {}),
            "idem": bool(act.get("idempotency_support", False)),
            "cost": json.dumps(act.get("cost_model") or {}),
            "pc": json.dumps(act.get("provider_config") or {}),
        },
    )


async def set_action_status(action_id: str, status: str) -> bool:
    if status not in ("ACTIVE", "DEPRECATED", "END_OF_LIFE"):
        raise ManifestValidationError("status de acción inválido")
    session = await get_async_session()
    try:
        result = await session.execute(
            text("UPDATE integration_actions SET status = :status WHERE action_id = :aid RETURNING id"),
            {"status": status, "aid": action_id},
        )
        await session.commit()
        return result.rowcount > 0
    finally:
        await session.close()
