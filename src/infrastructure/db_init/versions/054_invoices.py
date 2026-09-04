"""Tenant Self-Service Billing & Invoices v2 — invoices, items, profiles,
payment events.

Revision ID: 054
Revises: 053
Create Date: 2026-09-01
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "054"
down_revision: Union[str, None] = "053"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS invoices (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            provider VARCHAR(30),
            provider_invoice_id VARCHAR(120),
            period_start DATE NOT NULL,
            period_end DATE NOT NULL,
            subtotal_cents INT NOT NULL DEFAULT 0,
            overage_cents INT NOT NULL DEFAULT 0,
            total_cents INT NOT NULL DEFAULT 0,
            currency VARCHAR(3) NOT NULL DEFAULT 'USD',
            status VARCHAR(20) NOT NULL DEFAULT 'issued',
            issued_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            paid_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    # Extensión del schema (invoices v2): número, impuestos, vencimiento,
    # intent de pago y dirección fiscal.
    op.execute(
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS invoice_number VARCHAR(40)"
    )
    op.execute(
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS tax_cents INT NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS due_at TIMESTAMPTZ"
    )
    op.execute(
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS payment_provider VARCHAR(30)"
    )
    op.execute(
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS payment_intent_id VARCHAR(120)"
    )
    op.execute(
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS billing_address JSONB NOT NULL DEFAULT '{}'"
    )
    # El baseline SQL 14 creaba invoices con issued_at nullable sin default;
    # el CREATE TABLE IF NOT EXISTS de arriba no altera esa tabla. Asegurar
    # que toda factura emitida tenga issued_at (idempotente).
    op.execute("ALTER TABLE invoices ALTER COLUMN issued_at SET DEFAULT NOW()")
    op.execute("UPDATE invoices SET issued_at = NOW() WHERE issued_at IS NULL")
    op.execute("ALTER TABLE invoices ALTER COLUMN issued_at SET NOT NULL")
    op.execute(
        "UPDATE invoices SET invoice_number = 'INV-' || substr(replace(id::text, '-', ''), 1, 8) "
        "WHERE invoice_number IS NULL"
    )
    op.execute(
        "ALTER TABLE invoices ALTER COLUMN invoice_number SET NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS invoices_invoice_number_key "
        "ON invoices(invoice_number)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_invoices_org_period "
        "ON invoices(organization_id, period_start DESC)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_invoices_org_period_unique "
        "ON invoices(organization_id, period_start, period_end)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS invoice_items (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            invoice_id UUID NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
            kind VARCHAR(20) NOT NULL DEFAULT 'subscription',
            description VARCHAR(200) NOT NULL,
            quantity DOUBLE PRECISION NOT NULL DEFAULT 1,
            unit_price_cents INT NOT NULL DEFAULT 0,
            amount_cents INT NOT NULL DEFAULT 0,
            meta JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_invoice_items_invoice ON invoice_items(invoice_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS billing_profiles (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL UNIQUE,
            legal_name VARCHAR(200),
            tax_id VARCHAR(60),
            address_line1 VARCHAR(200),
            address_line2 VARCHAR(200),
            city VARCHAR(100),
            region VARCHAR(100),
            postal_code VARCHAR(30),
            country VARCHAR(60),
            default_payment_method VARCHAR(20) NOT NULL DEFAULT 'card',
            card_last4 VARCHAR(4),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS payment_events (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            invoice_id UUID,
            event_type VARCHAR(60) NOT NULL,
            provider VARCHAR(30) NOT NULL DEFAULT 'stripe',
            provider_event_id VARCHAR(120) NOT NULL UNIQUE,
            amount_cents INT NOT NULL DEFAULT 0,
            currency VARCHAR(3) NOT NULL DEFAULT 'USD',
            status VARCHAR(20) NOT NULL DEFAULT 'received',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_payment_events_org_time "
        "ON payment_events(organization_id, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS payment_events")
    op.execute("DROP TABLE IF EXISTS billing_profiles")
    op.execute("DROP TABLE IF EXISTS invoice_items")
    op.execute("DROP TABLE IF EXISTS invoices")
