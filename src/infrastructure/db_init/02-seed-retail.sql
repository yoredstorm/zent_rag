-- =============================================================================
-- Seed Data: Tienda Retail "ZentStore" — Datos ricos para pruebas RAG
-- =============================================================================
-- Schema: retail — Módulo independiente. Si mañana es una farmacia o cafetería,
-- se crea otro schema con sus propias tablas. El ingestion engine las descubre
-- automáticamente sin tocar código.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS retail;

-- -----------------------------------------------------------------------------
-- retail.categories — Jerarquía de categorías de producto
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS retail.categories (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(255) NOT NULL,
    description TEXT,
    parent_id UUID REFERENCES retail.categories(id),
    display_order INT DEFAULT 0,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (tenant_id, slug)
);

INSERT INTO retail.categories (id, tenant_id, name, slug, description, display_order) VALUES
('c1000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000001', 'Electrónica', 'electronica', 'Dispositivos electrónicos, gadgets y accesorios tecnológicos', 1),
('c1000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-000000000001', 'Hogar y Cocina', 'hogar-cocina', 'Artículos para el hogar, cocina y decoración', 2),
('c1000000-0000-0000-0000-000000000003', '00000000-0000-0000-0000-000000000001', 'Deportes y Aire Libre', 'deportes-aire-libre', 'Equipamiento deportivo, ropa y accesorios outdoor', 3),
('c1000000-0000-0000-0000-000000000004', '00000000-0000-0000-0000-000000000001', 'Libros y Papelería', 'libros-papeleria', 'Libros, eBooks y artículos de papelería', 4),
('c1000000-0000-0000-0000-000000000005', '00000000-0000-0000-0000-000000000001', 'Juguetes y Juegos', 'juguetes-juegos', 'Juguetes educativos, juegos de mesa y videojuegos', 5)
ON CONFLICT (tenant_id, slug) DO NOTHING;

-- Subcategorías
INSERT INTO retail.categories (id, tenant_id, name, slug, description, parent_id, display_order) VALUES
('c2000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000001', 'Smartphones', 'smartphones', 'Teléfonos inteligentes y accesorios', 'c1000000-0000-0000-0000-000000000001', 1),
('c2000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-000000000001', 'Laptops', 'laptops', 'Computadores portátiles y accesorios', 'c1000000-0000-0000-0000-000000000001', 2),
('c2000000-0000-0000-0000-000000000003', '00000000-0000-0000-0000-000000000001', 'Audio', 'audio', 'Audífonos, parlantes y equipos de sonido', 'c1000000-0000-0000-0000-000000000001', 3),
('c2000000-0000-0000-0000-000000000004', '00000000-0000-0000-0000-000000000001', 'Muebles', 'muebles', 'Muebles para hogar y oficina', 'c1000000-0000-0000-0000-000000000002', 1),
('c2000000-0000-0000-0000-000000000005', '00000000-0000-0000-0000-000000000001', 'Electrodomésticos', 'electrodomesticos', 'Electrodomésticos de cocina y limpieza', 'c1000000-0000-0000-0000-000000000002', 2),
('c2000000-0000-0000-0000-000000000006', '00000000-0000-0000-0000-000000000001', 'Running', 'running', 'Zapatillas y ropa para correr', 'c1000000-0000-0000-0000-000000000003', 1),
('c2000000-0000-0000-0000-000000000007', '00000000-0000-0000-0000-000000000001', 'Fitness', 'fitness', 'Equipamiento de gimnasio y accesorios', 'c1000000-0000-0000-0000-000000000003', 2)
ON CONFLICT (tenant_id, slug) DO NOTHING;

-- -----------------------------------------------------------------------------
-- retail.products — Catálogo de productos
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS retail.products (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    category_id UUID REFERENCES retail.categories(id),
    name VARCHAR(500) NOT NULL,
    slug VARCHAR(500) NOT NULL,
    description TEXT,
    sku VARCHAR(100) NOT NULL,
    brand VARCHAR(200),
    price DECIMAL(12,2) NOT NULL,
    cost DECIMAL(12,2),
    currency VARCHAR(3) DEFAULT 'CLP',
    weight_kg DECIMAL(8,3),
    dimensions_cm VARCHAR(100),
    color VARCHAR(100),
    material VARCHAR(200),
    warranty_months INT DEFAULT 0,
    tags TEXT[],
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (tenant_id, sku)
);

