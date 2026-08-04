-- =============================================================================
-- Seed Data: Farmacia "ZentSalud" — Datos reales para RAG
-- =============================================================================
-- Schema: farmacia — Dominio farmacéutico con productos, recetas, proveedores e
-- isapres reales. El ingestion engine descubre todo automáticamente.
-- =============================================================================

-- Limpiar schema retail anterior
DROP SCHEMA IF EXISTS retail CASCADE;

CREATE SCHEMA IF NOT EXISTS farmacia;

-- =============================================================================
-- 1. CATEGORÍAS — Jerarquía farmacéutica real
-- =============================================================================
CREATE TABLE IF NOT EXISTS farmacia.categories (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(255) NOT NULL,
    description TEXT,
    parent_id UUID REFERENCES farmacia.categories(id),
    display_order INT DEFAULT 0,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (tenant_id, slug)
);

INSERT INTO farmacia.categories (id, tenant_id, name, slug, description, display_order) VALUES
('c1000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000001', 'Medicamentos', 'medicamentos', 'Medicamentos éticos (con receta) y de venta libre (OTC)', 1),
('c1000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-000000000001', 'Vitaminas y Suplementos', 'vitaminas-suplementos', 'Vitaminas, minerales, suplementos deportivos y nutricionales', 2),
('c1000000-0000-0000-0000-000000000003', '00000000-0000-0000-0000-000000000001', 'Dermocosmética', 'dermocosmetica', 'Cuidado facial, corporal, protección solar y capilar', 3),
('c1000000-0000-0000-0000-000000000004', '00000000-0000-0000-0000-000000000001', 'Cuidado Personal', 'cuidado-personal', 'Higiene bucal, desinfectantes, cuidado íntimo', 4),
('c1000000-0000-0000-0000-000000000005', '00000000-0000-0000-0000-000000000001', 'Bebés y Maternidad', 'bebes-maternidad', 'Pañales, fórmulas infantiles, accesorios de lactancia', 5),
('c1000000-0000-0000-0000-000000000006', '00000000-0000-0000-0000-000000000001', 'Primeros Auxilios', 'primeros-auxilios', 'Vendas, apósitos, termómetros, tensiómetros, insumos clínicos', 6),
('c1000000-0000-0000-0000-000000000007', '00000000-0000-0000-0000-000000000001', 'Homeopatía y Natural', 'homeopatia-natural', 'Productos homeopáticos, fitoterapia, aceites esenciales', 7)
ON CONFLICT (tenant_id, slug) DO NOTHING;

INSERT INTO farmacia.categories (id, tenant_id, name, slug, description, parent_id, display_order) VALUES
-- Medicamentos subcategorías
('c2000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000001', 'Analgésicos y Antiinflamatorios', 'analgesicos-antiinflamatorios', 'Paracetamol, Ibuprofeno, Naproxeno, Celecoxib, Ácido Acetilsalicílico', 'c1000000-0000-0000-0000-000000000001', 1),
('c2000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-000000000001', 'Antibióticos', 'antibioticos', 'Amoxicilina, Ciprofloxacino, Azitromicina, Claritromicina, Cefadroxilo', 'c1000000-0000-0000-0000-000000000001', 2),
('c2000000-0000-0000-0000-000000000003', '00000000-0000-0000-0000-000000000001', 'Antigripales y Antitusivos', 'antigripales-antitusivos', 'Antigripales compuestos, descongestionantes, jarabes para la tos', 'c1000000-0000-0000-0000-000000000001', 3),
('c2000000-0000-0000-0000-000000000004', '00000000-0000-0000-0000-000000000001', 'Antialérgicos', 'antialergicos', 'Loratadina, Cetirizina, Clorfenamina, Desloratadina, Levocetirizina', 'c1000000-0000-0000-0000-000000000001', 4),
('c2000000-0000-0000-0000-000000000005', '00000000-0000-0000-0000-000000000001', 'Digestivos y Antiácidos', 'digestivos-antiacidos', 'Omeprazol, Ranitidina, Loperamida, Simeticona, Sales de Rehidratación', 'c1000000-0000-0000-0000-000000000001', 5),
('c2000000-0000-0000-0000-000000000006', '00000000-0000-0000-0000-000000000001', 'Cardiovasculares', 'cardiovasculares', 'Losartán, Enalapril, Atorvastatina, Amlodipino, Hidroclorotiazida, AAS', 'c1000000-0000-0000-0000-000000000001', 6),
('c2000000-0000-0000-0000-000000000007', '00000000-0000-0000-0000-000000000001', 'Antidiabéticos', 'antidiabeticos', 'Metformina, Glibenclamida, Insulina, Sitagliptina, Empagliflozina', 'c1000000-0000-0000-0000-000000000001', 7),
-- Vitaminas y Suplementos subcategorías
('c2000000-0000-0000-0000-000000000008', '00000000-0000-0000-0000-000000000001', 'Vitaminas y Minerales', 'vitaminas-minerales', 'Vitamina C, D, Complejo B, Magnesio, Zinc, Calcio, Hierro', 'c1000000-0000-0000-0000-000000000002', 1),
('c2000000-0000-0000-0000-000000000009', '00000000-0000-0000-0000-000000000001', 'Suplementos Deportivos', 'suplementos-deportivos', 'Proteínas, Creatina, BCAA, Pre-entreno, Glutamina, Omega 3', 'c1000000-0000-0000-0000-000000000002', 2),
-- Dermocosmética subcategorías
('c2000000-0000-0000-0000-000000000010', '00000000-0000-0000-0000-000000000001', 'Protección Solar', 'proteccion-solar', 'Protectores solares faciales y corporales FPS 30, 50, 50+', 'c1000000-0000-0000-0000-000000000003', 1),
('c2000000-0000-0000-0000-000000000011', '00000000-0000-0000-0000-000000000001', 'Cuidado Facial', 'cuidado-facial', 'Cremas hidratantes, anti-edad, contorno de ojos, sérums', 'c1000000-0000-0000-0000-000000000003', 2),
('c2000000-0000-0000-0000-000000000012', '00000000-0000-0000-0000-000000000001', 'Cuidado Capilar', 'cuidado-capilar', 'Shampoos medicados, Minoxidil, tratamientos anticaída', 'c1000000-0000-0000-0000-000000000003', 3),
-- Cuidado Personal subcategorías
('c2000000-0000-0000-0000-000000000013', '00000000-0000-0000-0000-000000000001', 'Higiene Bucal', 'higiene-bucal', 'Cepillos dentales, pastas dentales, enjuagues bucales, hilo dental', 'c1000000-0000-0000-0000-000000000004', 1),
('c2000000-0000-0000-0000-000000000014', '00000000-0000-0000-0000-000000000001', 'Desinfección y Antisépticos', 'desinfeccion-antisepticos', 'Alcohol gel, clorhexidina, povidona yodada, agua oxigenada', 'c1000000-0000-0000-0000-000000000004', 2),
-- Bebés subcategorías
('c2000000-0000-0000-0000-000000000015', '00000000-0000-0000-0000-000000000001', 'Pañales y Toallitas', 'panales-toallitas', 'Pañales desechables, toallitas húmedas, cremas para rozaduras', 'c1000000-0000-0000-0000-000000000005', 1),
('c2000000-0000-0000-0000-000000000016', '00000000-0000-0000-0000-000000000001', 'Fórmulas Infantiles', 'formulas-infantiles', 'Leches de fórmula etapa 1, 2 y 3, leches especiales', 'c1000000-0000-0000-0000-000000000005', 2),
-- Primeros Auxilios subcategorías
('c2000000-0000-0000-0000-000000000017', '00000000-0000-0000-0000-000000000001', 'Vendas y Apósitos', 'vendas-apositos', 'Vendas elásticas, gasas, apósitos, cintas adhesivas, algodón', 'c1000000-0000-0000-0000-000000000006', 1),
('c2000000-0000-0000-0000-000000000018', '00000000-0000-0000-0000-000000000001', 'Dispositivos Médicos', 'dispositivos-medicos', 'Termómetros, tensiómetros, oxímetros, glucómetros, nebulizadores', 'c1000000-0000-0000-0000-000000000006', 2)
ON CONFLICT (tenant_id, slug) DO NOTHING;

