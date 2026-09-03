# =============================================================================
# AI Agent Marketplace & Ecosystem v2 — publicación, reviews verificadas,
# revenue sharing con payouts y programas de partner.
# =============================================================================
from __future__ import annotations

import json
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

CATEGORIES = ("general", "support", "sales", "operations", "legal", "hr", "analytics", "engineering")
COMMISSION_PCT = 20.0
PARTNER_LEVELS = {"builder": "constructor", "partner": "partner", "premier": "premier"}


# ---------------------------------------------------------------------------
# Publicación
# ---------------------------------------------------------------------------
async def create_listing(
    publisher_org_id: UUID,
    name: str,
    description: str | None = None,
    category: str = "general",
    pricing_type: str = "free",
    price_cents: int = 0,
    config_template: dict | None = None,
    prompt_template: str | None = None,
) -> dict:
    if category not in CATEGORIES:
        raise ValueError(f"category debe ser uno de {CATEGORIES}")
    if pricing_type not in ("free", "one_time", "subscription"):
        raise ValueError("pricing_type debe ser free|one_time|subscription")
    price = max(0, int(price_cents))
    slug_base = re_slug(name)
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO public_listings (id, publisher_org_id, name, slug, "
                    "description, category, pricing_type, price_cents) "
                    "VALUES (gen_random_uuid(), :oid, :name, :slug, :desc, :cat, "
                    ":ptype, :price) RETURNING id, slug"
                ),
                {
                    "oid": publisher_org_id,
                    "name": name[:150],
                    "slug": f"{slug_base}-{publisher_org_id.hex[:6]}",
                    "desc": description,
                    "cat": category,
                    "ptype": pricing_type,
                    "price": price,
                },
            )
        ).fetchone()
        listing_id = row.id
        await session.execute(
            text(
                "INSERT INTO listing_versions (id, listing_id, version, changelog, "
                "config_template, prompt_template) "
                "VALUES (gen_random_uuid(), :lid, '1.0.0', 'Versión inicial', "
                "CAST(:cfg AS jsonb), :prompt)"
            ),
            {
                "lid": listing_id,
                "cfg": json.dumps(config_template or {}),
                "prompt": prompt_template,
            },
        )
        await session.commit()
    finally:
        await session.close()
    return {"listing_id": str(listing_id), "slug": row.slug}


def re_slug(name: str) -> str:
    import re

    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:40] or "agent"


async def set_listing_status(publisher_org_id: UUID, listing_id: UUID, status: str) -> dict | None:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "UPDATE public_listings SET status = :status, updated_at = NOW() "
                    "WHERE id = :lid AND publisher_org_id = :oid RETURNING status"
                ),
                {"status": status, "lid": listing_id, "oid": publisher_org_id},
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    if row is None:
        return None
    return {"listing_id": str(listing_id), "status": row.status}


async def update_listing(
    publisher_org_id: UUID,
    listing_id: UUID,
    name: str | None = None,
    description: str | None = None,
    category: str | None = None,
    pricing_type: str | None = None,
    price_cents: int | None = None,
    screenshot_urls: list | None = None,
) -> dict | None:
    session = await get_async_session()
    try:
        exists = (
            await session.execute(
                text("SELECT id FROM public_listings WHERE id = :lid AND publisher_org_id = :oid"),
                {"lid": listing_id, "oid": publisher_org_id},
            )
        ).fetchone()
        if exists is None:
            await session.commit()
            return None
        sets = ["updated_at = NOW()"]
        params: dict = {"lid": listing_id}
        if name is not None:
            sets.append("name = :name")
            params["name"] = name[:150]
        if description is not None:
            sets.append("description = :desc")
            params["desc"] = description
        if category is not None:
            sets.append("category = :cat")
            params["cat"] = category
        if pricing_type is not None:
            sets.append("pricing_type = :ptype")
            params["ptype"] = pricing_type
        if price_cents is not None:
            sets.append("price_cents = :price")
            params["price"] = max(0, int(price_cents))
        if screenshot_urls is not None:
            sets.append("screenshot_urls = CAST(:shots AS jsonb)")
            params["shots"] = json.dumps(screenshot_urls[:8])
        await session.execute(
            text(f"UPDATE public_listings SET {', '.join(sets)} WHERE id = :lid"),
            params,
        )
        await session.commit()
    finally:
        await session.close()
    return {"updated": True}