INSERT INTO retail.products (id, tenant_id, category_id, name, slug, description, sku, brand, price, cost, weight_kg, color, warranty_months, tags) VALUES
-- Smartphones
('f1000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000001', 'c2000000-0000-0000-0000-000000000001', 'ZentPhone X1 128GB', 'zentphone-x1-128gb', 'Smartphone premium con pantalla AMOLED de 6.7 pulgadas, procesador Octa-Core 3.2GHz, 8GB RAM, 128GB almacenamiento. Cámara triple de 108MP + 12MP ultra wide + 5MP macro. Batería 5000mAh con carga rápida 65W. Resistente al agua IP68.', 'ZNT-X1-128-BLK', 'ZentTech', 599990, 420000, 0.189, 'Negro Midnight', 24, ARRAY['smartphone','5g','amoled','camara','resistente-agua']),
('f1000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-000000000001', 'c2000000-0000-0000-0000-000000000001', 'ZentPhone X1 256GB', 'zentphone-x1-256gb', 'Versión de 256GB del ZentPhone X1. Mismas especificaciones premium.', 'ZNT-X1-256-BLK', 'ZentTech', 699990, 490000, 0.189, 'Negro Midnight', 24, ARRAY['smartphone','5g','amoled','256gb']),
('f1000000-0000-0000-0000-000000000003', '00000000-0000-0000-0000-000000000001', 'c2000000-0000-0000-0000-000000000001', 'Samsung Galaxy S25 Ultra', 'samsung-galaxy-s25-ultra', 'El smartphone más potente de Samsung. Pantalla Dynamic AMOLED 2X de 6.9 pulgadas, S Pen integrado, cámara de 200MP con zoom espacial 100x. Procesador Snapdragon 8 Gen 4, 12GB RAM.', 'SAM-S25U-512-TIT', 'Samsung', 1249990, 950000, 0.218, 'Titanio', 24, ARRAY['samsung','premium','spen','200mp','ai']),
-- Laptops
('f1000000-0000-0000-0000-000000000004', '00000000-0000-0000-0000-000000000001', 'c2000000-0000-0000-0000-000000000002', 'MacBook Pro M4 14"', 'macbook-pro-m4-14', 'Apple MacBook Pro con chip M4, 14 pulgadas Liquid Retina XDR, 16GB RAM unificada, 512GB SSD. Rendimiento extremo para profesionales creativos. Hasta 22 horas de batería.', 'APL-MBP14-M4-16-512', 'Apple', 1899990, 1550000, 1.55, 'Gris Espacial', 12, ARRAY['apple','macbook','m4','profesional','creativo']),
('f1000000-0000-0000-0000-000000000005', '00000000-0000-0000-0000-000000000001', 'c2000000-0000-0000-0000-000000000002', 'Dell XPS 15', 'dell-xps-15', 'Laptop premium Dell XPS 15. Intel Core i9-14900H, 32GB DDR5, 1TB NVMe SSD, NVIDIA RTX 4070, pantalla OLED 3.5K táctil de 15.6". Windows 11 Pro.', 'DELL-XPS15-i9-32-1TB', 'Dell', 1599990, 1280000, 1.86, 'Plata', 24, ARRAY['dell','xps','i9','rtx4070','oled']),
('f1000000-0000-0000-0000-000000000006', '00000000-0000-0000-0000-000000000001', 'c2000000-0000-0000-0000-000000000002', 'Lenovo ThinkPad X1 Carbon Gen 12', 'thinkpad-x1-carbon-gen12', 'Laptop empresarial ultraligera. Intel Core Ultra 7 155H, 16GB LPDDR5x, 512GB SSD, pantalla 14" 2.8K OLED, menos de 1kg.', 'LNV-X1C12-U7-16-512', 'Lenovo', 1399990, 1100000, 0.98, 'Negro', 36, ARRAY['lenovo','thinkpad','empresarial','ultraligero','oled']),
-- Audio
('f1000000-0000-0000-0000-000000000007', '00000000-0000-0000-0000-000000000001', 'c2000000-0000-0000-0000-000000000003', 'Sony WH-1000XM6', 'sony-wh1000xm6', 'Audífonos inalámbricos con cancelación de ruido activa líder en la industria. 40 horas de batería, códec LDAC, multipunto Bluetooth 5.4, diseño plegable.', 'SNY-WH1000XM6-BLK', 'Sony', 349990, 240000, 0.250, 'Negro', 12, ARRAY['sony','audifonos','cancelacion-ruido','bluetooth','premium']),
('f1000000-0000-0000-0000-000000000008', '00000000-0000-0000-0000-000000000001', 'c2000000-0000-0000-0000-000000000003', 'AirPods Pro 2', 'airpods-pro-2', 'Audífonos in-ear con cancelación activa de ruido adaptativa. Chip H2, audio espacial personalizado, estuche MagSafe con Find My. Resistencia IPX4.', 'APL-AIRPODSPRO2', 'Apple', 249990, 190000, 0.005, 'Blanco', 12, ARRAY['apple','airpods','in-ear','cancelacion-ruido','magsafe']),
-- Muebles
('f1000000-0000-0000-0000-000000000009', '00000000-0000-0000-0000-000000000001', 'c2000000-0000-0000-0000-000000000004', 'Escritorio Eléctrico Ajustable Pro', 'escritorio-electrico-ajustable-pro', 'Escritorio standing desk con motor eléctrico dual. Altura ajustable 62-128cm, tablero 160x80cm en madera de nogal. Panel de control digital con 4 memorias. Capacidad 120kg.', 'ZNT-DESKPRO-160-NOG', 'ZentHome', 499990, 350000, 28.5, 'Nogal', 24, ARRAY['escritorio','standing-desk','electrico','oficina','ergonomico']),
('f1000000-0000-0000-0000-000000000010', '00000000-0000-0000-0000-000000000001', 'c2000000-0000-0000-0000-000000000004', 'Silla Ergonómica Executive', 'silla-ergonomica-executive', 'Silla de oficina ergonómica con soporte lumbar ajustable, reposacabezas 4D, reposabrazos 3D, respaldo mesh transpirable. Base de aluminio pulido, ruedas silenciosas.', 'ZNT-CHAIR-EXEC-BLK', 'ZentHome', 349990, 220000, 18.2, 'Negro', 60, ARRAY['silla','ergonomica','oficina','lumbar','mesh']),
-- Electrodomésticos
('f1000000-0000-0000-0000-000000000011', '00000000-0000-0000-0000-000000000001', 'c2000000-0000-0000-0000-000000000005', 'Robot Aspirador SmartClean 9000', 'robot-aspirador-smartclean-9000', 'Robot aspirador y trapeador inteligente con LiDAR. Mapeo 3D, navegación por habitaciones, 5000Pa de succión. Base auto-vaciado con bolsa de 3L. App + Alexa + Google Home.', 'ZNT-SC9000-WHT', 'ZentHome', 399990, 280000, 3.6, 'Blanco', 12, ARRAY['robot','aspirador','trapeador','smart','lidar','auto-vaciado']),
('f1000000-0000-0000-0000-000000000012', '00000000-0000-0000-0000-000000000001', 'c2000000-0000-0000-0000-000000000005', 'Cafetera Espresso Automática Barista Plus', 'cafetera-barista-plus', 'Cafetera superautomática con molinillo de acero cónico integrado, 15 bares de presión. 8 recetas programables, espumador de leche automático. Depósito 2L agua + 500g granos.', 'ZNT-CAFE-BAR-BLK', 'ZentHome', 699990, 480000, 9.8, 'Negro', 24, ARRAY['cafetera','espresso','automatica','molinillo','capuccino']),
-- Deportes - Running
('f1000000-0000-0000-0000-000000000013', '00000000-0000-0000-0000-000000000001', 'c2000000-0000-0000-0000-000000000006', 'Zapatillas UltraBoost Pro Runner', 'ultraboost-pro-runner', 'Zapatillas de running de alto rendimiento. Mediasuela Boost con retorno de energía del 85%, upper Primeknit+ transpirable. Drop 10mm, peso 260g (talla 42). Suela Continental para máximo agarre.', 'ZNT-RUN-UBP-BLU', 'ZentSport', 129990, 85000, 0.260, 'Azul/Blanco', 6, ARRAY['zapatillas','running','boost','transpirable','agarre']),
('f1000000-0000-0000-0000-000000000014', '00000000-0000-0000-0000-000000000001', 'c2000000-0000-0000-0000-000000000006', 'Reloj Deportivo GPS Forerunner 975', 'forerunner-975', 'Reloj GPS multideporte con pantalla AMOLED táctil de 1.4". 50 modos deportivos, frecuencia cardíaca por muñeca, VO2 max, training load, mapas TopoActive. Batería 16 días modo smartwatch, 40h GPS.', 'ZNT-FR975-BLK', 'ZentSport', 499990, 350000, 0.052, 'Negro', 12, ARRAY['reloj','gps','running','deportivo','frecuencia-cardiaca']),
-- Fitness
('f1000000-0000-0000-0000-000000000015', '00000000-0000-0000-0000-000000000001', 'c2000000-0000-0000-0000-000000000007', 'Bandas Elásticas Set Profesional 5 niveles', 'bandas-elasticas-pro', 'Set de 5 bandas de resistencia (5-15kg, 10-20kg, 15-25kg, 20-35kg, 25-50kg). Fabricadas en látex natural 100%, anti-rotura. Incluye 2 asas acolchadas, 2 tobilleras, anclaje de puerta y bolsa de transporte.', 'ZNT-BANDS-PRO', 'ZentSport', 29990, 15000, 0.85, 'Multicolor', 3, ARRAY['bandas','resistencia','fitness','ejercicio','casa']),
('f1000000-0000-0000-0000-000000000016', '00000000-0000-0000-0000-000000000001', 'c2000000-0000-0000-0000-000000000007', 'Mancuernas Ajustables 2-24kg Par', 'mancuernas-ajustables-par', 'Par de mancuernas con sistema de ajuste rápido por dial. 15 niveles de peso (2-24kg cada una). Reemplaza 30 pares de mancuernas tradicionales. Base con bandeja de almacenamiento incluida.', 'ZNT-DUMB-24', 'ZentSport', 249990, 160000, 48.0, 'Negro/Rojo', 24, ARRAY['mancuernas','ajustables','pesas','gimnasio','casa']),
-- Libros
('f1000000-0000-0000-0000-000000000017', '00000000-0000-0000-0000-000000000001', 'c1000000-0000-0000-0000-000000000004', 'Clean Architecture — Robert C. Martin', 'clean-architecture-martin', 'Guía esencial sobre arquitectura de software. Principios SOLID, diseño por capas, inversión de dependencias. Un clásico para desarrolladores senior. Tapa blanda, 432 páginas.', 'BK-CLEAN-ARCH', 'Pearson', 45990, 28000, 0.68, NULL, 0, ARRAY['software','arquitectura','solid','clean-code','programacion']),
('f1000000-0000-0000-0000-000000000018', '00000000-0000-0000-0000-000000000001', 'c1000000-0000-0000-0000-000000000004', 'Designing Data-Intensive Applications', 'designing-data-intensive-apps', 'Referencia definitiva sobre sistemas de datos distribuidos. Bases de datos, streams, batch processing, consistencia, escalabilidad. Martin Kleppmann. Tapa blanda, 616 páginas.', 'BK-DDIA', 'OReilly', 55990, 35000, 0.85, NULL, 0, ARRAY['datos','distribuidos','bases-de-datos','escalabilidad','streams']),
-- Juguetes
('f1000000-0000-0000-0000-000000000019', '00000000-0000-0000-0000-000000000001', 'c1000000-0000-0000-0000-000000000005', 'LEGO Architecture — Tokyo Skyline', 'lego-tokyo-skyline', 'Set LEGO Architecture de la ciudad de Tokio. 547 piezas. Incluye el Tokyo Tower, puente arcoíris, pagoda y cerezos en flor. Edad recomendada: 12+. Dimensiones: 28x10x27cm.', 'LGO-TOKYO', 'LEGO', 69990, 45000, 0.82, NULL, 24, ARRAY['lego','arquitectura','tokio','construccion','coleccion']),
('f1000000-0000-0000-0000-000000000020', '00000000-0000-0000-0000-000000000001', 'c1000000-0000-0000-0000-000000000005', 'Catan — Juego de Mesa', 'catan-juego-mesa', 'El clásico juego de estrategia y negociación. De 3 a 4 jugadores, duración 60-90 min. Edad recomendada: 10+. Construye caminos, poblados y ciudades comerciando recursos.', 'BG-CATAN', 'Devir', 44990, 28000, 1.2, NULL, 0, ARRAY['juego-mesa','estrategia','negociacion','familiar','catan'])
ON CONFLICT (tenant_id, sku) DO NOTHING;

