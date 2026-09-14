# =============================================================================
# Universal API Connector — borradores de importación (misión §11-§13).
#
# El documento OpenAPI se transforma en un IntegrationDraft persistido y
# revisable. La instalación sólo ocurre tras la revisión humana: nunca se
# registra ni ejecuta nada durante el discovery.
# =============================================================================
from __future__ import annotations

import json
import re
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

DRAFT_STATUSES = ("draft", "installed", "discarded")
AUTH_KINDS = ("none", "api_key", "bearer", "basic", "oauth2")


class DraftError(ValueError):
    """Error de borrador (validación o estado)."""

    code = "DRAFT_ERROR"


class DraftNotFound(DraftError):
    code = "DRAFT_NOT_FOUND"


def _slug_org_suffix(organization_id: UUID) -> str:
    return organization_id.hex[:8]


async def _unique_manifest_slug(session, slug: str, organization_id: UUID) -> str:
    """Slug único global: si otro tenant ya lo usa (o es público), sufija."""
    row = (
        await session.execute(
            text("SELECT organization_id FROM integration_manifests WHERE slug = :slug"),
            {"slug": slug},
        )
    ).fetchone()
    if row is None or (row.organization_id is not None and row.organization_id == organization_id):
        return slug
    return f"{slug[:66]}-{_slug_org_suffix(organization_id)}"


def _draft_row(r) -> dict:
    return {
        "draft_id": str(r.id),
        "slug": r.slug,
        "name": r.name,
        "source_kind": r.source_kind,
        "source_url": r.source_url,
        "spec_hash": r.spec_hash,
        "openapi_version": r.openapi_version,
        "base_url": r.base_url,
        "auth_mode": r.auth_mode,
        "status": r.status,
        "integration_slug": r.integration_slug,
        "install_id": str(r.install_id) if r.install_id else None,
        "report": r.report or {},
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


def _draft_summary(r) -> dict:
    out = _draft_row(r)
    draft = r.draft or {}
    out["actions"] = sum(
        len(cap.get("actions") or []) for cap in (draft.get("capabilities") or [])
    )
    out["auth"] = draft.get("auth") or {"kind": r.auth_mode}
    out.pop("report", None)
    return out


_SELECT = (
    "SELECT id, organization_id, workspace_id, slug, name, source_kind, source_url, "
    "spec_hash, openapi_version, base_url, auth_mode, draft, report, status, "
    "integration_slug, install_id, created_by, created_at, updated_at "
    "FROM integration_drafts"
)


async def create_draft(
    organization_id: UUID,
    draft: dict,
    *,
    workspace_id: UUID | None = None,
    created_by: UUID | None = None,
) -> dict:
    """Persiste un IntegrationDraft (upsert por org+slug: reimportar actualiza)."""
    slug = str(draft.get("slug") or "").strip()
    if not slug:
        raise DraftError("borrador sin slug")
    source = draft.get("source") or {}
    auth_kind = str((draft.get("auth") or {}).get("kind") or "none")
    if auth_kind not in AUTH_KINDS:
        raise DraftError(f"auth kind inválido: {auth_kind}")
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO integration_drafts "
                    "(organization_id, workspace_id, slug, name, source_kind, source_url, "
                    "spec_hash, openapi_version, base_url, auth_mode, draft, report, status, created_by) "
                    "VALUES (:oid, :ws, :slug, :name, :sk, :su, :hash, :ver, :base, :auth, "
                    "CAST(:draft AS jsonb), CAST(:report AS jsonb), 'draft', :by) "
                    "ON CONFLICT (organization_id, slug) DO UPDATE SET "
                    "name = EXCLUDED.name, source_kind = EXCLUDED.source_kind, "
                    "source_url = EXCLUDED.source_url, spec_hash = EXCLUDED.spec_hash, "
                    "openapi_version = EXCLUDED.openapi_version, base_url = EXCLUDED.base_url, "
                    "auth_mode = EXCLUDED.auth_mode, draft = EXCLUDED.draft, "
                    "report = EXCLUDED.report, status = 'draft', "
                    "updated_at = NOW() "
                    "RETURNING id, organization_id, workspace_id, slug, name, source_kind, "
                    "source_url, spec_hash, openapi_version, base_url, auth_mode, draft, report, "
                    "status, integration_slug, install_id, created_by, created_at, updated_at"
                ),
                {
                    "oid": organization_id,
                    "ws": workspace_id,
                    "slug": slug[:80],
                    "name": str(draft.get("name") or slug)[:150],
                    "sk": str(source.get("kind") or "document")[:20],
                    "su": source.get("url"),
                    "hash": source.get("spec_hash"),
                    "ver": str(source.get("openapi_version") or "")[:20],
                    "base": draft.get("base_url"),
                    "auth": auth_kind[:30],
                    "draft": json.dumps(draft),
                    "report": json.dumps(draft.get("report") or {}),
                    "by": created_by,
                },
            )
        ).fetchone()
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise DraftError("ya existe un borrador con ese slug") from exc
    finally:
        await session.close()
    return _draft_row(row)