-- =============================================================================
-- 2. PROVEEDORES / LABORATORIOS
-- =============================================================================
CREATE TABLE IF NOT EXISTS farmacia.suppliers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name VARCHAR(300) NOT NULL,
    rut VARCHAR(20) NOT NULL,
    contact_name VARCHAR(300),
    contact_phone VARCHAR(50),
    contact_email VARCHAR(300),
    website VARCHAR(500),
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (tenant_id, rut)
);

INSERT INTO farmacia.suppliers (id, tenant_id, name, rut, contact_name, contact_phone, contact_email, website) VALUES
('e1000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000001', 'Laboratorio Chile S.A.', '91.234.000-1', 'María Angélica Soto', '+56 2 2364 5000', 'ventas@labchile.cl', 'www.laboratoriochile.cl'),
('e1000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-000000000001', 'Bayer S.A.', '91.567.000-2', 'Carlos Muñoz Rivera', '+56 2 2520 8000', 'pedidos.cl@bayer.com', 'www.bayer.cl'),
('e1000000-0000-0000-0000-000000000003', '00000000-0000-0000-0000-000000000001', 'Laboratorios Saval S.A.', '96.803.000-3', 'Patricia Araya Contreras', '+56 2 2754 3000', 'contacto@saval.cl', 'www.saval.cl'),
('e1000000-0000-0000-0000-000000000004', '00000000-0000-0000-0000-000000000001', 'Laboratorio Bagó Chile S.A.', '76.123.000-4', 'Rodrigo Fernández P.', '+56 2 2496 2000', 'ventas@bago.cl', 'www.bago.cl'),
('e1000000-0000-0000-0000-000000000005', '00000000-0000-0000-0000-000000000001', 'Pfizer Chile S.A.', '96.994.000-5', 'Carolina Leiva Morales', '+56 2 2710 7000', 'recepcion.chile@pfizer.com', 'www.pfizer.cl'),
('e1000000-0000-0000-0000-000000000006', '00000000-0000-0000-0000-000000000001', 'Laboratorio Prater S.A.', '91.456.000-6', 'Alejandro Guzmán T.', '+56 2 2598 4000', 'contacto@prater.cl', 'www.prater.cl'),
('e1000000-0000-0000-0000-000000000007', '00000000-0000-0000-0000-000000000001', 'Merck S.A.', '96.667.000-7', 'Francisca Rojas Duarte', '+56 2 2340 1000', 'info.cl@merckgroup.com', 'www.merck.cl'),
('e1000000-0000-0000-0000-000000000008', '00000000-0000-0000-0000-000000000001', 'Laboratorios Recalcine S.A.', '91.789.000-8', 'Eduardo Herrera Silva', '+56 2 2750 6000', 'ventas@recalcine.cl', 'www.recalcine.cl')
ON CONFLICT (tenant_id, rut) DO NOTHING;

-- =============================================================================
-- 3. ISAPRES / SEGUROS DE SALUD
-- =============================================================================
CREATE TABLE IF NOT EXISTS farmacia.health_insurance (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name VARCHAR(300) NOT NULL,
    code VARCHAR(20) NOT NULL,
    coverage_percentage DECIMAL(5,2) DEFAULT 0,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (tenant_id, code)
);

INSERT INTO farmacia.health_insurance (id, tenant_id, name, code, coverage_percentage) VALUES
('b1000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000001', 'FONASA', 'FONASA-001', 40.00),
('b1000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-000000000001', 'Isapre Banmédica', 'BANMED-001', 60.00),
('b1000000-0000-0000-0000-000000000003', '00000000-0000-0000-0000-000000000001', 'Isapre Cruz Blanca', 'CRUZBLA-001', 55.00),
('b1000000-0000-0000-0000-000000000004', '00000000-0000-0000-0000-000000000001', 'Isapre Colmena', 'COLMENA-001', 50.00),
('b1000000-0000-0000-0000-000000000005', '00000000-0000-0000-0000-000000000001', 'Isapre Consalud', 'CONSAL-001', 55.00),
('b1000000-0000-0000-0000-000000000006', '00000000-0000-0000-0000-000000000001', 'Isapre Vida Tres', 'VIDATRE-001', 70.00),
('b1000000-0000-0000-0000-000000000007', '00000000-0000-0000-0000-000000000001', 'Isapre Nueva MasVida', 'MASVIDA-001', 45.00),
('b1000000-0000-0000-0000-000000000008', '00000000-0000-0000-0000-000000000001', 'Sin Seguro / Particular', 'PARTIC-000', 0.00)
ON CONFLICT (tenant_id, code) DO NOTHING;

-- =============================================================================
-- 4. PRODUCTOS — Catálogo farmacéutico real
-- =============================================================================
CREATE TABLE IF NOT EXISTS farmacia.products (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    category_id UUID REFERENCES farmacia.categories(id),
    supplier_id UUID REFERENCES farmacia.suppliers(id),
    name VARCHAR(500) NOT NULL,
    slug VARCHAR(500) NOT NULL,
    description TEXT,
    sku VARCHAR(100) NOT NULL,
    active_ingredient VARCHAR(300),
    concentration VARCHAR(100),
    presentation_unit VARCHAR(200),
    registration_number VARCHAR(50),
    requires_prescription BOOLEAN DEFAULT false,
    price DECIMAL(12,2) NOT NULL,
    cost DECIMAL(12,2),
    currency VARCHAR(3) DEFAULT 'CLP',
    tags TEXT[],
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (tenant_id, sku)
);

INSERT INTO farmacia.products (id, tenant_id, category_id, supplier_id, name, slug, description, sku, active_ingredient, concentration, presentation_unit, registration_number, requires_prescription, price, cost, tags) VALUES
-- Analgésicos y Antiinflamatorios
('d1000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000001', 'c2000000-0000-0000-0000-000000000001', 'e1000000-0000-0000-0000-000000000001', 'Paracetamol 500mg 16 Comprimidos', 'paracetamol-500mg-16-comp', 'Analgésico y antipirético de venta libre. Alivio eficaz del dolor leve a moderado y reducción de fiebre. No irrita el estómago.', 'FAR-PAR500-001', 'Paracetamol', '500mg', '16 Comprimidos', 'ISP-23891-A', false, 1990, 890, ARRAY['paracetamol','analgesico','antipiretico','otc','dolor','fiebre']),
('d1000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-000000000001', 'c2000000-0000-0000-0000-000000000001', 'e1000000-0000-0000-0000-000000000003', 'Ibuprofeno 600mg 20 Comprimidos Recubiertos', 'ibuprofeno-600mg-20-comp', 'Antiinflamatorio no esteroideo (AINE). Alivio del dolor moderado a intenso, inflamación y fiebre. Acción rápida con recubrimiento gastroprotector.', 'FAR-IBU600-002', 'Ibuprofeno', '600mg', '20 Comprimidos Recubiertos', 'ISP-45210-B', false, 5990, 3200, ARRAY['ibuprofeno','aine','antiinflamatorio','analgesico','dolor-moderado']),
('d1000000-0000-0000-0000-000000000003', '00000000-0000-0000-0000-000000000001', 'c2000000-0000-0000-0000-000000000001', 'e1000000-0000-0000-0000-000000000004', 'Celecoxib 200mg 30 Cápsulas', 'celecoxib-200mg-30-caps', 'Antiinflamatorio selectivo COX-2. Tratamiento de artritis reumatoide, osteoartritis y dolor crónico. Menor riesgo gastrointestinal que AINEs tradicionales.', 'FAR-CEL200-003', 'Celecoxib', '200mg', '30 Cápsulas', 'ISP-52340-C', true, 24990, 15600, ARRAY['celecoxib','cox2','antiinflamatorio','artritis','receta']),

