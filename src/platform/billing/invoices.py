# =============================================================================
# Invoice & Payment Store — facturación y pagos del Billing Platform
# =============================================================================
from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

_TABLES_SQL = (
    """
    CREATE TABLE IF NOT EXISTS invoices (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id UUID NOT NULL,
        provider VARCHAR(30) NOT NULL DEFAULT 'manual',
        provider_invoice_id VARCHAR(200),
        period_start TIMESTAMPTZ NOT NULL,
        period_end TIMESTAMPTZ NOT NULL,
        subtotal_cents BIGINT NOT NULL DEFAULT 0,
        overage_cents BIGINT NOT NULL DEFAULT 0,
        total_cents BIGINT NOT NULL DEFAULT 0,
        currency VARCHAR(3) NOT NULL DEFAULT 'USD',
        status VARCHAR(20) NOT NULL DEFAULT 'draft',
        issued_at TIMESTAMPTZ,
        paid_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (organization_id, period_start, period_end)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS payments (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id UUID NOT NULL,
        provider VARCHAR(30) NOT NULL DEFAULT 'manual',
        provider_payment_id VARCHAR(200),
        invoice_id UUID REFERENCES invoices(id) ON DELETE SET NULL,
        amount_cents BIGINT NOT NULL DEFAULT 0,
        currency VARCHAR(3) NOT NULL DEFAULT 'USD',
        status VARCHAR(20) NOT NULL DEFAULT 'succeeded',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (provider, provider_payment_id)
    )
    """,
)


_PLANS_ALTERS = (
    "ALTER TABLE plans ADD COLUMN IF NOT EXISTS included_storage BIGINT",
    "ALTER TABLE plans ADD COLUMN IF NOT EXISTS max_agents INTEGER",
    "ALTER TABLE plans ADD COLUMN IF NOT EXISTS max_knowledge_bases INTEGER",
    "ALTER TABLE plans ADD COLUMN IF NOT EXISTS max_connectors INTEGER",
    "ALTER TABLE plans ADD COLUMN IF NOT EXISTS overage_request_cost_per_1k DOUBLE PRECISION",
    "ALTER TABLE plans ADD COLUMN IF NOT EXISTS overage_token_cost_per_1k DOUBLE PRECISION",
    "ALTER TABLE plans ADD COLUMN IF NOT EXISTS overage_storage_cost_per_gb DOUBLE PRECISION",
    "ALTER TABLE plans ADD COLUMN IF NOT EXISTS overage_connector_monthly_cents DOUBLE PRECISION",
    "ALTER TABLE plans ADD COLUMN IF NOT EXISTS overage_agent_monthly_cents DOUBLE PRECISION",
    "ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS payment_provider VARCHAR(30) DEFAULT 'manual'",
    "ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS provider_customer_id VARCHAR(200)",
    "ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS provider_subscription_id VARCHAR(200)",
)


async def ensure_billing_tables() -> None:
    session = await get_async_session()
    try:
        for sql in _TABLES_SQL:
            try:
                await session.execute(text(sql))
                await session.commit()
            except Exception:
                await session.rollback()
        for ddl in _PLANS_ALTERS:
            try:
                await session.execute(text(ddl))
                await session.commit()
            except Exception:
                await session.rollback()
        try:
            await session.execute(
                text(
                    "ALTER TABLE subscriptions "
                    "DROP CONSTRAINT IF EXISTS subscriptions_status_check"
                )
            )
            await session.commit()
        except Exception:
            await session.rollback()
        try:
            await session.execute(
                text(
                    "ALTER TABLE subscriptions ADD CONSTRAINT "
                    "subscriptions_status_check CHECK (status IN "
                    "('trialing','active','past_due','canceled','expired',"
                    "'paused','suspended'))"
                )
            )
            await session.commit()
        except Exception:
            await session.rollback()
    finally:
        await session.close()


