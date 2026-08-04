-- =============================================================================
-- Massive Seed Data — ~1.7M+ registros para pruebas de rendimiento
-- =============================================================================
-- Resultados: 100K productos, 100K ventas, 300K reseñas, 50K clientes
-- Usa generate_series() + LATERAL join con mod correlacionado
-- =============================================================================

-- =============================================================================
-- 1. CATEGORÍAS (500)
-- =============================================================================
INSERT INTO retail.categories (tenant_id, name, slug, description, parent_id, display_order)
SELECT
    '00000000-0000-0000-0000-000000000001',
    'Categoría ' || g,
    'cat-' || g,
    'Descripción de la categoría ' || g,
    CASE WHEN g <= 20 THEN NULL
         ELSE ('c1000000-0000-0000-0000-00000000000' || ((g % 5) + 1))::uuid
    END,
    g
FROM generate_series(1, 500) AS g
ON CONFLICT (tenant_id, slug) DO NOTHING;

-- =============================================================================
-- 2. PRODUCTOS (100,000)
-- =============================================================================
CREATE SEQUENCE IF NOT EXISTS retail.product_seq;

INSERT INTO retail.products (id, tenant_id, category_id, name, slug, description, sku, brand, price, cost, weight_kg, color, warranty_months, tags)
SELECT
    ('f' || LPAD(nextval('retail.product_seq')::text, 31, '0'))::uuid,
    '00000000-0000-0000-0000-000000000001',
    CASE
        WHEN g % 5 = 0 THEN 'c2000000-0000-0000-0000-000000000001'::uuid
        WHEN g % 5 = 1 THEN 'c2000000-0000-0000-0000-000000000002'::uuid
        WHEN g % 5 = 2 THEN 'c2000000-0000-0000-0000-000000000003'::uuid
        WHEN g % 5 = 3 THEN 'c2000000-0000-0000-0000-000000000004'::uuid
        ELSE 'c2000000-0000-0000-0000-000000000006'::uuid
    END,
    'Producto ' || g || ' - ' || (ARRAY['Pro','Max','Lite','Ultra','Plus'])[1 + (g % 5)],
    'producto-' || g,
    'Descripción del producto ' || g || '. Modelo de alto rendimiento.',
    'SKU-' || LPAD(g::text, 8, '0'),
    (ARRAY['ZentTech','ZentHome','ZentSport','TechPro','EcoBrand'])[1 + (g % 5)],
    (random() * 900000 + 10000)::decimal(12,2),
    (random() * 600000 + 5000)::decimal(12,2),
    (random() * 50 + 0.01)::decimal(8,3),
    (ARRAY['Negro','Blanco','Rojo','Azul','Verde','Plata','Dorado'])[1 + (g % 7)],
    (ARRAY[0,6,12,24,36,60])[1 + (g % 6)],
    ARRAY['tag-' || (g % 50), 'tipo-' || (g % 10), 'marca-' || ((g % 5) + 1),
          'gama-' || CASE WHEN g % 3 = 0 THEN 'alta' WHEN g % 3 = 1 THEN 'media' ELSE 'economica' END]
FROM generate_series(1, 100000) AS g
ON CONFLICT (tenant_id, sku) DO NOTHING;

-- =============================================================================
-- 3. INVENTARIO (200,000)
-- =============================================================================
INSERT INTO retail.inventory (tenant_id, product_id, warehouse_location, quantity_available, quantity_reserved, quantity_minimum, last_restock_date, next_restock_eta_days)
SELECT
    '00000000-0000-0000-0000-000000000001',
    p.id,
    wh.name,
    (random() * 500 + 1)::int,
    (random() * 50)::int,
    (random() * 20 + 5)::int,
    NOW() - (random() * 60 || ' days')::interval,
    (random() * 30 + 1)::int
FROM retail.products p
CROSS JOIN (VALUES ('Centro Distribución Santiago'), ('Bodega Valparaíso')) AS wh(name)
WHERE p.sku LIKE 'SKU-%'
ON CONFLICT (tenant_id, product_id, warehouse_location) DO NOTHING;

-- =============================================================================
-- 4. CLIENTES (50,000)
-- =============================================================================
CREATE TABLE IF NOT EXISTS retail.customers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    external_id VARCHAR(100) NOT NULL,
    name VARCHAR(500),
    email VARCHAR(500),
    phone VARCHAR(50),
    city VARCHAR(200),
    region VARCHAR(200),
    country VARCHAR(2) DEFAULT 'CL',
    total_orders INT DEFAULT 0,
    total_spent DECIMAL(14,2) DEFAULT 0,
    loyalty_tier VARCHAR(20) DEFAULT 'bronze',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (tenant_id, external_id)
);

INSERT INTO retail.customers (tenant_id, external_id, name, email, phone, city, region, loyalty_tier, created_at)
SELECT
    '00000000-0000-0000-0000-000000000001',
    'cust-' || LPAD(g::text, 5, '0'),
    'Cliente ' || g || ' ' || (ARRAY['Pérez','González','Rodríguez','López','Martínez'])[1 + (g % 5)],
    'cliente' || g || '@email' || (g % 100) || '.com',
    '+56 9 ' || LPAD(g::text, 8, '0'),
    (ARRAY['Santiago','Valparaíso','Concepción','La Serena','Antofagasta','Temuco'])[1 + (g % 6)],
    (ARRAY['RM','V','VIII','IV','II','IX'])[1 + (g % 6)],
    CASE WHEN g % 10 = 0 THEN 'gold' WHEN g % 5 = 0 THEN 'silver' ELSE 'bronze' END,
    NOW() - ((g % 730) || ' days')::interval