-- -----------------------------------------------------------------------------
-- retail.inventory — Stock por producto
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS retail.inventory (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    product_id UUID NOT NULL REFERENCES retail.products(id),
    warehouse_location VARCHAR(200),
    quantity_available INT NOT NULL DEFAULT 0,
    quantity_reserved INT DEFAULT 0,
    quantity_minimum INT DEFAULT 5,
    last_restock_date TIMESTAMPTZ,
    next_restock_eta_days INT,
    is_in_stock BOOLEAN GENERATED ALWAYS AS (quantity_available > 0) STORED,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (tenant_id, product_id, warehouse_location)
);

INSERT INTO retail.inventory (tenant_id, product_id, warehouse_location, quantity_available, quantity_reserved, quantity_minimum, last_restock_date, next_restock_eta_days) VALUES
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000001', 'Centro Distribución Santiago', 245, 12, 20, '2026-07-15', 7),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000001', 'Bodega Valparaíso', 89, 3, 10, '2026-07-20', 14),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000002', 'Centro Distribución Santiago', 120, 25, 15, '2026-07-18', 10),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000003', 'Centro Distribución Santiago', 67, 8, 10, '2026-07-10', 21),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000004', 'Centro Distribución Santiago', 34, 5, 5, '2026-07-25', 30),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000005', 'Centro Distribución Santiago', 18, 2, 5, '2026-07-22', 14),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000006', 'Centro Distribución Santiago', 42, 1, 5, '2026-07-28', 7),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000007', 'Centro Distribución Santiago', 156, 10, 15, '2026-07-12', 5),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000008', 'Centro Distribución Santiago', 203, 18, 20, '2026-07-14', 3),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000009', 'Centro Distribución Santiago', 12, 4, 5, '2026-07-01', 14),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000010', 'Centro Distribución Santiago', 28, 6, 5, '2026-07-08', 21),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000011', 'Centro Distribución Santiago', 0, 0, 10, '2026-07-01', 30),  -- Sin stock
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000012', 'Centro Distribución Santiago', 45, 7, 5, '2026-07-20', 14),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000013', 'Centro Distribución Santiago', 312, 45, 30, '2026-07-10', 7),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000014', 'Centro Distribución Santiago', 89, 3, 10, '2026-07-18', 14),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000015', 'Centro Distribución Santiago', 534, 22, 50, '2026-07-05', 5),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000016', 'Centro Distribución Santiago', 23, 8, 5, '2026-07-25', 21),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000017', 'Centro Distribución Santiago', 178, 5, 15, '2026-07-08', 7),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000018', 'Centro Distribución Santiago', 92, 12, 10, '2026-07-15', 10),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000019', 'Centro Distribución Santiago', 56, 0, 5, '2026-07-10', 14),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000020', 'Centro Distribución Santiago', 134, 7, 10, '2026-07-05', 7);