async def upsert_invoice(
    *,
    organization_id: UUID,
    period_start: datetime,
    period_end: datetime,
    subtotal_cents: int,
    overage_cents: int,
    currency: str = "USD",
    provider: str = "manual",
    provider_invoice_id: str | None = None,
    status: str = "draft",
) -> UUID:
    await ensure_billing_tables()
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO invoices "
                    "(organization_id, provider, provider_invoice_id, "
                    "period_start, period_end, subtotal_cents, "
                    "overage_cents, total_cents, currency, status, issued_at) "
                    "VALUES (:org, :prov, :pid, :ps, :pe, :sub, :ov, :tot, "
                    ":cur, :status, NOW()) "
                    "ON CONFLICT (organization_id, period_start, period_end) "
                    "DO UPDATE SET provider_invoice_id = "
                    "COALESCE(EXCLUDED.provider_invoice_id, "
                    "invoices.provider_invoice_id), "
                    "subtotal_cents = EXCLUDED.subtotal_cents, "
                    "overage_cents = EXCLUDED.overage_cents, "
                    "total_cents = EXCLUDED.total_cents, "
                    "status = EXCLUDED.status "
                    "RETURNING id"
                ),
                {
                    "org": organization_id,
                    "prov": provider,
                    "pid": provider_invoice_id,
                    "ps": period_start,
                    "pe": period_end,
                    "sub": subtotal_cents,
                    "ov": overage_cents,
                    "tot": subtotal_cents + overage_cents,
                    "cur": currency,
                    "status": status,
                },
            )
        ).fetchone()
        await session.commit()
        if row is None:
            raise RuntimeError("Invoice upsert failed")
        return UUID(str(row.id))
    finally:
        await session.close()


async def record_payment(
    *,
    organization_id: UUID,
    provider: str,
    provider_payment_id: str,
    amount_cents: int,
    currency: str = "USD",
    status: str = "succeeded",
    invoice_id: UUID | None = None,
) -> UUID:
    await ensure_billing_tables()
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO payments "
                    "(organization_id, provider, provider_payment_id, "
                    "invoice_id, amount_cents, currency, status) "
                    "VALUES (:org, :prov, :pid, :inv, :amt, :cur, :status) "
                    "ON CONFLICT (provider, provider_payment_id) DO NOTHING "
                    "RETURNING id"
                ),
                {
                    "org": organization_id,
                    "prov": provider,
                    "pid": provider_payment_id,
                    "inv": invoice_id,
                    "amt": amount_cents,
                    "cur": currency,
                    "status": status,
                },
            )
        ).fetchone()
        await session.commit()
        if row is None:
            # Idempotente: ya existía.
            existing = (
                await session.execute(
                    text(
                        "SELECT id FROM payments "
                        "WHERE provider = :prov AND provider_payment_id = :pid"
                    ),
                    {"prov": provider, "pid": provider_payment_id},
                )
            ).fetchone()
            return UUID(str(existing.id)) if existing else uuid4()
        return UUID(str(row.id))
    finally:
        await session.close()


async def mark_invoice_paid(provider_invoice_id: str) -> None:
    await ensure_billing_tables()
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE invoices SET status = 'paid', paid_at = NOW() "
                "WHERE provider_invoice_id = :pid"
            ),
            {"pid": provider_invoice_id},
        )
        await session.commit()
    finally:
        await session.close()


async def get_unpaid_invoices(organization_id: UUID) -> list[dict]:
    await ensure_billing_tables()
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id, provider_invoice_id, total_cents, currency, "
                    "status, period_start, period_end "
                    "FROM invoices WHERE organization_id = :org "
                    "AND status NOT IN ('paid', 'void') "
                    "ORDER BY period_start DESC"
                ),
                {"org": organization_id},
            )
        ).fetchall()
        return [
            {
                "id": str(r.id),
                "provider_invoice_id": r.provider_invoice_id,
                "total_cents": r.total_cents,
                "currency": r.currency,
                "status": r.status,
                "period_start": r.period_start.isoformat(),
                "period_end": r.period_end.isoformat(),
            }
            for r in rows
        ]
    finally:
        await session.close()


async def list_invoices(
    organization_id: UUID, *, limit: int = 50, offset: int = 0
) -> list[dict]:
    await ensure_billing_tables()
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id, provider_invoice_id, period_start, "
                    "period_end, subtotal_cents, overage_cents, total_cents, "
                    "currency, status, issued_at, paid_at "
                    "FROM invoices WHERE organization_id = :org "
                    "ORDER BY period_start DESC LIMIT :limit OFFSET :offset"
                ),
                {"org": organization_id, "limit": limit, "offset": offset},
            )
        ).fetchall()
        return [
            {
                "id": str(r.id),
                "provider_invoice_id": r.provider_invoice_id,
                "period_start": r.period_start.isoformat(),
                "period_end": r.period_end.isoformat(),
                "subtotal_cents": r.subtotal_cents,
                "overage_cents": r.overage_cents,
                "total_cents": r.total_cents,
                "currency": r.currency,
                "status": r.status,
                "issued_at": r.issued_at.isoformat() if r.issued_at else None,
                "paid_at": r.paid_at.isoformat() if r.paid_at else None,
            }
            for r in rows
        ]
    finally:
        await session.close()