-- Antibióticos
('d1000000-0000-0000-0000-000000000004', '00000000-0000-0000-0000-000000000001', 'c2000000-0000-0000-0000-000000000002', 'e1000000-0000-0000-0000-000000000002', 'Amoxicilina 500mg 21 Cápsulas', 'amoxicilina-500mg-21-caps', 'Antibiótico de amplio espectro del grupo de las penicilinas. Tratamiento de infecciones respiratorias, urinarias, otitis y faringoamigdalitis bacteriana.', 'FAR-AMOX500-001', 'Amoxicilina Trihidrato', '500mg', '21 Cápsulas', 'ISP-18760-A', true, 7990, 4200, ARRAY['amoxicilina','antibiotico','penicilina','infeccion-respiratoria','receta-retenida']),
('d1000000-0000-0000-0000-000000000005', '00000000-0000-0000-0000-000000000001', 'c2000000-0000-0000-0000-000000000002', 'e1000000-0000-0000-0000-000000000005', 'Azitromicina 500mg 3 Comprimidos', 'azitromicina-500mg-3-comp', 'Antibiótico macrólido de amplio espectro. Dosis única diaria por 3 días. Eficaz contra infecciones respiratorias altas y bajas, piel y ETS.', 'FAR-AZIT500-001', 'Azitromicina Dihidrato', '500mg', '3 Comprimidos', 'ISP-61280-B', true, 12990, 7800, ARRAY['azitromicina','macrolido','antibiotico','3-dias','infeccion-respiratoria']),

-- Antigripales
('d1000000-0000-0000-0000-000000000006', '00000000-0000-0000-0000-000000000001', 'c2000000-0000-0000-0000-000000000003', 'e1000000-0000-0000-0000-000000000002', 'Antigripal Día-Noche 12 Comprimidos', 'antigripal-dia-noche-12-comp', 'Antigripal compuesto con paracetamol, pseudoefedrina y clorfenamina. Fórmula día sin somnolencia y noche con antihistamínico para descanso reparador.', 'FAR-GRIP-DN12-001', 'Paracetamol + Pseudoefedrina + Clorfenamina', '500mg/30mg/4mg', '12 Comprimidos (8 Día + 4 Noche)', 'ISP-89123-B', false, 6990, 3800, ARRAY['antigripal','paracetamol','dia-noche','congestion','resfrio','gripe']),
('d1000000-0000-0000-0000-000000000007', '00000000-0000-0000-0000-000000000001', 'c2000000-0000-0000-0000-000000000003', 'e1000000-0000-0000-0000-000000000006', 'Propóleo + Miel + Limón Jarabe 200ml', 'propoleo-miel-limon-jarabe', 'Jarabe natural a base de propóleo, miel de abeja pura y extracto de limón. Alivio de la tos irritativa y dolor de garganta. Sin contraindicaciones. Toda la familia.', 'FAR-PROP-JAR-001', 'Propóleo + Miel + Extracto de Limón', 'NA', 'Frasco 200ml', 'ISP-NAT-4532', false, 4990, 2400, ARRAY['propoleo','miel','natural','tos','garganta','jarabe','familiar']),

-- Antialérgicos
('d1000000-0000-0000-0000-000000000008', '00000000-0000-0000-0000-000000000001', 'c2000000-0000-0000-0000-000000000004', 'e1000000-0000-0000-0000-000000000006', 'Loratadina 10mg 30 Comprimidos', 'loratadina-10mg-30-comp', 'Antihistamínico de segunda generación no sedante. Alivio de alergias estacionales y perennes, rinitis alérgica, urticaria. 24 horas de efecto sin somnolencia.', 'FAR-LORA10-001', 'Loratadina', '10mg', '30 Comprimidos', 'ISP-34567-A', false, 4990, 2600, ARRAY['loratadina','antihistaminico','alergia','no-sedante','rinitis','urticaria']),
('d1000000-0000-0000-0000-000000000009', '00000000-0000-0000-0000-000000000001', 'c2000000-0000-0000-0000-000000000004', 'e1000000-0000-0000-0000-000000000001', 'Cetirizina 10mg 30 Comprimidos Recubiertos', 'cetirizina-10mg-30-comp', 'Antihistamínico potente de segunda generación. Rápido alivio de síntomas alérgicos nasales y oculares. Efectivo en urticaria crónica.', 'FAR-CET10-001', 'Cetirizina Diclorhidrato', '10mg', '30 Comprimidos Recubiertos', 'ISP-78230-B', false, 6990, 3700, ARRAY['cetirizina','antihistaminico','alergia','rinitis','urticaria-cronica']),

-- Digestivos y Antiácidos
('d1000000-0000-0000-0000-000000000010', '00000000-0000-0000-0000-000000000001', 'c2000000-0000-0000-0000-000000000005', 'e1000000-0000-0000-0000-000000000003', 'Omeprazol 20mg 14 Cápsulas', 'omeprazol-20mg-14-caps', 'Inhibidor de la bomba de protones. Tratamiento del reflujo gastroesofágico, úlcera gástrica y duodenal, erradicación de H. pylori en combinación.', 'FAR-OME20-001', 'Omeprazol', '20mg', '14 Cápsulas de Liberación Retardada', 'ISP-56210-C', false, 4990, 2800, ARRAY['omeprazol','ibp','reflujo','ulcera','acidez','gastritis']),
('d1000000-0000-0000-0000-000000000011', '00000000-0000-0000-0000-000000000001', 'c2000000-0000-0000-0000-000000000005', 'e1000000-0000-0000-0000-000000000008', 'Loperamida 2mg 6 Comprimidos', 'loperamida-2mg-6-comp', 'Antidiarreico de acción rápida. Reduce la motilidad intestinal y la secreción de fluidos. Alivio sintomático de diarrea aguda inespecífica.', 'FAR-LOP2-001', 'Loperamida Clorhidrato', '2mg', '6 Comprimidos', 'ISP-19870-A', false, 3490, 1700, ARRAY['loperamida','antidiarreico','diarrea','viajero','emergencia']),

-- Cardiovasculares
('d1000000-0000-0000-0000-000000000012', '00000000-0000-0000-0000-000000000001', 'c2000000-0000-0000-0000-000000000006', 'e1000000-0000-0000-0000-000000000004', 'Losartán Potásico 50mg 30 Comprimidos', 'losartan-50mg-30-comp', 'Antagonista del receptor de angiotensina II (ARA-II). Tratamiento de hipertensión arterial esencial. Protección renal en diabetes tipo 2.', 'FAR-LOS50-001', 'Losartán Potásico', '50mg', '30 Comprimidos Recubiertos', 'ISP-67120-B', true, 12990, 7800, ARRAY['losartan','ara2','hipertension','presion-arterial','renal','receta']),
('d1000000-0000-0000-0000-000000000013', '00000000-0000-0000-0000-000000000001', 'c2000000-0000-0000-0000-000000000006', 'e1000000-0000-0000-0000-000000000005', 'Atorvastatina 20mg 30 Comprimidos', 'atorvastatina-20mg-30-comp', 'Estatina de alta potencia. Reducción del colesterol LDL y triglicéridos. Prevención cardiovascular primaria y secundaria.', 'FAR-ATV20-001', 'Atorvastatina Cálcica', '20mg', '30 Comprimidos Recubiertos', 'ISP-80340-D', true, 22990, 14200, ARRAY['atorvastatina','estatina','colesterol','ldl','cardiovascular','prevencion']),

-- Antidiabéticos
('d1000000-0000-0000-0000-000000000014', '00000000-0000-0000-0000-000000000001', 'c2000000-0000-0000-0000-000000000007', 'e1000000-0000-0000-0000-000000000007', 'Metformina 850mg 60 Comprimidos', 'metformina-850mg-60-comp', 'Antidiabético oral biguanida de primera línea. Reduce la producción hepática de glucosa y mejora la sensibilidad a la insulina. Tratamiento de diabetes mellitus tipo 2.', 'FAR-MET850-001', 'Metformina Clorhidrato', '850mg', '60 Comprimidos', 'ISP-44560-B', true, 9990, 5800, ARRAY['metformina','biguanida','diabetes-tipo2','glucosa','insulina','receta']),