async def list_drafts(organization_id: UUID, *, status: str | None = None) -> dict:
    session = await get_async_session()
    try:
        params: dict[str, Any] = {"oid": organization_id}
        sql = _SELECT + " WHERE organization_id = :oid"
        if status:
            sql += " AND status = :status"
            params["status"] = status
        else:
            sql += " AND status <> 'discarded'"
        rows = (await session.execute(text(sql + " ORDER BY updated_at DESC LIMIT 200"), params)).fetchall()
    finally:
        await session.close()
    return {"drafts": [_draft_summary(r) for r in rows]}


async def get_draft(organization_id: UUID, draft_id: UUID) -> dict | None:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(_SELECT + " WHERE id = :did AND organization_id = :oid"),
                {"did": draft_id, "oid": organization_id},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        return None
    out = _draft_row(row)
    out["draft"] = row.draft or {}
    return out


def _clean_text(value: Any, *, max_len: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:max_len]


def apply_draft_patch(draft: dict, patch: dict) -> dict:
    """Aplica la revisión humana: nombres, labels, auth, mapping y enable/disable."""
    auth = dict(draft.get("auth") or {})
    if "auth_kind" in patch:
        kind = str(patch.get("auth_kind") or "none")
        if kind not in AUTH_KINDS:
            raise DraftError(f"auth kind inválido: {kind}")
        auth["kind"] = kind
    if "auth_header_name" in patch and patch.get("auth_header_name"):
        auth["header_name"] = _clean_text(patch["auth_header_name"], max_len=60)
    draft["auth"] = auth

    if "name" in patch and str(patch.get("name") or "").strip():
        name = _clean_text(patch["name"], max_len=150)
        draft["name"] = name
    if "description" in patch:
        draft["description"] = _clean_text(patch.get("description"), max_len=400)
    if "base_url" in patch and patch.get("base_url"):
        from src.platform.marketplace.openapi_import import validate_server_url

        base_url = str(patch["base_url"]).rstrip("/")
        validate_server_url(base_url)
        draft["base_url"] = base_url
        for cap in draft.get("capabilities") or []:
            for action in cap.get("actions") or []:
                action["base_url"] = base_url
    if "rate_limits" in patch:
        rl = patch.get("rate_limits") or {}
        cleaned: dict[str, int] = {}
        for key in ("requests_per_minute", "requests_per_day"):
            try:
                value = int(rl.get(key) or 0)
            except (TypeError, ValueError):
                value = 0
            if value > 0:
                cleaned[key] = min(value, 1_000_000)
        draft["rate_limits"] = cleaned

    actions_patch = {
        str(item.get("action_id")): item
        for item in (patch.get("actions") or [])
        if isinstance(item, dict) and item.get("action_id")
    }
    for cap in draft.get("capabilities") or []:
        if "name" in patch and str(cap.get("slug")) == str(patch.get("capability_slug")):
            cap["name"] = _clean_text(patch["name"], max_len=80)
        for action in cap.get("actions") or []:
            item = actions_patch.get(str(action.get("action_id")))
            if not item:
                continue
            if str(item.get("display_name") or "").strip():
                action["display_name"] = _clean_text(item["display_name"], max_len=120)
            if "description" in item:
                action["description"] = _clean_text(item.get("description"), max_len=300)
            if "enabled" in item:
                action["enabled"] = bool(item["enabled"])
            if "requires_approval" in item:
                action["requires_approval"] = bool(item["requires_approval"])
            if isinstance(item.get("output_map"), dict):
                action["output_map"] = {
                    _clean_text(k, max_len=60): _clean_text(v, max_len=160)
                    for k, v in item["output_map"].items()
                    if k and v
                }
    return draft