async def new_listing_version(
    publisher_org_id: UUID,
    listing_id: UUID,
    version: str,
    changelog: str | None = None,
    config_template: dict | None = None,
    prompt_template: str | None = None,
) -> dict | None:
    session = await get_async_session()
    try:
        exists = (
            await session.execute(
                text("SELECT id FROM public_listings WHERE id = :lid AND publisher_org_id = :oid"),
                {"lid": listing_id, "oid": publisher_org_id},
            )
        ).fetchone()
        if exists is None:
            await session.commit()
            return None
        await session.execute(
            text(
                "INSERT INTO listing_versions (id, listing_id, version, changelog, "
                "config_template, prompt_template) "
                "VALUES (gen_random_uuid(), :lid, :ver, :log, CAST(:cfg AS jsonb), :prompt)"
            ),
            {
                "lid": listing_id,
                "ver": version[:20],
                "log": changelog,
                "cfg": json.dumps(config_template or {}),
                "prompt": prompt_template,
            },
        )
        await session.execute(
            text(
                "UPDATE public_listings SET version = :ver, updated_at = NOW() "
                "WHERE id = :lid"
            ),
            {"ver": version[:20], "lid": listing_id},
        )
        await session.commit()
    finally:
        await session.close()
    return {"listing_id": str(listing_id), "version": version[:20]}


async def my_listings(organization_id: UUID) -> dict:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT l.id, l.name, l.slug, l.category, l.pricing_type, l.price_cents, "
                    "l.version, l.status, l.installs, l.rating, l.reviews_count "
                    "FROM public_listings l WHERE l.publisher_org_id = :oid "
                    "ORDER BY l.created_at DESC"
                ),
                {"oid": organization_id},
            )
        ).fetchall()
    finally:
        await session.close()
    return {"listings": [_listing(r) for r in rows]}


def _listing(r) -> dict:
    return {
        "id": str(r.id),
        "name": r.name,
        "slug": r.slug,
        "category": r.category,
        "pricing_type": r.pricing_type,
        "price_cents": int(r.price_cents),
        "version": r.version,
        "status": r.status,
        "installs": int(r.installs),
        "rating": float(r.rating),
        "reviews_count": int(r.reviews_count),
    }