-- Vitaminas y Minerales
('d1000000-0000-0000-0000-000000000015', '00000000-0000-0000-0000-000000000001', 'c2000000-0000-0000-0000-000000000008', 'e1000000-0000-0000-0000-000000000002', 'Vitamina C 1000mg 10 Comprimidos Efervescentes Sabor Naranja', 'vitamina-c-1000mg-10-eferv', 'Suplemento de vitamina C de alta potencia. Refuerza el sistema inmunológico, favorece la absorción de hierro y actúa como antioxidante. Formato efervescente de rápida absorción y agradable sabor.', 'FAR-VITC1000-001', 'Ácido Ascórbico (Vitamina C)', '1000mg', '10 Comprimidos Efervescentes', 'ISP-SUP-12501', false, 5990, 3100, ARRAY['vitamina-c','acido-ascorbico','inmunidad','antioxidante','efervescente','naranja']),
('d1000000-0000-0000-0000-000000000016', '00000000-0000-0000-0000-000000000001', 'c2000000-0000-0000-0000-000000000008', 'e1000000-0000-0000-0000-000000000005', 'Complejo B Fortificado 60 Comprimidos', 'complejo-b-fortificado-60-comp', 'Fórmula completa con B1, B2, B3, B5, B6, B7, B9 y B12. Apoya el metabolismo energético, función del sistema nervioso y formación de glóbulos rojos.', 'FAR-COMP_B-001', 'Complejo vitamínico B (B1,B2,B3,B5,B6,B7,B9,B12)', 'NA', '60 Comprimidos', 'ISP-SUP-23080', false, 7990, 4500, ARRAY['complejo-b','vitaminas-b','energia','metabolismo','sistema-nervioso']),
('d1000000-0000-0000-0000-000000000017', '00000000-0000-0000-0000-000000000001', 'c2000000-0000-0000-0000-000000000008', 'e1000000-0000-0000-0000-000000000008', 'Vitamina D3 2000 UI 60 Cápsulas Blandas', 'vitamina-d3-2000-ui-60-caps', 'Suplemento de colecalciferol 2000 UI. Esencial para la absorción de calcio, salud ósea y función inmunológica. Recomendado en baja exposición solar y adultos mayores.', 'FAR-VITD3-001', 'Colecalciferol (Vitamina D3)', '2000 UI', '60 Cápsulas Blandas', 'ISP-SUP-38901', false, 8990, 5200, ARRAY['vitamina-d3','colecalciferol','huesos','calcio','inmunidad','adulto-mayor']),

-- Protección Solar
('d1000000-0000-0000-0000-000000000018', '00000000-0000-0000-0000-000000000001', 'c2000000-0000-0000-0000-000000000010', 'e1000000-0000-0000-0000-000000000002', 'Protector Solar Facial FPS 50+ Antimanchas 50ml', 'protector-solar-facial-fps50-50ml', 'Protector solar facial de amplio espectro UVA/UVB con FPS 50+. Fórmula con niacinamida y ácido hialurónico que hidrata, previene manchas y unifica el tono. Oil-free, no comedogénico.', 'FAR-SOL-FPS50-001', 'Octinoxato, Avobenzona, Niacinamida, Ácido Hialurónico', 'FPS 50+', 'Tubo 50ml', 'ISP-COSM-7812', false, 15990, 9400, ARRAY['protector-solar','fps50','facial','antimanchas','uva-uvb','oil-free']),

-- Cuidado Facial
('d1000000-0000-0000-0000-000000000019', '00000000-0000-0000-0000-000000000001', 'c2000000-0000-0000-0000-000000000011', 'e1000000-0000-0000-0000-000000000002', 'Crema Hidratante con Ceramidas y Ácido Hialurónico 200ml', 'crema-hidratante-ceramidas-200ml', 'Crema hidratante avanzada con ceramidas esenciales, ácido hialurónico y vitamina E. Restaura la barrera cutánea, hidratación profunda 24h. Ideal para piel seca, sensible y atópica.', 'FAR-CREM-HID-001', 'Ceramidas, Ácido Hialurónico, Vitamina E', 'NA', 'Frasco 200ml', 'ISP-COSM-12450', false, 14990, 8700, ARRAY['crema-hidratante','ceramidas','acido-hialuronico','piel-seca','sensible','24h']),

-- Desinfección y Antisépticos
('d1000000-0000-0000-0000-000000000020', '00000000-0000-0000-0000-000000000001', 'c2000000-0000-0000-0000-000000000014', 'e1000000-0000-0000-0000-000000000001', 'Alcohol Gel 70% Antiséptico 1 Litro', 'alcohol-gel-70-1l', 'Solución antiséptica con 70% de alcohol etílico. Elimina el 99.9% de bacterias y virus. Con glicerina y aloe vera para evitar resequedad en las manos. Dosificador tipo pump.', 'FAR-ALCGEL-001', 'Alcohol Etílico 70% + Glicerina + Aloe Vera', '70% v/v', 'Botella 1000ml con Dosificador', 'ISP-ASEP-4501', false, 4990, 2600, ARRAY['alcohol-gel','antiseptico','desinfeccion','manos','bactericida','aloe-vera']),

-- Pañales
('d1000000-0000-0000-0000-000000000021', '00000000-0000-0000-0000-000000000001', 'c2000000-0000-0000-0000-000000000015', 'e1000000-0000-0000-0000-000000000006', 'Pañales Ultra Confort Talla G (11-16kg) 62 Unidades', 'panales-talla-g-62-un', 'Pañales ultra absorbentes con canales antiescape. Triple barrera de protección, indicador de humedad y banda elástica ajustable. Hipoalergénicos. Talla G para bebés de 11 a 16 kg.', 'FAR-PANAL-G-001', 'NA', 'NA', 'Pack 62 Unidades', 'ISP-PAN-8823', false, 20990, 13800, ARRAY['panales','talla-g','bebes','absorbente','anti-escap','hipoalergenico']),

-- Fórmulas Infantiles
('d1000000-0000-0000-0000-000000000022', '00000000-0000-0000-0000-000000000001', 'c2000000-0000-0000-0000-000000000016', 'e1000000-0000-0000-0000-000000000005', 'Fórmula Infantil Etapa 2 Premium 900g', 'formula-infantil-etapa-2-900g', 'Fórmula de continuación para lactantes desde los 6 meses. Con DHA, ARA, hierro, zinc y 13 vitaminas. Prebióticos para salud digestiva.', 'FAR-FORM2-001', 'Leche descremada, suero lácteo, DHA, ARA, prebióticos GOS/FOS', 'NA', 'Lata 900g', 'ISP-ALIM-5610', false, 26990, 17800, ARRAY['formula-infantil','etapa-2','6-meses','dha','hierro','lactante']),

-- Vendas
('d1000000-0000-0000-0000-000000000023', '00000000-0000-0000-0000-000000000001', 'c2000000-0000-0000-0000-000000000017', 'e1000000-0000-0000-0000-000000000007', 'Vendas Elásticas 10cm x 5m Par', 'vendas-elasticas-10cm-5m-par', 'Par de vendas elásticas de algodón de alta compresión. Ideales para sujeción de apósitos, contención de esguinces y traumatismos. Lavables y reutilizables. Con cierre de velcro.', 'FAR-VENDA-001', 'NA', '10cm x 5m', 'Pack 2 Unidades', 'ISP-DISP-2340', false, 5990, 3100, ARRAY['vendas-elasticas','compresion','esguince','aposito','algodon','reutilizable']),

-- Dispositivos Médicos
('d1000000-0000-0000-0000-000000000024', '00000000-0000-0000-0000-000000000001', 'c2000000-0000-0000-0000-000000000018', 'e1000000-0000-0000-0000-000000000007', 'Tensiómetro Digital Automático de Brazo', 'tensiometro-digital-brazo', 'Tensiómetro oscilométrico digital con brazalete universal (22-42cm). Detección de arritmia, memoria 120 lecturas para 2 usuarios, pantalla LCD grande. Certificación clínica.', 'FAR-TENS-001', 'NA', 'NA', 'Set Completo con Estuche', 'ISP-DM-7801', false, 44990, 27800, ARRAY['tensiometro','digital','presion-arterial','brazo','arritmia','memoria']),