-- -----------------------------------------------------------------------------
-- retail.sales — Historial de ventas
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS retail.sales (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    product_id UUID NOT NULL REFERENCES retail.products(id),
    customer_id VARCHAR(100),
    quantity INT NOT NULL DEFAULT 1,
    unit_price DECIMAL(12,2) NOT NULL,
    total_amount DECIMAL(14,2) NOT NULL,
    payment_method VARCHAR(50),
    order_status VARCHAR(30) DEFAULT 'completed',
    sale_date TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    channel VARCHAR(50) DEFAULT 'web'
);

INSERT INTO retail.sales (tenant_id, product_id, customer_id, quantity, unit_price, total_amount, payment_method, sale_date, channel) VALUES
-- Productos más vendidos (ZentPhone X1 128GB)
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000001', 'cust-001', 1, 599990, 599990, 'Tarjeta Crédito', '2026-07-01 10:23:00', 'web'),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000001', 'cust-015', 2, 599990, 1199980, 'Transferencia', '2026-07-03 14:15:00', 'app'),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000001', 'cust-022', 1, 599990, 599990, 'Débito', '2026-07-05 09:45:00', 'web'),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000001', 'cust-031', 1, 599990, 599990, 'Tarjeta Crédito', '2026-07-08 16:30:00', 'web'),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000001', 'cust-042', 3, 599990, 1799970, 'Transferencia', '2026-07-12 11:10:00', 'app'),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000001', 'cust-048', 1, 599990, 599990, 'Tarjeta Crédito', '2026-07-15 13:22:00', 'web'),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000001', 'cust-055', 2, 599990, 1199980, 'Débito', '2026-07-18 10:05:00', 'web'),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000001', 'cust-061', 1, 599990, 599990, 'Tarjeta Crédito', '2026-07-22 08:40:00', 'app'),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000001', 'cust-073', 1, 599990, 599990, 'Transferencia', '2026-07-25 17:55:00', 'web'),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000001', 'cust-078', 2, 599990, 1199980, 'Tarjeta Crédito', '2026-07-27 12:30:00', 'web'),
-- AirPods Pro 2 (segundo más vendido)
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000008', 'cust-003', 1, 249990, 249990, 'Débito', '2026-07-02 09:15:00', 'web'),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000008', 'cust-012', 1, 249990, 249990, 'Tarjeta Crédito', '2026-07-04 15:45:00', 'web'),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000008', 'cust-019', 2, 249990, 499980, 'Transferencia', '2026-07-07 11:30:00', 'app'),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000008', 'cust-025', 1, 249990, 249990, 'Tarjeta Crédito', '2026-07-09 14:20:00', 'web'),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000008', 'cust-035', 1, 249990, 249990, 'Débito', '2026-07-13 10:10:00', 'web'),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000008', 'cust-044', 1, 249990, 249990, 'Tarjeta Crédito', '2026-07-16 16:00:00', 'app'),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000008', 'cust-052', 3, 249990, 749970, 'Transferencia', '2026-07-20 09:55:00', 'web'),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000008', 'cust-067', 1, 249990, 249990, 'Tarjeta Crédito', '2026-07-24 13:40:00', 'web'),
-- UltraBoost Pro Runner (tercero más vendido)
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000013', 'cust-006', 1, 129990, 129990, 'Débito', '2026-07-02 12:00:00', 'web'),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000013', 'cust-011', 1, 129990, 129990, 'Tarjeta Crédito', '2026-07-05 10:30:00', 'app'),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000013', 'cust-018', 2, 129990, 259980, 'Transferencia', '2026-07-08 08:20:00', 'web'),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000013', 'cust-029', 1, 129990, 129990, 'Débito', '2026-07-11 14:45:00', 'web'),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000013', 'cust-038', 1, 129990, 129990, 'Tarjeta Crédito', '2026-07-14 11:15:00', 'app'),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000013', 'cust-047', 2, 129990, 259980, 'Tarjeta Crédito', '2026-07-19 16:30:00', 'web'),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000013', 'cust-058', 1, 129990, 129990, 'Débito', '2026-07-23 09:10:00', 'web'),
-- Bandas Elásticas (producto más vendido por unidades)
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000015', 'cust-002', 2, 29990, 59980, 'Débito', '2026-07-01 08:30:00', 'web'),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000015', 'cust-007', 1, 29990, 29990, 'Tarjeta Crédito', '2026-07-02 17:00:00', 'web'),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000015', 'cust-009', 3, 29990, 89970, 'Transferencia', '2026-07-03 10:45:00', 'app'),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000015', 'cust-014', 1, 29990, 29990, 'Débito', '2026-07-05 13:20:00', 'web'),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000015', 'cust-021', 1, 29990, 29990, 'Tarjeta Crédito', '2026-07-07 15:10:00', 'web'),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000015', 'cust-028', 2, 29990, 59980, 'Débito', '2026-07-10 09:35:00', 'app'),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000015', 'cust-033', 1, 29990, 29990, 'Tarjeta Crédito', '2026-07-12 11:50:00', 'web'),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000015', 'cust-037', 5, 29990, 149950, 'Transferencia', '2026-07-14 14:25:00', 'web'),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000015', 'cust-041', 1, 29990, 29990, 'Débito', '2026-07-17 08:15:00', 'web'),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000015', 'cust-046', 2, 29990, 59980, 'Tarjeta Crédito', '2026-07-19 16:40:00', 'app'),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000015', 'cust-053', 1, 29990, 29990, 'Débito', '2026-07-22 10:05:00', 'web'),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000015', 'cust-064', 3, 29990, 89970, 'Tarjeta Crédito', '2026-07-25 12:30:00', 'web'),
-- MacBook Pro M4
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000004', 'cust-005', 1, 1899990, 1899990, 'Tarjeta Crédito', '2026-07-06 11:30:00', 'web'),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000004', 'cust-017', 1, 1899990, 1899990, 'Transferencia', '2026-07-14 09:20:00', 'app'),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000004', 'cust-036', 1, 1899990, 1899990, 'Tarjeta Crédito', '2026-07-21 15:45:00', 'web'),
-- Otros productos
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000007', 'cust-004', 1, 349990, 349990, 'Tarjeta Crédito', '2026-07-03 10:00:00', 'web'),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000007', 'cust-023', 1, 349990, 349990, 'Débito', '2026-07-11 13:50:00', 'app'),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000007', 'cust-040', 1, 349990, 349990, 'Tarjeta Crédito', '2026-07-17 11:25:00', 'web'),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000007', 'cust-059', 1, 349990, 349990, 'Transferencia', '2026-07-26 14:10:00', 'web'),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000012', 'cust-008', 1, 699990, 699990, 'Tarjeta Crédito', '2026-07-04 10:30:00', 'web'),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000012', 'cust-027', 1, 699990, 699990, 'Transferencia', '2026-07-12 15:00:00', 'app'),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000020', 'cust-010', 1, 44990, 44990, 'Débito', '2026-07-03 16:20:00', 'web'),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000020', 'cust-016', 1, 44990, 44990, 'Tarjeta Crédito', '2026-07-09 12:10:00', 'web'),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000020', 'cust-026', 2, 44990, 89980, 'Débito', '2026-07-15 09:55:00', 'app'),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000020', 'cust-039', 1, 44990, 44990, 'Tarjeta Crédito', '2026-07-20 14:30:00', 'web'),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000020', 'cust-051', 1, 44990, 44990, 'Débito', '2026-07-22 11:00:00', 'web'),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000017', 'cust-013', 1, 45990, 45990, 'Débito', '2026-07-06 10:00:00', 'web'),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000017', 'cust-032', 1, 45990, 45990, 'Tarjeta Crédito', '2026-07-13 08:45:00', 'app'),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000017', 'cust-049', 1, 45990, 45990, 'Débito', '2026-07-18 15:30:00', 'web'),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000017', 'cust-063', 1, 45990, 45990, 'Tarjeta Crédito', '2026-07-24 10:20:00', 'web');