async def update_draft(organization_id: UUID, draft_id: UUID, patch: dict) -> dict | None:
    current = await get_draft(organization_id, draft_id)
    if current is None:
        return None
    draft = apply_draft_patch(dict(current.get("draft") or {}), patch)
    auth_kind = str((draft.get("auth") or {}).get("kind") or "none")
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE integration_drafts SET name = :name, base_url = :base, auth_mode = :auth, "
                "draft = CAST(:draft AS jsonb), updated_at = NOW() "
                "WHERE id = :did AND organization_id = :oid"
            ),
            {
                "name": str(draft.get("name") or "")[:150],
                "base": draft.get("base_url"),
                "auth": auth_kind[:30],
                "draft": json.dumps(draft),
                "did": draft_id,
                "oid": organization_id,
            },
        )
        await session.commit()
    finally:
        await session.close()
    return await get_draft(organization_id, draft_id)


async def discard_draft(organization_id: UUID, draft_id: UUID) -> bool:
    session = await get_async_session()
    try:
        result = await session.execute(
            text(
                "UPDATE integration_drafts SET status = 'discarded', updated_at = NOW() "
                "WHERE id = :did AND organization_id = :oid AND status <> 'installed'"
            ),
            {"did": draft_id, "oid": organization_id},
        )
        await session.commit()
        return result.rowcount > 0
    finally:
        await session.close()


async def install_draft(
    organization_id: UUID,
    draft_id: UUID,
    *,
    workspace_id: UUID | None = None,
    created_by: UUID | None = None,
    purpose: str | None = None,
) -> dict:
    """Revisión humana → manifest publicado para el tenant + instalación."""
    from src.platform.marketplace import catalog
    from src.platform.marketplace.openapi_import import draft_to_manifest
    from src.platform.marketplace.runtime import install_integration

    current = await get_draft(organization_id, draft_id)
    if current is None:
        raise DraftNotFound("borrador no encontrado")
    if current["status"] == "discarded":
        raise DraftError("el borrador fue descartado")
    draft = current.get("draft") or {}
    session = await get_async_session()
    try:
        final_slug = await _unique_manifest_slug(session, str(current["slug"]), organization_id)
    finally:
        await session.close()
    manifest = draft_to_manifest(draft, slug=final_slug, organization_id=organization_id)
    registered = await catalog.register_manifest(
        manifest, created_by, organization_id=organization_id
    )
    install = await install_integration(
        organization_id,
        str(registered["slug"]),
        workspace_id=workspace_id,
        created_by=created_by,
        purpose=purpose,
    )
    auth_kind = str((draft.get("auth") or {}).get("kind") or "none")
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE integration_drafts SET status = 'installed', integration_slug = :slug, "
                "install_id = :iid, updated_at = NOW() "
                "WHERE id = :did AND organization_id = :oid"
            ),
            {
                "slug": registered["slug"],
                "iid": install["install_id"],
                "did": draft_id,
                "oid": organization_id,
            },
        )
        await session.commit()
    finally:
        await session.close()
    return {
        "draft_id": str(draft_id),
        "integration_slug": registered["slug"],
        "install_id": install["install_id"],
        "reused": bool(install.get("reused", False)),
        "credentials_required": auth_kind != "none",
        "auth_kind": auth_kind,
        "actions": sum(len(c["actions"]) for c in manifest["capabilities"]),
    }


__all__ = [
    "DraftError",
    "DraftNotFound",
    "apply_draft_patch",
    "create_draft",
    "discard_draft",
    "get_draft",
    "install_draft",
    "list_drafts",
    "update_draft",
]
