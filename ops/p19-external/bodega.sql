-- Bodega peruana MVP — 30 productos, stock y pedidos.
-- Ejecutar como p19_admin sobre zent_external_mvp.

CREATE SCHEMA IF NOT EXISTS bodega;

CREATE TABLE IF NOT EXISTS bodega.products (
    sku TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    unit TEXT NOT NULL,
    price NUMERIC(10, 2) NOT NULL,
    currency CHAR(3) NOT NULL DEFAULT 'PEN',
    active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS bodega.stock (
    sku TEXT PRIMARY KEY REFERENCES bodega.products(sku),
    on_hand INTEGER NOT NULL CHECK (on_hand >= 0),
    reserved INTEGER NOT NULL DEFAULT 0 CHECK (reserved >= 0),
    version INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS bodega.stock_movements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_number TEXT NOT NULL,
    sku TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    movement_type TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    before_on_hand INTEGER NOT NULL,
    after_on_hand INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS bodega.stock_reservations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_number TEXT NOT NULL,
    sku TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    status TEXT NOT NULL DEFAULT 'active',
    idempotency_key TEXT NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    committed_at TIMESTAMPTZ,
    released_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS bodega.orders (
    order_number TEXT PRIMARY KEY,
    customer_ref TEXT NOT NULL,
    status TEXT NOT NULL,
    payment_status TEXT NOT NULL,
    total NUMERIC(10, 2) NOT NULL,
    currency CHAR(3) NOT NULL DEFAULT 'PEN',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS bodega.order_items (
    order_number TEXT REFERENCES bodega.orders(order_number),
    sku TEXT REFERENCES bodega.products(sku),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price NUMERIC(10, 2) NOT NULL,
    PRIMARY KEY (order_number, sku)
);

CREATE OR REPLACE VIEW bodega.product_catalog_v AS
SELECT p.sku, p.name, p.category, p.unit, p.price, p.currency,
       s.on_hand, s.reserved, (s.on_hand - s.reserved) AS available
FROM bodega.products p
JOIN bodega.stock s ON s.sku = p.sku
WHERE p.active = TRUE;

INSERT INTO bodega.products (sku, name, category, unit, price, currency) VALUES
('BD-ARROZ-01', 'Arroz extra 1 kg', 'abarrotes', 'kg', 4.80, 'PEN'),
('BD-ARROZ-05', 'Arroz extra 5 kg', 'abarrotes', 'saco', 22.50, 'PEN'),
('BD-AZUCAR-01', 'Azúcar rubia 1 kg', 'abarrotes', 'kg', 4.20, 'PEN'),
('BD-AZUCAR-02', 'Azúcar blanca 1 kg', 'abarrotes', 'kg', 4.50, 'PEN'),
('BD-ACEITE-01', 'Aceite vegetal 1 L', 'abarrotes', 'botella', 8.90, 'PEN'),
('BD-ACEITE-02', 'Aceite de girasol 1 L', 'abarrotes', 'botella', 10.50, 'PEN'),
('BD-FIDEO-01', 'Fideos tallarín 500 g', 'abarrotes', 'paquete', 2.80, 'PEN'),
('BD-FIDEO-02', 'Fideos cabello de ángel 500 g', 'abarrotes', 'paquete', 2.70, 'PEN'),
('BD-ATUN-01', 'Atún en aceite 170 g', 'conservas', 'lata', 6.50, 'PEN'),
('BD-SARDINA-01', 'Sardinas en tomate 170 g', 'conservas', 'lata', 4.20, 'PEN'),
('BD-LECHE-01', 'Leche evaporada 400 g', 'lácteos', 'lata', 4.80, 'PEN'),
('BD-LECHE-02', 'Leche fresca 1 L', 'lácteos', 'botella', 5.90, 'PEN'),
('BD-HUEVO-01', 'Huevos 12 unidades', 'lácteos', 'docena', 10.90, 'PEN'),
('BD-PAN-01', 'Pan francés', 'panadería', 'unidad', 0.50, 'PEN'),
('BD-HARINA-01', 'Harina sin preparar 1 kg', 'abarrotes', 'kg', 5.20, 'PEN'),
('BD-SAL-01', 'Sal de mesa 1 kg', 'abarrotes', 'kg', 1.80, 'PEN'),
('BD-AJI-01', 'Ají amarillo fresco 250 g', 'frescos', 'paquete', 3.50, 'PEN'),
('BD-AJO-01', 'Ajo molido 100 g', 'frescos', 'frasco', 2.90, 'PEN'),
('BD-CEBOLLA-01', 'Cebolla roja 1 kg', 'frescos', 'kg', 2.90, 'PEN'),
('BD-PAPA-01', 'Papa blanca 1 kg', 'frescos', 'kg', 2.40, 'PEN'),
('BD-CAMOTE-01', 'Camote amarillo 1 kg', 'frescos', 'kg', 2.80, 'PEN'),
('BD-TOMATE-01', 'Tomate italiano 1 kg', 'frescos', 'kg', 3.90, 'PEN'),
('BD-ZANAHORIA-01', 'Zanahoria 1 kg', 'frescos', 'kg', 2.70, 'PEN'),
('BD-POLLO-01', 'Pollo entero 1 kg', 'carnes', 'kg', 12.90, 'PEN'),
('BD-CARNE-01', 'Carne de res 1 kg', 'carnes', 'kg', 24.90, 'PEN'),
('BD-PESCADO-01', 'Pescado bonito 1 kg', 'carnes', 'kg', 11.90, 'PEN'),
('BD-LENTEJA-01', 'Lentejas 500 g', 'abarrotes', 'paquete', 3.60, 'PEN'),
('BD-FREJOL-01', 'Frejoles canarios 500 g', 'abarrotes', 'paquete', 4.20, 'PEN'),
('BD-QUINUA-01', 'Quinua 500 g', 'abarrotes', 'paquete', 6.80, 'PEN'),
('BD-AVENA-01', 'Avena 500 g', 'abarrotes', 'paquete', 3.90, 'PEN')
ON CONFLICT (sku) DO NOTHING;

INSERT INTO bodega.stock (sku, on_hand, reserved, version)
SELECT sku, 20 + (row_number() OVER (ORDER BY sku)::int * 7 % 70), 0, 0
FROM bodega.products
ON CONFLICT (sku) DO NOTHING;

INSERT INTO bodega.orders
    (order_number, customer_ref, status, payment_status, total, currency)
VALUES
    ('BOD-1001', 'CUST-A', 'pending_approval', 'pending', 0, 'PEN'),
    ('BOD-1002', 'CUST-B', 'pending_approval', 'pending', 0, 'PEN')
ON CONFLICT (order_number) DO NOTHING;

INSERT INTO bodega.order_items (order_number, sku, quantity, unit_price)
VALUES
    ('BOD-1001', 'BD-ARROZ-01', 2, 4.80),
    ('BOD-1001', 'BD-ACEITE-01', 1, 8.90),
    ('BOD-1002', 'BD-POLLO-01', 1, 12.90)
ON CONFLICT (order_number, sku) DO NOTHING;

UPDATE bodega.orders o
SET total = COALESCE((SELECT SUM(i.quantity * i.unit_price) FROM bodega.order_items i WHERE i.order_number = o.order_number), 0)
WHERE o.order_number IN ('BOD-1001', 'BOD-1002');

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'p19_writer') THEN
        CREATE ROLE p19_writer LOGIN PASSWORD 'p19_writer_dev_2026';
    ELSE
        ALTER ROLE p19_writer WITH LOGIN PASSWORD 'p19_writer_dev_2026';
    END IF;
END $$;

GRANT USAGE ON SCHEMA bodega TO p19_reader, p19_writer;
GRANT SELECT ON ALL TABLES IN SCHEMA bodega TO p19_reader;
GRANT SELECT ON bodega.products, bodega.order_items, bodega.product_catalog_v TO p19_writer;
GRANT SELECT, INSERT, UPDATE ON bodega.stock, bodega.stock_movements, bodega.stock_reservations, bodega.orders TO p19_writer;