# ---------------------------------------------------------------------------
# Catálogo público
# ---------------------------------------------------------------------------
async def public_catalog(category: str | None = None, search: str | None = None, limit: int = 50) -> dict:
    session = await get_async_session()
    try:
        params: dict = {"lim": min(int(limit), 100)}
        where = " WHERE l.status = 'published'"
        if category:
            where += " AND l.category = :cat"
            params["cat"] = category
        if search:
            where += " AND (l.name ILIKE :q OR l.description ILIKE :q OR "
            where += "EXISTS (SELECT 1 FROM jsonb_array_elements_text(l.tags) t WHERE t ILIKE :q))"
            params["q"] = f"%{search}%"
        rows = (
            await session.execute(
                text(
                    "SELECT l.id, l.name, l.slug, l.description, l.category, l.tags, "
                    "l.pricing_type, l.price_cents, l.currency, l.version, l.installs, "
                    "l.rating, l.reviews_count, "
                    "o.name AS publisher_name, p.badge AS publisher_badge "
                    "FROM public_listings l "
                    "LEFT JOIN organizations o ON o.id = l.publisher_org_id "
                    "LEFT JOIN partner_programs p ON p.organization_id = l.publisher_org_id "
                    "AND p.status = 'active'"
                    + where
                    + " ORDER BY l.rating DESC, l.installs DESC LIMIT :lim"
                ),
                params,
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "listings": [
            {
                "id": str(r.id),
                "name": r.name,
                "slug": r.slug,
                "description": r.description,
                "category": r.category,
                "tags": r.tags,
                "pricing_type": r.pricing_type,
                "price_cents": int(r.price_cents),
                "currency": r.currency,
                "version": r.version,
                "installs": int(r.installs),
                "rating": float(r.rating),
                "reviews_count": int(r.reviews_count),
                "publisher_name": r.publisher_name,
                "publisher_badge": r.publisher_badge,
            }
            for r in rows
        ]
    }


async def listing_detail(listing_id: UUID) -> dict | None:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT l.id, l.name, l.slug, l.description, l.category, l.tags, "
                    "l.pricing_type, l.price_cents, l.currency, l.screenshot_urls, "
                    "l.version, l.installs, l.rating, l.reviews_count, l.status, "
                    "l.publisher_org_id, o.name AS publisher_name, p.badge AS publisher_badge "
                    "FROM public_listings l "
                    "LEFT JOIN organizations o ON o.id = l.publisher_org_id "
                    "LEFT JOIN partner_programs p ON p.organization_id = l.publisher_org_id "
                    "AND p.status = 'active' "
                    "WHERE l.id = :lid"
                ),
                {"lid": listing_id},
            )
        ).fetchone()
        if row is None:
            return None
        versions = (
            await session.execute(
                text(
                    "SELECT version, changelog, created_at FROM listing_versions "
                    "WHERE listing_id = :lid ORDER BY created_at DESC"
                ),
                {"lid": listing_id},
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "id": str(row.id),
        "name": row.name,
        "slug": row.slug,
        "description": row.description,
        "category": row.category,
        "tags": row.tags,
        "pricing_type": row.pricing_type,
        "price_cents": int(row.price_cents),
        "currency": row.currency,
        "screenshot_urls": row.screenshot_urls,
        "version": row.version,
        "installs": int(row.installs),
        "rating": float(row.rating),
        "reviews_count": int(row.reviews_count),
        "status": row.status,
        "publisher_org_id": str(row.publisher_org_id),
        "publisher_name": row.publisher_name,
        "publisher_badge": row.publisher_badge,
        "versions": [
            {"version": v.version, "changelog": v.changelog, "created_at": v.created_at.isoformat()}
            for v in versions
        ],
    }


# ---------------------------------------------------------------------------
# Reviews verificadas
# ---------------------------------------------------------------------------
async def add_review(
    organization_id: UUID,
    listing_id: UUID,
    rating: int,
    comment: str | None = None,
) -> dict:
    if not 1 <= int(rating) <= 5:
        raise ValueError("rating debe ser 1-5")
    session = await get_async_session()
    try:
        listing = (
            await session.execute(
                text("SELECT id FROM public_listings WHERE id = :lid AND status = 'published'"),
                {"lid": listing_id},
            )
        ).fetchone()
        if listing is None:
            await session.commit()
            return {"reviewed": False, "reason": "listing no publicado"}
        order = (
            await session.execute(
                text(
                    "SELECT id FROM marketplace_orders WHERE listing_id = :lid "
                    "AND organization_id = :oid AND status = 'paid'"
                ),
                {"lid": listing_id, "oid": organization_id},
            )
        ).fetchone()
        install = (
            await session.execute(
                text(
                    "SELECT mi.id FROM marketplace_installs mi "
                    "JOIN marketplace_agents ma ON ma.id = mi.marketplace_agent_id "
                    "WHERE mi.organization_id = :oid AND ma.slug = "
                    "(SELECT slug FROM public_listings WHERE id = :lid) AND mi.status = 'installed'"
                ),
                {"oid": organization_id, "lid": listing_id},
            )
        ).fetchone()
        verified = order is not None or install is not None
        await session.execute(
            text(
                "INSERT INTO listing_reviews (id, listing_id, organization_id, rating, "
                "comment, verified) VALUES (gen_random_uuid(), :lid, :oid, :rating, "
                ":comment, :verified) "
                "ON CONFLICT (listing_id, organization_id) DO UPDATE SET "
                "rating = :rating, comment = :comment, verified = :verified"
            ),
            {
                "lid": listing_id,
                "oid": organization_id,
                "rating": int(rating),
                "comment": comment,
                "verified": verified,
            },
        )
        await session.execute(
            text(
                "UPDATE public_listings SET rating = COALESCE(("
                "SELECT AVG(r.rating) FROM listing_reviews r WHERE r.listing_id = :lid), 0), "
                "reviews_count = (SELECT COUNT(*) FROM listing_reviews WHERE listing_id = :lid) "
                "WHERE id = :lid"
            ),
            {"lid": listing_id},
        )
        await session.commit()
    finally:
        await session.close()
    return {"reviewed": True, "verified": verified}


async def list_reviews(listing_id: UUID) -> dict:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT r.rating, r.comment, r.verified, r.created_at, o.name AS org_name "
                    "FROM listing_reviews r LEFT JOIN organizations o ON o.id = r.organization_id "
                    "WHERE r.listing_id = :lid ORDER BY r.created_at DESC"
                ),
                {"lid": listing_id},
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "reviews": [
            {
                "rating": int(r.rating),
                "comment": r.comment,
                "verified": bool(r.verified),
                "created_at": r.created_at.isoformat(),
                "org_name": r.org_name,
            }
            for r in rows
        ]
    }


