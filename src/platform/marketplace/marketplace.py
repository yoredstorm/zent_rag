# =============================================================================
# Marketplace & Sharing — publicar/clonar agentes, reviews/rating, share links,
# prompt templates.
# =============================================================================
from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

_SNAPSHOT_KEYS = ("name", "description", "system_prompt", "tools", "model", "config_json")


def _snapshot_agent(agent) -> dict:
    cfg = agent.config_json or {}
    return {
        "name": agent.name,
        "description": agent.description,
        "system_prompt": agent.system_prompt,
        "tools": list(agent.tools or []),
        "model": agent.model,
        "config_json": cfg,
    }


def _listing_response(r) -> dict:
    return {
        "id": str(r.id),
        "agent_id": str(r.agent_id),
        "organization_id": str(r.organization_id),
        "name": r.name,
        "description": r.description,
        "category": r.category,
        "tags": list(r.tags or []),
        "rating_avg": round(float(r.rating_avg or 0), 2),
        "rating_count": int(r.rating_count or 0),
        "installs": int(r.installs or 0),
        "status": r.status,
        "created_at": r.created_at.isoformat(),
        "updated_at": r.updated_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# Marketplace
# ---------------------------------------------------------------------------
async def publish_agent(
    organization_id: UUID,
    agent_id: UUID,
    name: str,
    description: str | None,
    category: str,
    tags: list[str],
) -> dict:
    from src.infrastructure.postgres.relational_db import PostgresAgentRepository

    agent = await PostgresAgentRepository().get_agent(organization_id, agent_id)
    if agent is None:
        return {"status": "agent_not_found"}
    snapshot = _snapshot_agent(agent)
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO marketplace_listings (id, agent_id, organization_id, "
                    "name, description, category, tags, agent_snapshot, status) "
                    "VALUES (gen_random_uuid(), :aid, :oid, :name, :desc, :cat, :tags, "
                    ":snap, 'published') "
                    "ON CONFLICT (agent_id) DO UPDATE SET name = EXCLUDED.name, "
                    "description = EXCLUDED.description, category = EXCLUDED.category, "
                    "tags = EXCLUDED.tags, agent_snapshot = EXCLUDED.agent_snapshot, "
                    "status = 'published', updated_at = NOW() "
                    "RETURNING *"
                ),
                {
                    "aid": agent_id,
                    "oid": organization_id,
                    "name": name,
                    "desc": description,
                    "cat": category,
                    "tags": json.dumps(tags),
                    "snap": json.dumps(snapshot),
                },
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    return {"status": "published", "listing": _listing_response(row)}


async def unpublish_listing(listing_id: UUID) -> bool:
    session = await get_async_session()
    try:
        result = await session.execute(
            text(
                "UPDATE marketplace_listings SET status = 'unpublished', "
                "updated_at = NOW() WHERE id = :lid"
            ),
            {"lid": listing_id},
        )
        await session.commit()
        return result.rowcount > 0
    finally:
        await session.close()


async def list_listings(
    q: str | None = None, category: str | None = None, status: str = "published", limit: int = 50
) -> list[dict]:
    session = await get_async_session()
    try:
        sql = (
            "SELECT id, agent_id, organization_id, name, description, category, tags, "
            "rating_avg, rating_count, installs, status, created_at, updated_at "
            "FROM marketplace_listings WHERE status = :status "
        )
        params: dict = {"status": status, "limit": min(limit, 200)}
        if q:
            sql += " AND (name ILIKE :q OR description ILIKE :q) "
            params["q"] = f"%{q}%"
        if category:
            sql += " AND category = :cat "
            params["cat"] = category
        sql += " ORDER BY rating_avg DESC, installs DESC LIMIT :limit"
        rows = (await session.execute(text(sql), params)).fetchall()
    finally:
        await session.close()
    return [_listing_response(r) for r in rows]


async def get_listing(listing_id: UUID) -> dict | None:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT id, agent_id, organization_id, name, description, category, "
                    "tags, agent_snapshot, rating_avg, rating_count, installs, status, "
                    "created_at, updated_at FROM marketplace_listings WHERE id = :lid"
                ),
                {"lid": listing_id},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        return None
    resp = _listing_response(row)
    resp["agent_snapshot"] = row.agent_snapshot or {}
    return resp