-- Homeopatía
('d1000000-0000-0000-0000-000000000025', '00000000-0000-0000-0000-000000000001', 'c1000000-0000-0000-0000-000000000007', 'e1000000-0000-0000-0000-000000000008', 'Valeriana + Melisa + Pasiflora Gotas 50ml', 'valeriana-melisa-pasiflora-gotas', 'Fitoterápico natural con extracto fluido de valeriana, melisa y pasiflora. Inductor del sueño natural, ansiolítico suave. Sin dependencia ni efectos secundarios diurnos.', 'FAR-VAL-GOT-001', 'Valeriana officinalis, Melissa officinalis, Passiflora incarnata', 'NA', 'Frasco Gotero 50ml', 'ISP-NAT-9045', false, 7990, 4200, ARRAY['valeriana','melisa','pasiflora','natural','insomnio','ansiedad','fitoterapia'])
ON CONFLICT (tenant_id, sku) DO NOTHING;

-- =============================================================================
-- 5. INVENTARIO — Stock por producto y sucursal
-- =============================================================================
CREATE TABLE IF NOT EXISTS farmacia.inventory (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    product_id UUID NOT NULL REFERENCES farmacia.products(id),
    warehouse_location VARCHAR(200),
    batch_number VARCHAR(100),
    expiration_date DATE,
    quantity_available INT NOT NULL DEFAULT 0,
    quantity_reserved INT DEFAULT 0,
    quantity_minimum INT DEFAULT 5,
    last_restock_date TIMESTAMPTZ,
    next_restock_eta_days INT,
    is_in_stock BOOLEAN GENERATED ALWAYS AS (quantity_available > 0) STORED,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (tenant_id, product_id, warehouse_location, batch_number)
);

INSERT INTO farmacia.inventory (tenant_id, product_id, warehouse_location, batch_number, expiration_date, quantity_available, quantity_reserved, quantity_minimum, last_restock_date, next_restock_eta_days) VALUES
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000001', 'Farmacia ZentSalud Santiago Centro', 'LCH-P500-B2407A', '2028-06-15', 456, 23, 50, '2026-07-15 10:30:00', 5),
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000001', 'Farmacia ZentSalud Providencia', 'LCH-P500-B2407B', '2028-06-16', 312, 15, 30, '2026-07-20 14:15:00', 7),
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000002', 'Farmacia ZentSalud Santiago Centro', 'SAV-IBU600-L2405A', '2027-12-30', 198, 8, 20, '2026-07-18 09:45:00', 10),
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000003', 'Farmacia ZentSalud Santiago Centro', 'BAG-C200-A2404B', '2028-03-10', 67, 1, 5, '2026-07-10 16:20:00', 21),
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000004', 'Farmacia ZentSalud Santiago Centro', 'BAY-AMOX500-F2406A', '2028-01-15', 0, 0, 10, '2026-07-01 08:00:00', 30),
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000005', 'Farmacia ZentSalud Santiago Centro', 'PFE-AZIT500-G2406B', '2027-11-22', 134, 12, 15, '2026-07-22 11:30:00', 7),
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000006', 'Farmacia ZentSalud Santiago Centro', 'BAY-GRIP-D2407C', '2028-04-05', 423, 38, 40, '2026-07-12 10:00:00', 5),
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000007', 'Farmacia ZentSalud Santiago Centro', 'PRA-PROP-J2405D', '2028-07-20', 287, 10, 25, '2026-07-08 15:40:00', 3),
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000008', 'Farmacia ZentSalud Santiago Centro', 'PRA-LORA10-M2406F', '2028-09-12', 567, 22, 50, '2026-07-05 12:15:00', 5),
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000009', 'Farmacia ZentSalud Santiago Centro', 'LCH-CET10-N2404G', '2028-02-28', 198, 7, 20, '2026-07-14 08:30:00', 7),
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000010', 'Farmacia ZentSalud Santiago Centro', 'SAV-OME20-P2407H', '2028-08-10', 345, 15, 30, '2026-07-20 13:45:00', 5),
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000012', 'Farmacia ZentSalud Santiago Centro', 'BAG-LOS50-R2406J', '2028-05-18', 234, 5, 20, '2026-07-23 09:20:00', 10),
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000013', 'Farmacia ZentSalud Santiago Centro', 'PFE-ATV20-S2403K', '2027-10-05', 123, 3, 10, '2026-07-25 14:10:00', 14),
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000014', 'Farmacia ZentSalud Santiago Centro', 'MER-MET850-T2406L', '2028-06-01', 289, 10, 25, '2026-07-18 10:55:00', 7),
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000015', 'Farmacia ZentSalud Santiago Centro', 'BAY-VITC1000-U2407M', '2028-11-30', 678, 45, 60, '2026-07-10 11:00:00', 5),
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000016', 'Farmacia ZentSalud Santiago Centro', 'PFE-COMPB-V2405N', '2028-05-22', 345, 12, 30, '2026-07-15 16:30:00', 7),
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000018', 'Farmacia ZentSalud Santiago Centro', 'BAY-SOL50-W2407P', '2028-12-01', 234, 8, 20, '2026-07-22 09:15:00', 14),
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000019', 'Farmacia ZentSalud Santiago Centro', 'BAY-CREMH-X2406Q', '2028-04-20', 156, 4, 15, '2026-07-08 13:50:00', 10),
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000020', 'Farmacia ZentSalud Santiago Centro', 'LCH-ALCGEL-Y2407R', '2028-09-01', 890, 56, 100, '2026-07-05 10:20:00', 3),
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000024', 'Farmacia ZentSalud Santiago Centro', 'MER-TENS-Z2406S', '2030-06-30', 87, 3, 10, '2026-07-12 14:45:00', 21),
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000025', 'Farmacia ZentSalud Santiago Centro', 'REC-VALER-A2407T', '2028-08-15', 123, 0, 10, '2026-07-02 09:00:00', 14)
ON CONFLICT (tenant_id, product_id, warehouse_location, batch_number) DO NOTHING;

-- =============================================================================
-- 6. CLIENTES
-- =============================================================================
CREATE TABLE IF NOT EXISTS farmacia.customers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    external_id VARCHAR(100) NOT NULL,
    rut VARCHAR(20),
    name VARCHAR(500),
    email VARCHAR(500),
    phone VARCHAR(50),
    city VARCHAR(200),
    region VARCHAR(200),
    country VARCHAR(2) DEFAULT 'CL',
    birth_date DATE,
    health_insurance_id UUID REFERENCES farmacia.health_insurance(id),
    total_orders INT DEFAULT 0,
    total_spent DECIMAL(14,2) DEFAULT 0,
    loyalty_tier VARCHAR(20) DEFAULT 'bronce',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (tenant_id, external_id)
);