# ---------------------------------------------------------------------------
# Compras + revenue sharing
# ---------------------------------------------------------------------------
async def purchase(organization_id: UUID, listing_id: UUID) -> dict:
    """Compra: crea order con comisión y despliega el agente en el tenant."""
    session = await get_async_session()
    try:
        listing = (
            await session.execute(
                text(
                    "SELECT id, name, slug, pricing_type, price_cents, version "
                    "FROM public_listings WHERE id = :lid AND status = 'published'"
                ),
                {"lid": listing_id},
            )
        ).fetchone()
        if listing is None:
            await session.commit()
            return {"purchased": False, "reason": "listing no publicado"}
        existing = (
            await session.execute(
                text(
                    "SELECT id FROM marketplace_orders WHERE listing_id = :lid "
                    "AND organization_id = :oid AND status = 'paid'"
                ),
                {"lid": listing_id, "oid": organization_id},
            )
        ).fetchone()
        if existing is not None:
            await session.commit()
            return {"purchased": False, "reason": "ya comprado"}
        price = int(listing.price_cents)
        commission = COMMISSION_PCT
        platform_fee = round(price * commission / 100)
        payout = price - platform_fee
        await session.execute(
            text(
                "INSERT INTO marketplace_orders (id, listing_id, organization_id, price_cents, "
                "commission_pct, platform_fee_cents, publisher_payout_cents, status) "
                "VALUES (gen_random_uuid(), :lid, :oid, :price, :comm, :fee, :payout, 'paid')"
            ),
            {
                "lid": listing_id,
                "oid": organization_id,
                "price": price,
                "comm": commission,
                "fee": platform_fee,
                "payout": payout,
            },
        )
        await session.execute(
            text(
                "UPDATE public_listings SET installs = installs + 1, updated_at = NOW() "
                "WHERE id = :lid"
            ),
            {"lid": listing_id},
        )
        await session.commit()
    finally:
        await session.close()

    # Instala el agente en el tenant (config/prompt de la última versión).
    await _install_listing_agent(organization_id, listing_id)
    return {
        "purchased": True,
        "listing": listing.name,
        "price_cents": int(listing.price_cents),
        "platform_fee_cents": platform_fee,
        "publisher_payout_cents": payout,
    }