-- -----------------------------------------------------------------------------
-- retail.delivery_options — Métodos de envío
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS retail.delivery_options (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    carrier VARCHAR(100),
    estimated_days_min INT NOT NULL,
    estimated_days_max INT NOT NULL,
    cost DECIMAL(10,2) NOT NULL DEFAULT 0,
    free_over_amount DECIMAL(12,2),
    regions TEXT[],
    is_active BOOLEAN DEFAULT true,
    UNIQUE (tenant_id, name)
);

INSERT INTO retail.delivery_options (tenant_id, name, carrier, estimated_days_min, estimated_days_max, cost, free_over_amount, regions) VALUES
('00000000-0000-0000-0000-000000000001', 'Envío Express AM', 'ZentLogistics', 1, 1, 4990, 150000, ARRAY['RM - Santiago', 'RM - Providencia', 'RM - Las Condes', 'RM - Vitacura', 'RM - Ñuñoa', 'RM - La Florida']),
('00000000-0000-0000-0000-000000000001', 'Envío Express', 'ZentLogistics', 1, 2, 3990, 100000, ARRAY['RM - Santiago', 'RM - Resto', 'V - Valparaíso', 'V - Viña del Mar']),
('00000000-0000-0000-0000-000000000001', 'Envío Estándar', 'Chilexpress', 3, 5, 2990, 50000, ARRAY['RM', 'V', 'VI', 'VII', 'VIII', 'XVI']),
('00000000-0000-0000-0000-000000000001', 'Envío Nacional', 'Chilexpress', 5, 10, 4990, 80000, ARRAY['Arica', 'Tarapacá', 'Antofagasta', 'Atacama', 'Coquimbo', 'Los Lagos', 'Aysén', 'Magallanes']),
('00000000-0000-0000-0000-000000000001', 'Retiro en Tienda', 'Pickup', 0, 2, 0, NULL, ARRAY['RM - Santiago Centro', 'RM - Costanera Center', 'V - Viña del Mar'])
ON CONFLICT (tenant_id, name) DO NOTHING;