INSERT INTO farmacia.customers (tenant_id, external_id, rut, name, email, phone, city, region, birth_date, health_insurance_id, loyalty_tier, total_orders, total_spent, created_at) VALUES
('00000000-0000-0000-0000-000000000001', 'cust-00001', '12.345.678-9', 'Ana María González Pérez', 'ana.gonzalez@email.com', '+56 9 8765 4321', 'Santiago', 'RM', '1985-03-12', 'b1000000-0000-0000-0000-000000000002', 'gold', 48, 456000, '2025-01-15 10:30:00'),
('00000000-0000-0000-0000-000000000001', 'cust-00002', '9.876.543-2', 'Luis Alberto Muñoz Rojas', 'luis.munoz@email.com', '+56 9 7654 3210', 'Providencia', 'RM', '1972-07-28', 'b1000000-0000-0000-0000-000000000001', 'gold', 156, 1890000, '2024-03-22 14:00:00'),
('00000000-0000-0000-0000-000000000001', 'cust-00003', '23.456.789-0', 'Carmen Gloria Silva Martínez', 'carmen.silva@gmail.com', '+56 9 6543 2109', 'Viña del Mar', 'V', '1990-11-05', 'b1000000-0000-0000-0000-000000000003', 'silver', 23, 234000, '2025-08-10 09:15:00'),
('00000000-0000-0000-0000-000000000001', 'cust-00004', '18.765.432-1', 'Jorge Patricio Cáceres Díaz', 'jorge.caceres@correo.cl', '+56 9 5432 1098', 'Concepción', 'VIII', '1982-01-18', 'b1000000-0000-0000-0000-000000000004', 'bronce', 8, 89000, '2026-01-20 16:45:00'),
('00000000-0000-0000-0000-000000000001', 'cust-00005', '14.567.890-3', 'Rosa Elena Contreras Fuentes', 'rosa.contreras@hotmail.com', '+56 9 4321 0987', 'La Serena', 'IV', '1965-09-30', 'b1000000-0000-0000-0000-000000000001', 'silver', 67, 567000, '2024-06-05 11:20:00'),
('00000000-0000-0000-0000-000000000001', 'cust-00006', '21.098.765-4', 'Daniel Andrés Vega Tapia', 'daniel.vega@outlook.com', '+56 9 3210 9876', 'Antofagasta', 'II', '1995-06-14', 'b1000000-0000-0000-0000-000000000005', 'bronce', 12, 123000, '2025-11-30 08:10:00'),
('00000000-0000-0000-0000-000000000001', 'cust-00007', '16.789.012-5', 'Patricia Alejandra Riquelme Morales', 'patricia.riquelme@icloud.com', '+56 9 2109 8765', 'Temuco', 'IX', '1978-12-22', 'b1000000-0000-0000-0000-000000000006', 'gold', 89, 1230000, '2024-01-15 13:30:00'),
('00000000-0000-0000-0000-000000000001', 'cust-00008', '19.876.543-6', 'Oscar Fernando Herrera Lagos', 'oscar.herrera@empresa.cl', '+56 9 1098 7654', 'Santiago', 'RM', '1988-04-03', 'b1000000-0000-0000-0000-000000000008', 'bronce', 3, 44000, '2026-06-10 17:00:00'),
('00000000-0000-0000-0000-000000000001', 'cust-00009', '25.012.345-7', 'Claudia Verónica Leiva Soto', 'claudia.leiva@live.cl', '+56 9 0987 6543', 'Puente Alto', 'RM', '1992-08-17', 'b1000000-0000-0000-0000-000000000002', 'silver', 34, 312000, '2025-04-18 10:45:00'),
('00000000-0000-0000-0000-000000000001', 'cust-00010', '22.345.678-8', 'Roberto Carlos Farías Ibáñez', 'roberto.farias@gmail.com', '+56 9 9876 5432', 'Valparaíso', 'V', '1970-02-09', 'b1000000-0000-0000-0000-000000000008', 'bronce', 15, 178000, '2025-09-25 12:00:00')
ON CONFLICT (tenant_id, external_id) DO NOTHING;

-- =============================================================================
-- 7. RECETAS MÉDICAS
-- =============================================================================
CREATE TABLE IF NOT EXISTS farmacia.prescriptions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    prescription_code VARCHAR(50) NOT NULL,
    patient_rut VARCHAR(20) NOT NULL,
    patient_name VARCHAR(500),
    doctor_name VARCHAR(500) NOT NULL,
    doctor_rut VARCHAR(20) NOT NULL,
    diagnosis TEXT,
    observations TEXT,
    issue_date DATE NOT NULL,
    expiration_date DATE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (tenant_id, prescription_code)
);

INSERT INTO farmacia.prescriptions (id, tenant_id, prescription_code, patient_rut, patient_name, doctor_name, doctor_rut, diagnosis, observations, issue_date, expiration_date) VALUES
('a1000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000001', 'RX-2026-00001', '12.345.678-9', 'Ana María González Pérez', 'Dra. María Teresa Barrientos', '8.765.432-1', 'Hipertensión arterial esencial grado 1', 'Iniciar con Losartán 50mg cada 24h. Control en 30 días. Dieta baja en sodio. Monitoreo semanal de presión.', '2026-07-05', '2026-08-05'),
('a1000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-000000000001', 'RX-2026-00002', '9.876.543-2', 'Luis Alberto Muñoz Rojas', 'Dr. Andrés Felipe Valenzuela', '15.678.901-2', 'Diabetes mellitus tipo 2 no controlada + Dislipidemia', 'Continuar Metformina 850mg cada 12h. Agregar Atorvastatina 20mg cada noche. Solicitar hemograma y HbA1c en 45 días.', '2026-07-10', '2026-08-10'),
('a1000000-0000-0000-0000-000000000003', '00000000-0000-0000-0000-000000000001', 'RX-2026-00003', '23.456.789-0', 'Carmen Gloria Silva Martínez', 'Dr. Juan Carlos Morales', '10.432.109-8', 'Faringoamigdalitis bacteriana aguda', 'Amoxicilina 500mg cada 8 horas por 7 días. Reforzar con Paracetamol 500mg c/6h si fiebre. Reposo relativo. Hidratación.', '2026-07-12', '2026-07-19'),
('a1000000-0000-0000-0000-000000000004', '00000000-0000-0000-0000-000000000001', 'RX-2026-00004', '18.765.432-1', 'Jorge Patricio Cáceres Díaz', 'Dra. Carolina Espinoza Tapia', '7.890.123-4', 'Crisis asmática moderada', 'Iniciar Azitromicina 500mg 1 vez al día por 3 días como profilaxis. Continuar con broncodilatador inhalado de rescate. Control en 1 semana.', '2026-07-15', '2026-07-22'),
('a1000000-0000-0000-0000-000000000005', '00000000-0000-0000-0000-000000000001', 'RX-2026-00005', '14.567.890-3', 'Rosa Elena Contreras Fuentes', 'Dr. Roberto Martínez Herrera', '9.012.345-6', 'Osteoartritis de rodilla bilateral + Dolor crónico', 'Celecoxib 200mg cada 24h por 30 días. Paracetamol 500mg c/8h si dolor leve. Derivar a fisiatría para programa de ejercicios.', '2026-07-18', '2026-08-17'),
('a1000000-0000-0000-0000-000000000006', '00000000-0000-0000-0000-000000000001', 'RX-2026-00006', '21.098.765-4', 'Daniel Andrés Vega Tapia', 'Dra. Paulina Figueroa', '12.543.210-9', 'Rinitis alérgica estacional persistente', 'Cetirizina 10mg cada 24h por 30 días. Evitar exposición a alérgenos. Lavado nasal con suero fisiológico A.M. y P.M.', '2026-07-20', '2026-08-19'),
('a1000000-0000-0000-0000-000000000007', '00000000-0000-0000-0000-000000000001', 'RX-2026-00007', '16.789.012-5', 'Patricia Alejandra Riquelme Morales', 'Dr. Fernando Gómez', '14.321.098-7', 'Gastritis crónica por H. pylori', 'Omeprazol 20mg cada 12h por 14 días como parte del esquema triple. Amoxicilina 500mg c/8h. No suspender tratamiento antes de completar ciclo.', '2026-07-22', '2026-08-05')
ON CONFLICT (tenant_id, prescription_code) DO NOTHING;

-- =============================================================================
-- 8. VENTAS — Historial con recetas e isapre
-- =============================================================================
CREATE TABLE IF NOT EXISTS farmacia.sales (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    product_id UUID NOT NULL REFERENCES farmacia.products(id),
    customer_id VARCHAR(100),
    quantity INT NOT NULL DEFAULT 1,
    unit_price DECIMAL(12,2) NOT NULL,
    total_amount DECIMAL(14,2) NOT NULL,
    payment_method VARCHAR(50),
    payment_amount DECIMAL(14,2),
    health_insurance_id UUID REFERENCES farmacia.health_insurance(id),
    insurance_covered_amount DECIMAL(14,2) DEFAULT 0,
    prescription_id UUID REFERENCES farmacia.prescriptions(id),
    order_status VARCHAR(30) DEFAULT 'completed',
    sale_date TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    channel VARCHAR(50) DEFAULT 'presencial'
);

