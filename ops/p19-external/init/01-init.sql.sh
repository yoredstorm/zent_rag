#!/bin/sh
set -eu

psql -v ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  -v reader_user="$P19_READER_USER" \
  -v reader_password="$P19_READER_PASSWORD" <<'SQL'
CREATE ROLE :"reader_user" LOGIN PASSWORD :'reader_password';
ALTER ROLE :"reader_user" SET default_transaction_read_only = on;

CREATE SCHEMA IF NOT EXISTS catalog;
CREATE SCHEMA IF NOT EXISTS loyalty;
CREATE SCHEMA IF NOT EXISTS sales;

CREATE TABLE catalog.product_prices (
    sku TEXT NOT NULL,
    product_name TEXT NOT NULL,
    channel TEXT NOT NULL,
    price NUMERIC(12, 2) NOT NULL,
    currency CHAR(3) NOT NULL,
    valid_from DATE NOT NULL,
    valid_to DATE,
    stock INTEGER NOT NULL DEFAULT 0
);

INSERT INTO catalog.product_prices
    (sku, product_name, channel, price, currency, valid_from, valid_to, stock)
VALUES
    ('ARR-001', 'Arroz premium 1 kg', 'retail', 5.00, 'PEN', '2026-01-01', '2026-12-31', 120),
    ('ARR-002', 'Arroz extra 1 kg', 'retail', 6.50, 'PEN', '2026-01-01', '2026-12-31', 80),
    ('ARR-001', 'Arroz premium 1 kg', 'wholesale', 4.50, 'PEN', '2026-01-01', '2026-12-31', 120),
    ('EXP-001', 'Arroz promocional vencido', 'retail', 4.20, 'PEN', '2025-01-01', '2025-12-31', 0),
    ('USD-001', 'Arroz importado', 'retail', 1.50, 'USD', '2026-01-01', '2026-12-31', 10);

CREATE TABLE loyalty.loyalty_balances (
    customer_ref TEXT PRIMARY KEY,
    points_balance INTEGER NOT NULL,
    status TEXT NOT NULL,
    last_activity_at TIMESTAMPTZ NOT NULL
);

INSERT INTO loyalty.loyalty_balances
    (customer_ref, points_balance, status, last_activity_at)
VALUES
    ('CUST-A', 120, 'active', '2026-10-20T10:00:00Z'),
    ('CUST-B', 40, 'active', '2026-10-21T11:00:00Z'),
    ('CUST-C', 0, 'inactive', '2025-01-01T00:00:00Z');

CREATE TABLE sales.orders (
    order_number TEXT PRIMARY KEY,
    customer_ref TEXT NOT NULL,
    status TEXT NOT NULL,
    total NUMERIC(12, 2) NOT NULL,
    currency CHAR(3) NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    shipping_address TEXT
);

INSERT INTO sales.orders
    (order_number, customer_ref, status, total, currency, updated_at, shipping_address)
VALUES
    ('ORD-1001', 'CUST-A', 'shipped', 25.00, 'PEN', '2026-10-30T15:00:00Z', 'Av. Demo 123'),
    ('ORD-1002', 'CUST-A', 'delivered', 12.00, 'PEN', '2026-10-25T09:00:00Z', 'Av. Demo 123'),
    ('ORD-2001', 'CUST-B', 'pending', 6.50, 'PEN', '2026-10-31T08:00:00Z', 'Calle Demo 456');

GRANT USAGE ON SCHEMA catalog, loyalty, sales TO :"reader_user";
GRANT SELECT ON ALL TABLES IN SCHEMA catalog, loyalty, sales TO :"reader_user";
ALTER DEFAULT PRIVILEGES IN SCHEMA catalog, loyalty, sales
    GRANT SELECT ON TABLES TO :"reader_user";
SQL