-- -----------------------------------------------------------------------------
-- retail.product_reviews — Reseñas de productos
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS retail.product_reviews (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    product_id UUID NOT NULL REFERENCES retail.products(id),
    customer_id VARCHAR(100),
    rating INT NOT NULL CHECK (rating BETWEEN 1 AND 5),
    title VARCHAR(300),
    comment TEXT,
    is_verified_purchase BOOLEAN DEFAULT false,
    helpful_count INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO retail.product_reviews (tenant_id, product_id, customer_id, rating, title, comment, is_verified_purchase, helpful_count) VALUES
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000001', 'cust-001', 5, 'Excelente teléfono', 'La pantalla AMOLED es impresionante y la cámara toma fotos increíbles. La batería dura todo el día con uso intensivo.', true, 34),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000001', 'cust-015', 4, 'Muy buen rendimiento', 'Rápido, fluido y la carga de 65W es un game changer. Solo le doy 4 estrellas porque no trae cargador en la caja.', true, 21),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000001', 'cust-022', 5, 'Vale cada peso', 'Me cambié de un iPhone y no me arrepiento. La personalización de Android 15 con la capa de Zent es muy limpia.', true, 15),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000003', 'cust-001', 5, 'La mejor cámara del mercado', 'El zoom 100x es una locura. Las fotos nocturnas salen perfectas. La IA de Samsung realmente ayuda en el día a día.', true, 28),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000004', 'cust-005', 5, 'El mejor laptop para developers', 'Compila proyectos enormes en segundos. La pantalla XDR es perfecta para diseño. Batería eterna.', true, 42),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000004', 'cust-017', 5, 'Increíble potencia', 'Renderizo video 8K sin problemas. El M4 es una bestia. Cero ruido de ventilador incluso bajo carga pesada.', true, 19),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000007', 'cust-004', 5, 'Cancelación de ruido mágica', 'Los uso en la oficina open space y no escucho nada. La calidad de audio es superior a los Bose QC.', true, 56),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000007', 'cust-023', 4, 'Muy cómodos para vuelos largos', 'Los usé en un vuelo de 14 horas y no me cansaron. La batería aguantó todo el viaje. Plegables y compactos.', true, 31),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000008', 'cust-003', 5, 'Los mejores earbuds', 'Se conectan instantáneo con todo el ecosistema Apple. El audio espacial es increíble para películas.', true, 67),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000012', 'cust-008', 5, 'Café de especialidad en casa', 'El molinillo integrado marca la diferencia. Café recién molido cada mañana. Fácil de limpiar.', true, 23),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000013', 'cust-006', 5, 'Mis zapatillas favoritas', 'Corrí la maratón de Santiago con ellas y 10/10. Amortiguación perfecta, cero ampollas. Ya voy por mi segundo par.', true, 89),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000013', 'cust-018', 4, 'Excelente relación calidad-precio', 'Por 130k son muy superiores a opciones de 200k+. El Boost se siente reactivo. La talla viene un poco justa.', true, 45),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000015', 'cust-002', 5, 'Perfectas para entrenar en casa', '5 niveles de resistencia cubren desde principiante a avanzado. El anclaje de puerta es muy sólido.', true, 112),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000011', 'cust-020', 3, 'Bueno pero con fallas', 'Aspira bien pero a veces se pierde y no encuentra la base. La app es mejorable. Por el precio esperaba más.', false, 12),
('00000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000020', 'cust-010', 5, 'Clásico infaltable', 'Catan nunca falla en las juntas con amigos. Fácil de aprender, difícil de masterizar. El tablero modular lo hace rejugable.', true, 78);