INSERT INTO farmacia.sales (tenant_id, product_id, customer_id, quantity, unit_price, total_amount, payment_method, payment_amount, health_insurance_id, insurance_covered_amount, prescription_id, sale_date, channel) VALUES
-- Paracetamol (alta rotación OTC)
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000001', 'cust-00003', 2, 1990, 3980, 'Efectivo', 3980, 'b1000000-0000-0000-0000-000000000003', 0, NULL, '2026-07-01 10:23:00', 'presencial'),
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000001', 'cust-00010', 1, 1990, 1990, 'Débito', 1990, 'b1000000-0000-0000-0000-000000000008', 0, NULL, '2026-07-02 14:15:00', 'presencial'),
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000001', 'cust-00005', 3, 1990, 5970, 'Efectivo', 5970, 'b1000000-0000-0000-0000-000000000001', 0, NULL, '2026-07-04 09:30:00', 'presencial'),
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000001', 'cust-00008', 1, 1990, 1990, 'Débito', 1990, 'b1000000-0000-0000-0000-000000000008', 0, NULL, '2026-07-06 16:10:00', 'presencial'),
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000001', 'cust-00001', 2, 1990, 3980, 'Tarjeta Crédito', 3980, 'b1000000-0000-0000-0000-000000000002', 0, NULL, '2026-07-08 11:45:00', 'web'),
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000001', 'cust-00009', 1, 1990, 1990, 'Efectivo', 1990, 'b1000000-0000-0000-0000-000000000002', 0, NULL, '2026-07-10 08:20:00', 'presencial'),

-- Ibuprofeno
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000002', 'cust-00004', 1, 5990, 5990, 'Débito', 5990, 'b1000000-0000-0000-0000-000000000004', 0, NULL, '2026-07-01 15:40:00', 'presencial'),
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000002', 'cust-00007', 2, 5990, 11980, 'Tarjeta Crédito', 11980, 'b1000000-0000-0000-0000-000000000006', 0, NULL, '2026-07-03 12:10:00', 'presencial'),
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000002', 'cust-00006', 1, 5990, 5990, 'Efectivo', 5990, 'b1000000-0000-0000-0000-000000000005', 0, NULL, '2026-07-05 17:55:00', 'presencial'),

-- Losartán (con receta)
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000012', 'cust-00001', 2, 12990, 25980, 'Tarjeta Crédito', 10392, 'b1000000-0000-0000-0000-000000000002', 15588, 'a1000000-0000-0000-0000-000000000001', '2026-07-05 14:30:00', 'presencial'),
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000012', 'cust-00001', 1, 12990, 12990, 'Tarjeta Crédito', 5196, 'b1000000-0000-0000-0000-000000000002', 7794, 'a1000000-0000-0000-0000-000000000001', '2026-07-28 10:15:00', 'presencial'),

-- Metformina (con receta)
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000014', 'cust-00002', 2, 9990, 19980, 'Efectivo', 11988, 'b1000000-0000-0000-0000-000000000001', 7992, 'a1000000-0000-0000-0000-000000000002', '2026-07-10 09:00:00', 'presencial'),

-- Atorvastatina (con receta)
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000013', 'cust-00002', 1, 22990, 22990, 'Efectivo', 13794, 'b1000000-0000-0000-0000-000000000001', 9196, 'a1000000-0000-0000-0000-000000000002', '2026-07-10 09:00:00', 'presencial'),

-- Amoxicilina (con receta retenida)
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000004', 'cust-00003', 1, 7990, 7990, 'Débito', 4395, 'b1000000-0000-0000-0000-000000000003', 3595, 'a1000000-0000-0000-0000-000000000003', '2026-07-12 11:20:00', 'presencial'),

-- Paracetamol complementando Amoxicilina (misma venta que arriba)
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000001', 'cust-00003', 1, 1990, 1990, 'Débito', 1990, 'b1000000-0000-0000-0000-000000000003', 0, 'a1000000-0000-0000-0000-000000000003', '2026-07-12 11:20:00', 'presencial'),

-- Antigripal Día-Noche (temporada invierno)
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000006', 'cust-00010', 1, 6990, 6990, 'Efectivo', 6990, 'b1000000-0000-0000-0000-000000000008', 0, NULL, '2026-07-13 09:45:00', 'presencial'),
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000006', 'cust-00008', 2, 6990, 13980, 'Débito', 13980, 'b1000000-0000-0000-0000-000000000008', 0, NULL, '2026-07-14 16:30:00', 'presencial'),
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000006', 'cust-00006', 1, 6990, 6990, 'Tarjeta Crédito', 6990, 'b1000000-0000-0000-0000-000000000005', 0, NULL, '2026-07-15 08:10:00', 'presencial'),
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000006', 'cust-00009', 1, 6990, 6990, 'Efectivo', 6990, 'b1000000-0000-0000-0000-000000000002', 0, NULL, '2026-07-17 12:25:00', 'web'),

-- Propóleo jarabe (temporada invierno)
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000007', 'cust-00005', 2, 4990, 9980, 'Efectivo', 9980, 'b1000000-0000-0000-0000-000000000001', 0, NULL, '2026-07-04 14:15:00', 'presencial'),
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000007', 'cust-00010', 1, 4990, 4990, 'Efectivo', 4990, 'b1000000-0000-0000-0000-000000000008', 0, NULL, '2026-07-08 10:30:00', 'presencial'),
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000007', 'cust-00009', 1, 4990, 4990, 'Tarjeta Crédito', 4990, 'b1000000-0000-0000-0000-000000000002', 0, NULL, '2026-07-16 17:20:00', 'web'),

-- Loratadina
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000008', 'cust-00007', 1, 4990, 4990, 'Tarjeta Crédito', 4990, 'b1000000-0000-0000-0000-000000000006', 0, NULL, '2026-07-02 08:30:00', 'presencial'),
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000008', 'cust-00005', 2, 4990, 9980, 'Efectivo', 9980, 'b1000000-0000-0000-0000-000000000001', 0, NULL, '2026-07-18 11:45:00', 'presencial'),

-- Omeprazol
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000010', 'cust-00007', 2, 4990, 9980, 'Tarjeta Crédito', 3992, 'b1000000-0000-0000-0000-000000000006', 5988, 'a1000000-0000-0000-0000-000000000007', '2026-07-22 14:00:00', 'presencial'),
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000010', 'cust-00004', 1, 4990, 4990, 'Débito', 4990, 'b1000000-0000-0000-0000-000000000004', 0, NULL, '2026-07-25 10:00:00', 'presencial'),

-- Vitamina C
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000015', 'cust-00007', 2, 5990, 11980, 'Tarjeta Crédito', 11980, 'b1000000-0000-0000-0000-000000000006', 0, NULL, '2026-07-03 10:15:00', 'presencial'),
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000015', 'cust-00002', 3, 5990, 17970, 'Efectivo', 17970, 'b1000000-0000-0000-0000-000000000001', 0, NULL, '2026-07-19 09:00:00', 'presencial'),
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000015', 'cust-00009', 1, 5990, 5990, 'Efectivo', 5990, 'b1000000-0000-0000-0000-000000000002', 0, NULL, '2026-07-27 12:30:00', 'web'),

-- Alcohol Gel (alta rotación)
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000020', 'cust-00001', 1, 4990, 4990, 'Tarjeta Crédito', 4990, 'b1000000-0000-0000-0000-000000000002', 0, NULL, '2026-07-01 09:00:00', 'presencial'),
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000020', 'cust-00008', 1, 4990, 4990, 'Efectivo', 4990, 'b1000000-0000-0000-0000-000000000008', 0, NULL, '2026-07-07 11:00:00', 'presencial'),
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000020', 'cust-00003', 2, 4990, 9980, 'Débito', 9980, 'b1000000-0000-0000-0000-000000000003', 0, NULL, '2026-07-11 14:30:00', 'presencial'),
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000020', 'cust-00006', 1, 4990, 4990, 'Tarjeta Crédito', 4990, 'b1000000-0000-0000-0000-000000000005', 0, NULL, '2026-07-21 16:45:00', 'web'),