async def _install_listing_agent(organization_id: UUID, listing_id: UUID) -> None:
    session = await get_async_session()
    try:
        version = (
            await session.execute(
                text(
                    "SELECT config_template, prompt_template, version FROM listing_versions "
                    "WHERE listing_id = :lid ORDER BY created_at DESC LIMIT 1"
                ),
                {"lid": listing_id},
            )
        ).fetchone()
        listing = (
            await session.execute(
                text(
                    "SELECT name, description FROM public_listings WHERE id = :lid"
                ),
                {"lid": listing_id},
            )
        ).fetchone()
        if version is None or listing is None:
            return
        cfg = version.config_template or {}
        await session.execute(
            text(
                "INSERT INTO agents (id, organization_id, name, description, status, "
                "system_prompt, model, config_json) "
                "VALUES (gen_random_uuid(), :oid, :name, :desc, 'configured', :prompt, "
                ":model, CAST(:cfg AS jsonb))"
            ),
            {
                "oid": organization_id,
                "name": f"{listing.name} (marketplace)",
                "desc": listing.description,
                "prompt": version.prompt_template or "",
                "model": cfg.get("model", "gpt-4o-mini"),
                "cfg": json.dumps({"marketplace_listing": str(listing_id), "version": version.version}),
            },
        )
        await session.commit()
    finally:
        await session.close()


async def my_purchases(organization_id: UUID) -> dict:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT o.id, o.price_cents, o.platform_fee_cents, o.publisher_payout_cents, "
                    "o.status, o.created_at, l.name AS listing_name, l.category "
                    "FROM marketplace_orders o JOIN public_listings l ON l.id = o.listing_id "
                    "WHERE o.organization_id = :oid ORDER BY o.created_at DESC"
                ),
                {"oid": organization_id},
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "purchases": [
            {
                "id": str(r.id),
                "listing": r.listing_name,
                "category": r.category,
                "price_cents": int(r.price_cents),
                "platform_fee_cents": int(r.platform_fee_cents),
                "publisher_payout_cents": int(r.publisher_payout_cents),
                "status": r.status,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
    }


# ---------------------------------------------------------------------------
# Payouts
# ---------------------------------------------------------------------------
async def generate_payouts(period_end: date | None = None) -> dict:
    """Genera payouts por publicador de las órdenes del período (default: hoy)."""
    end = period_end or date.today()
    start = end - timedelta(days=30)
    end_next = end + timedelta(days=1)
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT l.publisher_org_id, SUM(o.publisher_payout_cents) AS total "
                    "FROM marketplace_orders o JOIN public_listings l ON l.id = o.listing_id "
                    "WHERE o.created_at >= :start AND o.created_at < :end "
                    "GROUP BY l.publisher_org_id"
                ),
                {"start": start, "end": end_next},
            )
        ).fetchall()
        generated = []
        for r in rows:
            await session.execute(
                text(
                    "INSERT INTO payouts (id, publisher_org_id, amount_cents, period_start, "
                    "period_end) VALUES (gen_random_uuid(), :oid, :amount, :start, :end) "
                    "ON CONFLICT DO NOTHING"
                ),
                {
                    "oid": r.publisher_org_id,
                    "amount": int(r.total),
                    "start": start,
                    "end": end,
                },
            )
            generated.append({"publisher_org_id": str(r.publisher_org_id), "amount_cents": int(r.total)})
        await session.commit()
    finally:
        await session.close()
    return {"period_start": start.isoformat(), "period_end": end.isoformat(), "payouts": generated}


async def list_payouts(organization_id: UUID) -> dict:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id, amount_cents, period_start, period_end, status, created_at, paid_at "
                    "FROM payouts WHERE publisher_org_id = :oid "
                    "ORDER BY period_end DESC"
                ),
                {"oid": organization_id},
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "payouts": [
            {
                "id": str(r.id),
                "amount_cents": int(r.amount_cents),
                "period_start": r.period_start.isoformat(),
                "period_end": r.period_end.isoformat(),
                "status": r.status,
                "created_at": r.created_at.isoformat(),
                "paid_at": r.paid_at.isoformat() if r.paid_at else None,
            }
            for r in rows
        ]
    }