async def add_review(listing_id: UUID, organization_id: UUID, rating: int, comment: str | None) -> dict:
    session = await get_async_session()
    try:
        result = await session.execute(
            text(
                "INSERT INTO marketplace_reviews (id, listing_id, organization_id, "
                "rating, comment) VALUES (gen_random_uuid(), :lid, :oid, :rating, :comment) "
                "ON CONFLICT (listing_id, organization_id) DO NOTHING RETURNING id"
            ),
            {"lid": listing_id, "oid": organization_id, "rating": rating, "comment": comment},
        )
        inserted = result.scalar()
        if inserted is None:
            return {"status": "already_reviewed"}
        await session.execute(
            text(
                "UPDATE marketplace_listings SET rating_avg = "
                "(SELECT AVG(rating) FROM marketplace_reviews WHERE listing_id = :lid), "
                "rating_count = (SELECT COUNT(*) FROM marketplace_reviews WHERE listing_id = :lid), "
                "updated_at = NOW() WHERE id = :lid"
            ),
            {"lid": listing_id},
        )
        await session.commit()
        return {"status": "reviewed"}
    finally:
        await session.close()


async def list_reviews(listing_id: UUID) -> list[dict]:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id, organization_id, rating, comment, created_at "
                    "FROM marketplace_reviews WHERE listing_id = :lid "
                    "ORDER BY created_at DESC LIMIT 50"
                ),
                {"lid": listing_id},
            )
        ).fetchall()
    finally:
        await session.close()
    return [
        {
            "id": str(r.id),
            "organization_id": str(r.organization_id),
            "rating": int(r.rating),
            "comment": r.comment,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


async def install_listing(listing_id: UUID, target_organization_id: UUID) -> dict:
    """Clona el snapshot del listing en la org destino y cuenta installs."""
    from src.infrastructure.postgres.relational_db import PostgresAgentRepository

    listing = await get_listing(listing_id)
    if listing is None or listing["status"] != "published":
        return {"status": "not_found"}
    snap = listing["agent_snapshot"]
    repo = PostgresAgentRepository()
    agent = await repo.create_agent(
        target_organization_id,
        name=f"{snap.get('name') or listing['name']} (mkt)",
        description=snap.get("description"),
        system_prompt=snap.get("system_prompt"),
        tools=snap.get("tools"),
        model=snap.get("model"),
        config_json=snap.get("config_json") or {},
    )
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE marketplace_listings SET installs = installs + 1, "
                "updated_at = NOW() WHERE id = :lid"
            ),
            {"lid": listing_id},
        )
        await session.commit()
    finally:
        await session.close()
    return {"status": "installed", "agent_id": str(agent.id), "listing_id": listing_id}


async def clone_agent(organization_id: UUID, agent_id: UUID) -> dict:
    from src.infrastructure.postgres.relational_db import PostgresAgentRepository

    repo = PostgresAgentRepository()
    agent = await repo.get_agent(organization_id, agent_id)
    if agent is None:
        return {"status": "agent_not_found"}
    copy = await repo.create_agent(
        organization_id,
        name=f"{agent.name} (copia)",
        description=agent.description,
        system_prompt=agent.system_prompt,
        tools=list(agent.tools or []),
        model=agent.model,
        config_json=agent.config_json or {},
    )
    return {"status": "cloned", "agent_id": str(copy.id)}


# ---------------------------------------------------------------------------
# Share links
# ---------------------------------------------------------------------------
async def create_share_link(
    organization_id: UUID, agent_id: UUID, expires_days: int | None, max_uses: int | None
) -> dict:
    from src.infrastructure.postgres.relational_db import PostgresAgentRepository

    agent = await PostgresAgentRepository().get_agent(organization_id, agent_id)
    if agent is None:
        return {"status": "agent_not_found"}
    token = secrets.token_urlsafe(24)
    expires_at = (
        datetime.now(timezone.utc) + timedelta(days=expires_days)
        if expires_days
        else None
    )
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO agent_share_links (id, agent_id, organization_id, "
                    "token, expires_at, max_uses) "
                    "VALUES (gen_random_uuid(), :aid, :oid, :token, :exp, :max) "
                    "RETURNING id, token, expires_at, max_uses"
                ),
                {"aid": agent_id, "oid": organization_id, "token": token, "exp": expires_at, "max": max_uses},
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    return {
        "status": "created",
        "link_id": str(row.id),
        "token": token,
        "url": f"/share/agent/{token}",
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "max_uses": row.max_uses,
    }