-- =============================================================================
-- Views: Vistas materializadas para enriquecer el discovery
-- =============================================================================

-- Vista que combina producto + categoría + stock para queries frecuentes
CREATE OR REPLACE VIEW retail.vw_product_catalog AS
SELECT
    p.id,
    p.name,
    p.description,
    p.sku,
    p.brand,
    p.price,
    p.tags,
    c.name AS category_name,
    pc.name AS parent_category_name,
    COALESCE(inv.total_stock, 0) AS total_stock,
    inv.is_in_stock,
    COALESCE(rev.avg_rating, 0) AS avg_rating,
    COALESCE(rev.review_count, 0) AS review_count,
    COALESCE(sls.total_sales, 0) AS total_sales,
    COALESCE(sls.total_revenue, 0) AS total_revenue,
    COALESCE(sls.total_units, 0) AS total_units,
    sls.last_sale_date
FROM retail.products p
LEFT JOIN retail.categories c ON p.category_id = c.id
LEFT JOIN retail.categories pc ON c.parent_id = pc.id
LEFT JOIN LATERAL (
    SELECT
        COALESCE(SUM(i.quantity_available), 0) AS total_stock,
        BOOL_OR(i.is_in_stock) AS is_in_stock
    FROM retail.inventory i
    WHERE i.product_id = p.id
) inv ON true
LEFT JOIN LATERAL (
    SELECT
        AVG(r.rating) AS avg_rating,
        COUNT(r.id) AS review_count
    FROM retail.product_reviews r
    WHERE r.product_id = p.id
) rev ON true
LEFT JOIN LATERAL (
    SELECT
        COUNT(s.id) AS total_sales,
        COALESCE(SUM(s.total_amount), 0) AS total_revenue,
        COALESCE(SUM(s.quantity), 0) AS total_units,
        MAX(s.sale_date) AS last_sale_date
    FROM retail.sales s
    WHERE s.product_id = p.id
) sls ON true;