# ---------------------------------------------------------------------------
# Partners
# ---------------------------------------------------------------------------
async def apply_partner(organization_id: UUID, level: str = "builder") -> dict:
    if level not in PARTNER_LEVELS:
        raise ValueError(f"level debe ser uno de {list(PARTNER_LEVELS)}")
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO partner_programs (id, organization_id, level, badge) "
                "VALUES (gen_random_uuid(), :oid, :level, :badge) "
                "ON CONFLICT (organization_id) DO UPDATE SET level = :level, badge = :badge, "
                "status = 'active'"
            ),
            {"oid": organization_id, "level": level, "badge": PARTNER_LEVELS[level]},
        )
        await session.commit()
    finally:
        await session.close()
    return {"level": level, "badge": PARTNER_LEVELS[level], "status": "active"}


async def partner_badges(organization_id: UUID) -> dict:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT level, badge, status, earned_at FROM partner_programs "
                    "WHERE organization_id = :oid"
                ),
                {"oid": organization_id},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        return {"badge": None}
    return {
        "badge": row.badge,
        "level": row.level,
        "status": row.status,
        "earned_at": row.earned_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# Dashboard ecosistema
# ---------------------------------------------------------------------------
async def ecosystem_dashboard() -> dict:
    session = await get_async_session()
    try:
        totals = (
            await session.execute(
                text(
                    "SELECT COUNT(*) AS listings, "
                    "COUNT(*) FILTER (WHERE status = 'published') AS published, "
                    "COALESCE(SUM(installs), 0) AS installs, "
                    "COALESCE(SUM(price_cents), 0) AS revenue_cents "
                    "FROM public_listings"
                )
            )
        ).fetchone()
        orders = (
            await session.execute(
                text(
                    "SELECT COUNT(*) AS orders, COALESCE(SUM(price_cents), 0) AS gmv, "
                    "COALESCE(SUM(platform_fee_cents), 0) AS fees, "
                    "COALESCE(SUM(publisher_payout_cents), 0) AS payouts "
                    "FROM marketplace_orders WHERE status = 'paid'"
                )
            )
        ).fetchone()
        by_category = (
            await session.execute(
                text(
                    "SELECT category, COUNT(*) AS n, SUM(installs) AS installs "
                    "FROM public_listings GROUP BY category ORDER BY installs DESC"
                )
            )
        ).fetchall()
        top_publishers = (
            await session.execute(
                text(
                    "SELECT o.name AS publisher, COUNT(l.id) AS listings, "
                    "COALESCE(SUM(od.publisher_payout_cents), 0) AS earned_cents, "
                    "COALESCE(p.badge, 'sin badge') AS badge "
                    "FROM public_listings l "
                    "JOIN organizations o ON o.id = l.publisher_org_id "
                    "LEFT JOIN marketplace_orders od ON od.listing_id = l.id "
                    "LEFT JOIN partner_programs p ON p.organization_id = l.publisher_org_id "
                    "GROUP BY o.id, p.badge ORDER BY earned_cents DESC LIMIT 10"
                )
            )
        ).fetchall()
        avg_reviews = (
            await session.execute(text("SELECT COALESCE(AVG(rating), 0) FROM listing_reviews"))
        ).scalar()
    finally:
        await session.close()
    return {
        "listings_total": int(totals.listings or 0),
        "listings_published": int(totals.published or 0),
        "total_installs": int(totals.installs or 0),
        "gmv_cents": int(orders.gmv or 0),
        "platform_fees_cents": int(orders.fees or 0),
        "publisher_payouts_cents": int(orders.payouts or 0),
        "orders_count": int(orders.orders or 0),
        "avg_rating": round(float(avg_reviews or 0), 2),
        "by_category": [
            {"category": r.category, "count": int(r.n), "installs": int(r.installs)} for r in by_category
        ],
        "top_publishers": [
            {
                "publisher": r.publisher,
                "listings": int(r.listings),
                "earned_cents": int(r.earned_cents),
                "badge": r.badge,
            }
            for r in top_publishers
        ],
    }
