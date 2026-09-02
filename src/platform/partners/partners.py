# =============================================================================
# Partner Ecosystem — partners con rev-share, metering, subtenants white-label,
# catálogo de integraciones.
# =============================================================================
from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

PARTNER_SCOPE = "partner:*"


# ---------------------------------------------------------------------------
# Partners CRUD
# ---------------------------------------------------------------------------
async def create_partner(
    organization_id: UUID,
    name: str,
    contact_email: str | None,
    rev_share_pct: float,
) -> dict:
    from src.platform.billing.service import generate_api_token

    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO partners (id, organization_id, name, contact_email, "
                    "rev_share_pct) VALUES (gen_random_uuid(), :oid, :name, :email, :share) "
                    "RETURNING id, name, rev_share_pct"
                ),
                {"oid": organization_id, "name": name, "email": contact_email, "share": rev_share_pct},
            )
        ).fetchone()
        partner_id = row.id
        token = generate_api_token("zent_sk_partner")
        from src.infrastructure.postgres.relational_db import (
            PostgresApiKeyRepository as _Repo,
        )

        key = await _Repo().create_key(
            organization_id,
            token,
            name=f"Partner: {name} ({str(partner_id)[:8]})",
            scopes=[PARTNER_SCOPE, "agents:execute", "rag:read"],
            created_by=None,
        )
        # Vincular la key al partner.
        session2 = await get_async_session()
        try:
            await session2.execute(
                text("UPDATE api_keys SET partner_id = :pid WHERE id = :kid"),
                {"pid": partner_id, "kid": key.id},
            )
            await session2.commit()
        finally:
            await session2.close()
        await session.commit()
    finally:
        await session.close()
    return {
        "id": str(partner_id),
        "name": row.name,
        "rev_share_pct": float(row.rev_share_pct),
        "api_token": token,
        "status": "active",
    }


def _partner_response(r) -> dict:
    return {
        "id": str(r.id),
        "organization_id": str(r.organization_id),
        "name": r.name,
        "contact_email": r.contact_email,
        "rev_share_pct": float(r.rev_share_pct or 0),
        "status": r.status,
        "white_label_enabled": bool(r.white_label_enabled),
        "branding": r.branding or {},
        "created_at": r.created_at.isoformat(),
    }


async def list_partners() -> list[dict]:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id, organization_id, name, contact_email, rev_share_pct, "
                    "status, white_label_enabled, branding, created_at "
                    "FROM partners ORDER BY created_at DESC"
                )
            )
        ).fetchall()
    finally:
        await session.close()
    return [_partner_response(r) for r in rows]


async def get_partner(partner_id: UUID) -> dict | None:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT id, organization_id, name, contact_email, rev_share_pct, "
                    "status, white_label_enabled, branding, created_at "
                    "FROM partners WHERE id = :pid"
                ),
                {"pid": partner_id},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        return None
    return _partner_response(row)


async def update_partner(partner_id: UUID, **fields) -> bool:
    allowed = {"name", "contact_email", "rev_share_pct", "white_label_enabled"}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    session = await get_async_session()
    try:
        sets: list[str] = []
        params: dict = {"pid": partner_id}
        for key, value in updates.items():
            sets.append(f"{key} = :{key}")
            params[key] = value
        if not sets:
            return False
        result = await session.execute(
            text(
                f"UPDATE partners SET {', '.join(sets)} WHERE id = :pid"  # noqa: S608 (keys whitelisted)
            ),
            params,
        )
        await session.commit()
        return result.rowcount > 0
    finally:
        await session.close()


async def set_partner_status(partner_id: UUID, status: str) -> bool:
    session = await get_async_session()
    try:
        result = await session.execute(
            text("UPDATE partners SET status = :status WHERE id = :pid"),
            {"status": status, "pid": partner_id},
        )
        await session.commit()
        return result.rowcount > 0
    finally:
        await session.close()


# ---------------------------------------------------------------------------
# Metering + rev-share
# ---------------------------------------------------------------------------
async def record_partner_usage(
    partner_id: UUID, organization_id: UUID, tokens: int, cost: float, event_type: str = "api_query"
) -> None:
    try:
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    "INSERT INTO partner_usage (id, partner_id, organization_id, "
                    "event_type, tokens, cost) VALUES (gen_random_uuid(), :pid, :oid, "
                    ":etype, :tokens, :cost)"
                ),
                {
                    "pid": partner_id,
                    "oid": organization_id,
                    "etype": event_type,
                    "tokens": tokens,
                    "cost": cost,
                },
            )
            await session.commit()
        finally:
            await session.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Partner usage record failed", error=str(exc)[:150])


async def partner_usage(partner_id: UUID, days: int = 30) -> dict:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT DATE_TRUNC('day', created_at)::date AS day, "
                    "COUNT(*)::int AS requests, "
                    "COALESCE(SUM(tokens), 0)::bigint AS tokens, "
                    "COALESCE(SUM(cost), 0)::float AS cost "
                    "FROM partner_usage WHERE partner_id = :pid "
                    "AND created_at > NOW() - MAKE_INTERVAL(days => :days) "
                    "GROUP BY 1 ORDER BY 1"
                ),
                {"pid": partner_id, "days": max(1, min(days, 365))},
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "partner_id": str(partner_id),
        "days": days,
        "by_day": [
            {
                "date": r.day.isoformat(),
                "requests": int(r.requests),
                "tokens": int(r.tokens),
                "cost": round(float(r.cost), 4),
            }
            for r in rows
        ],
        "total_requests": sum(int(r.requests) for r in rows),
        "total_cost": round(sum(float(r.cost) for r in rows), 4),
    }