-- Protector Solar (verano)
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000018', 'cust-00009', 1, 15990, 15990, 'Tarjeta Crédito', 15990, 'b1000000-0000-0000-0000-000000000002', 0, NULL, '2026-07-06 10:40:00', 'presencial'),
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000018', 'cust-00001', 1, 15990, 15990, 'Tarjeta Crédito', 15990, 'b1000000-0000-0000-0000-000000000002', 0, NULL, '2026-07-20 15:10:00', 'web'),

-- Tensiómetro
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000024', 'cust-00001', 1, 44990, 44990, 'Tarjeta Crédito', 44990, 'b1000000-0000-0000-0000-000000000002', 0, NULL, '2026-07-09 12:00:00', 'presencial'),

-- Pañales
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000021', 'cust-00003', 2, 20990, 41980, 'Tarjeta Crédito', 41980, 'b1000000-0000-0000-0000-000000000003', 0, NULL, '2026-07-14 09:30:00', 'web'),

-- Crema Hidratante
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000019', 'cust-00007', 1, 14990, 14990, 'Tarjeta Crédito', 14990, 'b1000000-0000-0000-0000-000000000006', 0, NULL, '2026-07-23 16:00:00', 'web'),

-- Valeriana gotas
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000025', 'cust-00005', 1, 7990, 7990, 'Efectivo', 7990, 'b1000000-0000-0000-0000-000000000001', 0, NULL, '2026-07-26 10:20:00', 'presencial')
ON CONFLICT DO NOTHING;

-- =============================================================================
-- 9. RESEÑAS DE PRODUCTOS
-- =============================================================================
CREATE TABLE IF NOT EXISTS farmacia.product_reviews (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    product_id UUID NOT NULL REFERENCES farmacia.products(id),
    customer_id VARCHAR(100),
    rating INT NOT NULL CHECK (rating BETWEEN 1 AND 5),
    title VARCHAR(300),
    comment TEXT,
    is_verified_purchase BOOLEAN DEFAULT false,
    helpful_count INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO farmacia.product_reviews (tenant_id, product_id, customer_id, rating, title, comment, is_verified_purchase, helpful_count) VALUES
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000001', 'cust-00003', 5, 'Siempre en mi botiquín', 'El paracetamol de Laboratorio Chile es el mejor calidad-precio. Siempre lo tengo en casa para fiebre o dolores leves. No irrita el estómago.', true, 45),
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000001', 'cust-00005', 4, 'Efectivo y económico', 'Cumple perfecto para dolores de cabeza y fiebre. La caja de 16 comprimidos rinde harto. Le doy 4 estrellas porque el blíster a veces es difícil de abrir.', true, 23),
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000002', 'cust-00004', 5, 'Único que me calma la migraña', 'Sufro migrañas crónicas y este ibuprofeno 600mg me las corta en 30 minutos. El recubrimiento ayuda a no sentir molestia gástrica.', true, 67),
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000006', 'cust-00008', 5, 'Salvador en invierno', 'Me agarró una gripe fuerte y este antigripal día-noche fue lo único que me permitió funcionar de día y dormir de noche. El componente noche realmente ayuda a descansar.', true, 34),
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000006', 'cust-00010', 3, 'Bueno pero me dio sueño', 'El de día funciona bien, pero el de noche me dejó muy dormido al día siguiente. Quizás es muy fuerte para mí. Prefiero tomar solo el de día.', true, 12),
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000007', 'cust-00005', 5, '100% natural y efectivo', 'Mis nietos y yo usamos este jarabe de propóleo para la tos. Sabe rico, no es empalagoso y calma la irritación de garganta al toque. Me encanta que sea natural.', true, 89),
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000008', 'cust-00007', 5, 'La mejor loratadina', 'No me da nada de sueño y me controla la alergia al polen perfecto. 30 comprimidos duran un mes. Muy recomendable.', true, 56),
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000010', 'cust-00007', 4, 'Mejoró mi gastritis en 1 semana', 'El omeprazol de Saval me ha ayudado muchísimo con el reflujo. La única razón de no darle 5 estrellas es que el efecto no es inmediato, toma unos 3-4 días.', true, 41),
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000012', 'cust-00001', 5, 'Presión controlada por fin', 'Desde que tomo Losartán de Bagó mi presión se mantiene en 120/80. Sin efectos secundarios. Mi cardiólogo me felicitó por la adherencia al tratamiento.', true, 34),
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000013', 'cust-00002', 5, 'Colesterol normal en 2 meses', 'Bajé de 280 a 180 de colesterol total con esta Atorvastatina. Junto con dieta y ejercicio. Cero dolores musculares como efecto secundario, que es común con otras estatinas.', true, 28),
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000015', 'cust-00002', 5, 'Mejor vitamina C efervescente', 'Sabor rico, se disuelve rápido y no deja residuos. La tomo todas las mañanas y siento que me enfermo menos. El formato de 10 es ideal para probar.', true, 62),
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000020', 'cust-00001', 4, 'Básico indispensable', 'Alcohol gel de buena calidad, no deja las manos pegajosas y el aloe vera ayuda a no resecar. El litro rinde caleta. Le doy 4 estrellas porque el dispensador a veces se tapa.', true, 78),
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000024', 'cust-00001', 5, 'Fácil de usar y preciso', 'Compré este tensiómetro para mi mamá hipertensa. Ella lo usa sola sin problemas. Pantalla grande, números claros. Coincide con las mediciones del médico.', true, 45),
('00000000-0000-0000-0000-000000000001', 'd1000000-0000-0000-0000-000000000025', 'cust-00005', 5, 'Duermo como bebé', 'Desde la menopausia no podía dormir bien. Estas gotas naturales me cambiaron la vida. Las tomo 30 min antes de acostarme y duermo profundamente toda la noche sin despertar.', true, 91)
ON CONFLICT DO NOTHING;

-- =============================================================================
-- VISTA MATERIALIZADA — Catálogo completo de farmacia
-- =============================================================================
DROP VIEW IF EXISTS farmacia.vw_product_catalog;
DROP MATERIALIZED VIEW IF EXISTS farmacia.vw_product_catalog;

CREATE MATERIALIZED VIEW farmacia.vw_product_catalog AS
SELECT
    p.id,
    p.name,
    p.description,
    p.sku,
    p.active_ingredient,
    p.concentration,
    p.presentation_unit,
    p.requires_prescription,
    p.registration_number,
    p.price,
    p.tags,
    s.name AS supplier_name,
    s.rut AS supplier_rut,
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
FROM farmacia.products p
LEFT JOIN farmacia.suppliers s ON p.supplier_id = s.id
LEFT JOIN farmacia.categories c ON p.category_id = c.id
LEFT JOIN farmacia.categories pc ON c.parent_id = pc.id
LEFT JOIN LATERAL (
    SELECT
        COALESCE(SUM(i.quantity_available), 0) AS total_stock,
        BOOL_OR(i.is_in_stock) AS is_in_stock
    FROM farmacia.inventory i
    WHERE i.product_id = p.id
) inv ON true
LEFT JOIN LATERAL (
    SELECT
        AVG(r.rating) AS avg_rating,
        COUNT(r.id) AS review_count
    FROM farmacia.product_reviews r
    WHERE r.product_id = p.id
) rev ON true
LEFT JOIN LATERAL (
    SELECT
        COUNT(s.id) AS total_sales,
        COALESCE(SUM(s.total_amount), 0) AS total_revenue,
        COALESCE(SUM(s.quantity), 0) AS total_units,
        MAX(s.sale_date) AS last_sale_date
    FROM farmacia.sales s
    WHERE s.product_id = p.id
) sls ON true;