FROM generate_series(1, 50000) AS g
ON CONFLICT (tenant_id, external_id) DO NOTHING;

-- =============================================================================
-- 5. VENTAS (100,000) — usa LATERAL con g%100000 para distribuir productos
-- =============================================================================
TRUNCATE retail.sales CASCADE;

INSERT INTO retail.sales (tenant_id, product_id, customer_id, quantity, unit_price, total_amount, payment_method, order_status, sale_date, channel)
SELECT
    '00000000-0000-0000-0000-000000000001'::uuid,
    p.id,
    'cust-' || LPAD((g % 50000 + 1)::text, 5, '0'),
    (g % 5 + 1),
    ((g * 7 + 10000) % 900000 + 10000)::decimal(12,2),
    ((g % 5 + 1) * ((g * 7 + 10000) % 900000 + 10000))::decimal(14,2),
    (ARRAY['Tarjeta Crédito','Débito','Transferencia','Efectivo'])[1 + (g % 4)],
    CASE WHEN g % 20 = 0 THEN 'cancelled' WHEN g % 50 = 0 THEN 'refunded' ELSE 'completed' END,
    NOW() - ((g % 365) || ' days')::interval,
    (ARRAY['web','app','store'])[1 + (g % 3)]
FROM generate_series(1, 100000) AS g
CROSS JOIN LATERAL (
    SELECT id FROM retail.products WHERE sku = 'SKU-' || LPAD((g % 100000 + 1)::text, 8, '0')
) AS p;

-- =============================================================================
-- 6. RESEÑAS (300,000)
-- =============================================================================
CREATE TABLE IF NOT EXISTS retail.product_reviews (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    product_id UUID NOT NULL REFERENCES retail.products(id),
    customer_id VARCHAR(100),
    rating INT NOT NULL CHECK (rating BETWEEN 1 AND 5),
    title VARCHAR(500),
    comment TEXT,
    is_verified_purchase BOOLEAN DEFAULT false,
    helpful_count INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

TRUNCATE retail.product_reviews CASCADE;

INSERT INTO retail.product_reviews (tenant_id, product_id, customer_id, rating, title, comment, is_verified_purchase, helpful_count, created_at)
SELECT
    '00000000-0000-0000-0000-000000000001'::uuid,
    p.id,
    'cust-' || LPAD((g % 50000 + 1)::text, 5, '0'),
    CASE
        WHEN g % 10 = 0 THEN 1 WHEN g % 10 <= 2 THEN 2
        WHEN g % 10 <= 4 THEN 3 WHEN g % 10 <= 7 THEN 4
        ELSE 5
    END,
    (ARRAY['Excelente','Bueno','Regular','Malo','Me encantó','No me gustó','Lo recomiendo','Cumple','Súper','Increíble'])[1 + (g % 10)],
    'Comentario de prueba número ' || g || '. Generado para pruebas de rendimiento RAG.',
    g % 3 != 0,
    g % 200,
    NOW() - ((g % 365) || ' days')::interval
FROM generate_series(1, 300000) AS g
CROSS JOIN LATERAL (
    SELECT id FROM retail.products WHERE sku = 'SKU-' || LPAD((g % 100000 + 1)::text, 8, '0')
) AS p;

-- =============================================================================
-- 7. VISTA MATERIALIZADA
-- =============================================================================
DROP VIEW IF EXISTS retail.vw_product_catalog;
DROP MATERIALIZED VIEW IF EXISTS retail.vw_product_catalog;

CREATE MATERIALIZED VIEW retail.vw_product_catalog AS
SELECT
    p.id, p.name, p.sku, p.brand, p.price, p.description, p.tags, p.color,
    c.name AS category,
    pc.name AS parent_category,
    COALESCE(s.total_sold, 0) AS units_sold,
    COALESCE(s.total_revenue, 0) AS total_revenue,
    COALESCE(rev.avg_rating, 0) AS avg_rating,
    COALESCE(rev.review_count, 0) AS review_count,
    COALESCE(inv.total_stock, 0) AS in_stock
FROM retail.products p
LEFT JOIN retail.categories c ON p.category_id = c.id
LEFT JOIN retail.categories pc ON c.parent_id = pc.id
LEFT JOIN (
    SELECT product_id, SUM(quantity) AS total_sold, SUM(total_amount) AS total_revenue
    FROM retail.sales WHERE order_status = 'completed' GROUP BY product_id
) s ON p.id = s.product_id
LEFT JOIN (
    SELECT product_id, ROUND(AVG(rating), 1) AS avg_rating, COUNT(*) AS review_count
    FROM retail.product_reviews GROUP BY product_id
) rev ON p.id = rev.product_id
LEFT JOIN (
    SELECT product_id, SUM(quantity_available - quantity_reserved) AS total_stock
    FROM retail.inventory GROUP BY product_id
) inv ON p.id = inv.product_id;

-- =============================================================================
-- Stats
-- =============================================================================
DO $$
BEGIN
    RAISE NOTICE '=== DATA GENERATION COMPLETE ===';
    RAISE NOTICE 'Products: %', (SELECT COUNT(*) FROM retail.products);
    RAISE NOTICE 'Sales: %', (SELECT COUNT(*) FROM retail.sales);
    RAISE NOTICE 'Inventory: %', (SELECT COUNT(*) FROM retail.inventory);
    RAISE NOTICE 'Reviews: %', (SELECT COUNT(*) FROM retail.product_reviews);
    RAISE NOTICE 'Customers: %', (SELECT COUNT(*) FROM retail.customers);
END $$;