async def calculate_commission(partner_id: UUID, period: str) -> dict:
    """Revenue = costo de consumo del período; commission = revenue × rev_share_pct."""
    partner = await get_partner(partner_id)
    if partner is None:
        return {"status": "not_found"}
    session = await get_async_session()
    try:
        usage = (
            await session.execute(
                text(
                    "SELECT COALESCE(SUM(cost), 0)::float AS revenue "
                    "FROM partner_usage WHERE partner_id = :pid "
                    "AND TO_CHAR(created_at, 'YYYY-MM') = :period"
                ),
                {"pid": partner_id, "period": period},
            )
        ).scalar()
    finally:
        await session.close()
    revenue = float(usage or 0)
    revenue_cents = int(round(revenue * 100))
    commission_cents = int(round(revenue_cents * partner["rev_share_pct"] / 100))
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO partner_commissions (id, partner_id, period, "
                "revenue_cents, commission_cents) "
                "VALUES (gen_random_uuid(), :pid, :period, :revenue, :commission) "
                "ON CONFLICT (partner_id, period) DO UPDATE SET "
                "revenue_cents = EXCLUDED.revenue_cents, "
                "commission_cents = EXCLUDED.commission_cents"
            ),
            {"pid": partner_id, "period": period, "revenue": revenue_cents, "commission": commission_cents},
        )
        await session.commit()
    finally:
        await session.close()
    return {
        "status": "calculated",
        "partner_id": str(partner_id),
        "period": period,
        "revenue": round(revenue, 4),
        "commission": round(commission_cents / 100, 4),
        "rev_share_pct": partner["rev_share_pct"],
    }


async def list_commissions(partner_id: UUID) -> list[dict]:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT period, revenue_cents, commission_cents, status, created_at "
                    "FROM partner_commissions WHERE partner_id = :pid ORDER BY period DESC"
                ),
                {"pid": partner_id},
            )
        ).fetchall()
    finally:
        await session.close()
    return [
        {
            "period": r.period,
            "revenue": round(int(r.revenue_cents or 0) / 100, 4),
            "commission": round(int(r.commission_cents or 0) / 100, 4),
            "status": r.status,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Subtenants (white-label)
# ---------------------------------------------------------------------------
async def attach_subtenant(partner_id: UUID, organization_id: UUID, commission_share_pct: float) -> dict:
    session = await get_async_session()
    try:
        org_exists = (
            await session.execute(
                text("SELECT 1 FROM organizations WHERE id = :oid"),
                {"oid": organization_id},
            )
        ).fetchone()
        if org_exists is None:
            return {"status": "org_not_found"}
        await session.execute(
            text(
                "INSERT INTO partner_subtenants (id, partner_id, organization_id, "
                "commission_share_pct) VALUES (gen_random_uuid(), :pid, :oid, :share) "
                "ON CONFLICT (partner_id, organization_id) DO NOTHING"
            ),
            {"pid": partner_id, "oid": organization_id, "share": commission_share_pct},
        )
        await session.commit()
        return {"status": "attached", "organization_id": str(organization_id)}
    finally:
        await session.close()


async def list_subtenants(partner_id: UUID) -> list[dict]:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT organization_id, commission_share_pct, created_at "
                    "FROM partner_subtenants WHERE partner_id = :pid ORDER BY created_at DESC"
                ),
                {"pid": partner_id},
            )
        ).fetchall()
    finally:
        await session.close()
    return [
        {
            "organization_id": str(r.organization_id),
            "commission_share_pct": float(r.commission_share_pct),
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


async def set_partner_branding(partner_id: UUID, branding: dict) -> bool:
    session = await get_async_session()
    try:
        result = await session.execute(
            text("UPDATE partners SET branding = :branding WHERE id = :pid"),
            {"branding": json.dumps(branding), "pid": partner_id},
        )
        await session.commit()
        return result.rowcount > 0
    finally:
        await session.close()


# ---------------------------------------------------------------------------
# Integrations catalog
# ---------------------------------------------------------------------------
async def list_integrations() -> list[dict]:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT key, name, category, description, oauth_url_template, "
                    "docs_url, is_active FROM integrations_catalog ORDER BY name"
                )
            )
        ).fetchall()
    finally:
        await session.close()
    return [
        {
            "key": r.key,
            "name": r.name,
            "category": r.category,
            "description": r.description,
            "oauth_url_template": r.oauth_url_template,
            "docs_url": r.docs_url,
            "is_active": bool(r.is_active),
        }
        for r in rows
    ]


async def add_integration(
    key: str, name: str, category: str, description: str | None, oauth_url_template: str | None
) -> dict:
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO integrations_catalog (id, key, name, category, description, "
                "oauth_url_template) VALUES (gen_random_uuid(), :key, :name, :cat, :desc, :oauth) "
                "ON CONFLICT (key) DO UPDATE SET name = EXCLUDED.name, "
                "oauth_url_template = EXCLUDED.oauth_url_template, is_active = true"
            ),
            {"key": key, "name": name, "cat": category, "desc": description, "oauth": oauth_url_template},
        )
        await session.commit()
        return {"status": "saved", "key": key}
    finally:
        await session.close()


async def toggle_integration(key: str, active: bool) -> bool:
    session = await get_async_session()
    try:
        result = await session.execute(
            text("UPDATE integrations_catalog SET is_active = :active WHERE key = :key"),
            {"active": active, "key": key},
        )
        await session.commit()
        return result.rowcount > 0
    finally:
        await session.close()