async def get_agent_by_share_token(token: str) -> dict | None:
    """Valida token + expiry + usos; registra el uso (fail-soft)."""
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT id, agent_id, organization_id, expires_at, max_uses, uses, "
                    "enabled FROM agent_share_links WHERE token = :token"
                ),
                {"token": token},
            )
        ).fetchone()
        if row is None or not row.enabled:
            return None
        if row.expires_at and row.expires_at < datetime.now(timezone.utc):
            return None
        if row.max_uses is not None and row.uses >= row.max_uses:
            return None
        await session.execute(
            text(
                "UPDATE agent_share_links SET uses = uses + 1 WHERE id = :lid"
            ),
            {"lid": row.id},
        )
        await session.commit()
        agent_row = (
            await session.execute(
                text(
                    "SELECT name, description, system_prompt, tools, model, config_json "
                    "FROM agents WHERE id = :aid AND organization_id = :oid"
                ),
                {"aid": row.agent_id, "oid": row.organization_id},
            )
        ).fetchone()
    finally:
        await session.close()
    if agent_row is None:
        return None
    return {
        "name": agent_row.name,
        "description": agent_row.description,
        "system_prompt": agent_row.system_prompt,
        "tools": list(agent_row.tools or []),
        "model": agent_row.model,
        "config": agent_row.config_json or {},
    }


async def list_share_links(organization_id: UUID, agent_id: UUID) -> list[dict]:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id, token, expires_at, max_uses, uses, enabled, created_at "
                    "FROM agent_share_links WHERE agent_id = :aid AND organization_id = :oid "
                    "ORDER BY created_at DESC"
                ),
                {"aid": agent_id, "oid": organization_id},
            )
        ).fetchall()
    finally:
        await session.close()
    return [
        {
            "id": str(r.id),
            "token": r.token,
            "expires_at": r.expires_at.isoformat() if r.expires_at else None,
            "max_uses": r.max_uses,
            "uses": int(r.uses),
            "enabled": bool(r.enabled),
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


async def revoke_share_link(organization_id: UUID, link_id: UUID) -> bool:
    session = await get_async_session()
    try:
        result = await session.execute(
            text(
                "UPDATE agent_share_links SET enabled = false "
                "WHERE id = :lid AND organization_id = :oid"
            ),
            {"lid": link_id, "oid": organization_id},
        )
        await session.commit()
        return result.rowcount > 0
    finally:
        await session.close()


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------
async def list_templates(category: str | None = None) -> list[dict]:
    session = await get_async_session()
    try:
        sql = "SELECT id, name, category, description, content, is_builtin, created_at FROM prompt_templates WHERE 1=1 "
        params: dict = {}
        if category:
            sql += " AND category = :cat "
            params["cat"] = category
        sql += " ORDER BY is_builtin DESC, name"
        rows = (await session.execute(text(sql), params)).fetchall()
    finally:
        await session.close()
    return [
        {
            "id": str(r.id),
            "name": r.name,
            "category": r.category,
            "description": r.description,
            "content": r.content,
            "is_builtin": bool(r.is_builtin),
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


async def create_template(
    name: str, category: str, description: str | None, content: str, created_by: UUID | None
) -> dict:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO prompt_templates (id, name, category, description, "
                    "content, created_by) VALUES (gen_random_uuid(), :name, :cat, :desc, "
                    ":content, :by) RETURNING id, name, category, is_builtin"
                ),
                {
                    "name": name,
                    "cat": category,
                    "desc": description,
                    "content": content,
                    "by": created_by,
                },
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    return {"id": str(row.id), "name": row.name, "category": row.category, "is_builtin": bool(row.is_builtin)}


async def update_template(template_id: UUID, **fields) -> bool:
    session = await get_async_session()
    try:
        sets: list[str] = []
        params: dict = {"tid": template_id}
        for key in ("name", "category", "description", "content"):
            if key in fields and fields[key] is not None:
                sets.append(f"{key} = :{key}")
                params[key] = fields[key]
        if not sets:
            return False
        await session.execute(
            text(f"UPDATE prompt_templates SET {', '.join(sets)} WHERE id = :tid"),  # noqa: S608 (keys fijas)
            params,
        )
        await session.commit()
        return True
    finally:
        await session.close()


async def delete_template(template_id: UUID) -> bool:
    session = await get_async_session()
    try:
        result = await session.execute(
            text(
                "DELETE FROM prompt_templates WHERE id = :tid AND is_builtin = false"
            ),
            {"tid": template_id},
        )
        await session.commit()
        return result.rowcount > 0
    finally:
        await session.close()
