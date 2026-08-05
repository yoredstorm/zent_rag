-- =============================================================================
-- Massive Seed Data — Farmacia ZentSalud (~400K registros)
-- =============================================================================
-- Resultados: 500 categorías, 30 proveedores, 50K productos, 25K clientes,
-- 50K ventas, 150K reseñas, 5K recetas médicas
-- Usa generate_series() + LATERAL join combinando arrays de fármacos reales
-- =============================================================================

-- =============================================================================
-- 1. CATEGORÍAS FARMACÉUTICAS (500 adicionales)
-- =============================================================================
INSERT INTO farmacia.categories (tenant_id, name, slug, description, parent_id, display_order)
SELECT
    '00000000-0000-0000-0000-000000000001',
    cat_names[1 + (g % array_length(cat_names, 1))],
    lower(replace(cat_names[1 + (g % array_length(cat_names, 1))], ' ', '-')) || '-' || g,
    'Subcategoría farmacéutica generada automáticamente.',
    CASE WHEN g % 3 = 0 THEN NULL
         ELSE parent_ids[1 + (g % array_length(parent_ids, 1))]::uuid
    END,
    g
FROM generate_series(1, 500) AS g
CROSS JOIN LATERAL (
    SELECT ARRAY[
        'Analgésico General','Antipirético','Antiinflamatorio Tópico','Antibiótico Betalactámico',
        'Antibiótico Macrólido','Antiviral','Antimicótico','Antiparasitario','Antihipertensivo ARA-II',
        'Antihipertensivo IECA','Betabloqueante','Bloqueador de Calcio','Diurético','Hipolipemiante',
        'Antidiabético Oral','Insulina y Análogos','Antidepresivo ISRS','Ansiolítico','Antipsicótico Atípico',
        'Anticonvulsivante','Antiparkinsoniano','Broncodilatador','Corticoide Inhalado','Corticoide Tópico',
        'Corticoide Sistémico','Antihistamínico H1','Antihistamínico H2','Protector Gástrico','Laxante Osmótico',
        'Antidiarreico','Probiótico','Antiespasmódico','Antiácido','Suplemento Multivitamínico',
        'Suplemento Mineral','Suplemento Deportivo','Suplemento Articular','Suplemento Antioxidante',
        'Suplemento para la Memoria','Suplemento para el Sueño','Omega 3 y Aceites Esenciales',
        'Colágeno y Ácido Hialurónico','Proteína y Aminoácidos','Quemador de Grasa','Ganador de Peso',
        'Protector Solar Químico','Protector Solar Físico','Hidratante Facial','Hidratante Corporal',
        'Antiarrugas y Anti-edad','Sérum Facial','Limpiador Facial','Contorno de Ojos',
        'Shampoo Medicado','Tratamiento Anticaída','Acondicionador Terapéutico','Crema para Manos y Pies',
        'Desodorante Clínico','Jabón Antibacterial','Pasta Dental Terapéutica','Enjuague Bucal Medicado',
        'Cepillo Dental Eléctrico','Hilo Dental y Cepillos Interdentales','Alcohol Gel Antiséptico',
        'Solución Desinfectante','Povidona Yodada','Clorhexidina','Agua Oxigenada',
        'Pañal Recién Nacido','Pañal Prematuro','Toallitas Húmedas','Crema Anti-rozaduras',
        'Fórmula Inicio','Fórmula Continuación','Fórmula Crecimiento','Fórmula Antirreflujo',
        'Fórmula Hipoalergénica','Accesorio de Lactancia','Chupete y Mamadera',
        'Venda Elástica','Venda Adhesiva','Apósito Estéril','Gasa Hidrofílica','Cinta Micropore',
        'Algodón Hidrofílico','Termómetro Digital','Tensiómetro de Brazo','Oxímetro de Pulso',
        'Glucómetro y Tiras','Nebulizador y Accesorios','Bastón Ortopédico','Silla de Ruedas',
        'Homeopatía Respiratoria','Homeopatía Digestiva','Homeopatía Ansiedad','Homeopatía Inmunidad',
        'Aceite Esencial Puro','Aceite Esencial Mezcla','Difusor de Aromaterapia','Fitoterapia General'
    ] AS cat_names,
    ARRAY[
        'c1000000-0000-0000-0000-000000000001','c1000000-0000-0000-0000-000000000001',
        'c1000000-0000-0000-0000-000000000002','c1000000-0000-0000-0000-000000000002',
        'c1000000-0000-0000-0000-000000000003','c1000000-0000-0000-0000-000000000003',
        'c1000000-0000-0000-0000-000000000004','c1000000-0000-0000-0000-000000000004',
        'c1000000-0000-0000-0000-000000000005','c1000000-0000-0000-0000-000000000005',
        'c1000000-0000-0000-0000-000000000006','c1000000-0000-0000-0000-000000000006',
        'c1000000-0000-0000-0000-000000000007','c1000000-0000-0000-0000-000000000001',
        'c1000000-0000-0000-0000-000000000002','c1000000-0000-0000-0000-000000000003',
        'c1000000-0000-0000-0000-000000000004','c1000000-0000-0000-0000-000000000005',
        'c1000000-0000-0000-0000-000000000006','c1000000-0000-0000-0000-000000000007'
    ] AS parent_ids
) AS src
ON CONFLICT (tenant_id, slug) DO NOTHING;

-- =============================================================================
-- 2. PROVEEDORES / LABORATORIOS (30)
-- =============================================================================
INSERT INTO farmacia.suppliers (tenant_id, name, rut, contact_name, contact_phone, contact_email, website)
SELECT
    '00000000-0000-0000-0000-000000000001',
    lab.name,
    '90.' || LPAD(g::text, 6::int, '0'::text) || '-' || (g % 10),
    'Representante ' || (g % 5 + 1),
    '+56 2 2' || LPAD(g::text, 3::int, '0'::text) || ' ' || LPAD(((g*7)%9999)::text, 4::int, '0'::text),
    'ventas@' || lower(replace(lab.name, ' ', '')) || '.cl',
    'www.' || lower(replace(lab.name, ' ', '')) || '.cl'
FROM generate_series(1, 30) AS g
CROSS JOIN LATERAL (
    SELECT (ARRAY[
        'Andrómaco','Tecnofarma','Medipharm','Pasteur','Raffo','Gador Chile',
        'Nestlé Health Science','Abbott Chile','Sanofi Aventis','GlaxoSmithKline Chile',
        'Boehringer Ingelheim','AstraZeneca Chile','Novartis Chile','Roche Chile',
        'Bristol-Myers Squibb','Johnson & Johnson Chile','Biogen Chile','Eurofarma Chile',
        'Genomma Lab','Maver','Biotoscana','Fresenius Kabi','Hospira Chile','Bago Chile',
        'Industria Química Farm.','Synthon Chile','Ipsen Chile','Asofarma','Danone Nutricia',
        'Hypofarma'
    ])[g] AS name
) AS lab
ON CONFLICT (tenant_id, rut) DO NOTHING;

-- =============================================================================
-- 3. PRODUCTOS (50,000) — Combinaciones de fármacos, vitaminas y productos reales
-- =============================================================================
CREATE SEQUENCE IF NOT EXISTS farmacia.product_seq;

INSERT INTO farmacia.products (id, tenant_id, category_id, supplier_id, name, slug, description, sku, active_ingredient, concentration, presentation_unit, requires_prescription, price, cost, tags)
SELECT
    ('F' || LPAD(nextval('farmacia.product_seq')::text, 31, '0'))::uuid,
    '00000000-0000-0000-0000-000000000001',
    CASE
        WHEN g % 20 = 0 THEN 'c2000000-0000-0000-0000-000000000001'::uuid
        WHEN g % 20 = 1 THEN 'c2000000-0000-0000-0000-000000000002'::uuid
        WHEN g % 20 = 2 THEN 'c2000000-0000-0000-0000-000000000003'::uuid
        WHEN g % 20 = 3 THEN 'c2000000-0000-0000-0000-000000000004'::uuid
        WHEN g % 20 = 4 THEN 'c2000000-0000-0000-0000-000000000005'::uuid
        WHEN g % 20 = 5 THEN 'c2000000-0000-0000-0000-000000000006'::uuid
        WHEN g % 20 = 6 THEN 'c2000000-0000-0000-0000-000000000007'::uuid
        WHEN g % 20 = 7 THEN 'c2000000-0000-0000-0000-000000000008'::uuid
        WHEN g % 20 = 8 THEN 'c2000000-0000-0000-0000-000000000009'::uuid
        WHEN g % 20 = 9 THEN 'c2000000-0000-0000-0000-000000000010'::uuid
        WHEN g % 20 = 10 THEN 'c2000000-0000-0000-0000-000000000011'::uuid
        WHEN g % 20 = 11 THEN 'c2000000-0000-0000-0000-000000000012'::uuid
        WHEN g % 20 = 12 THEN 'c2000000-0000-0000-0000-000000000013'::uuid
        WHEN g % 20 = 13 THEN 'c2000000-0000-0000-0000-000000000014'::uuid
        WHEN g % 20 = 14 THEN 'c2000000-0000-0000-0000-000000000015'::uuid
        WHEN g % 20 = 15 THEN 'c2000000-0000-0000-0000-000000000016'::uuid
        WHEN g % 20 = 16 THEN 'c2000000-0000-0000-0000-000000000017'::uuid
        WHEN g % 20 = 17 THEN 'c2000000-0000-0000-0000-000000000018'::uuid
        ELSE 'c2000000-0000-0000-0000-000000000008'::uuid
    END,
    (SELECT id FROM farmacia.suppliers WHERE tenant_id = '00000000-0000-0000-0000-000000000001' OFFSET (g % 30) LIMIT 1),
    ingredient[1 + (g % array_length(ingredient, 1))] || ' ' || conc[1 + ((g * 3) % array_length(conc, 1))] || ' ' || units[1 + ((g * 5) % array_length(units, 1))] || ' ' || pres[1 + (g % array_length(pres, 1))],
    lower(REPLACE(ingredient[1 + (g % array_length(ingredient, 1))] || '-' || conc[1 + ((g * 3) % array_length(conc, 1))] || '-' || units[1 + ((g * 5) % array_length(units, 1))] || '-' || pres[1 + (g % array_length(pres, 1))], ' ', '-')),
    'Fármaco: ' || ingredient[1 + (g % array_length(ingredient, 1))] || '. ' ||
        CASE WHEN g % 7 <= 4 THEN 'Presentación: ' || pres[1 + (g % array_length(pres, 1))] || '. ' ELSE '' END ||
        CASE WHEN g % 3 = 0 THEN 'Venta bajo receta médica. ' ELSE 'Venta libre sin receta. ' END ||
        'Producto farmacéutico registrado en ISP para distribución en farmacias.',
    'FAR-' || UPPER(LEFT(REPLACE(ingredient[1 + (g % array_length(ingredient, 1))], ' ', ''), 6)) || '-' || LPAD(g::text, 6, '0') || '-' || (g % 10),
    ingredient[1 + (g % array_length(ingredient, 1))],
    conc[1 + ((g * 3) % array_length(conc, 1))],
    units[1 + ((g * 5) % array_length(units, 1))] || ' ' || pres[1 + (g % array_length(pres, 1))],
    g % 4 = 0,
    (( (1 + (g % array_length(ingredient, 1))) * 137 +
       (1 + ((g * 3) % array_length(conc, 1))) * 251 +
       (1 + ((g * 5) % array_length(units, 1))) * 73 ) % 40000 + 1500)::decimal(12,2),
    (( (1 + (g % array_length(ingredient, 1))) * 103 +
       (1 + ((g * 3) % array_length(conc, 1))) * 197 +
       (1 + ((g * 5) % array_length(units, 1))) * 61 ) % 28000 + 800)::decimal(12,2),
    ARRAY[
        lower(ingredient[1 + (g % array_length(ingredient, 1))]),
        lower(pres[1 + (g % array_length(pres, 1))]),
        conc[1 + (((g * 3) % array_length(conc, 1)) + 1)],
        CASE WHEN g % 4 = 0 THEN 'receta' ELSE 'otc' END
    ]
FROM generate_series(1, 50000) AS g
CROSS JOIN LATERAL (
    SELECT ARRAY[
        'Paracetamol','Ibuprofeno','Naproxeno Sódico','Ácido Acetilsalicílico','Diclofenaco Sódico',
        'Ketoprofeno','Celecoxib','Tramadol Clorhidrato','Metamizol Sódico','Pregabalina',
        'Amoxicilina Trihidrato','Ciprofloxacino','Azitromicina Dihidrato','Claritromicina','Cefadroxilo Monohidrato',
        'Doxiciclina','Clindamicina','Metronidazol','Nitrofurantoína','Trimetoprima-Sulfametoxazol',
        'Aciclovir','Oseltamivir','Fluconazol','Ketoconazol','Clotrimazol',
        'Loratadina','Cetirizina Diclorhidrato','Desloratadina','Levocetirizina','Clorfenamina Maleato',
        'Omeprazol','Esomeprazol Magnésico','Pantoprazol','Ranitidina','Loperamida Clorhidrato',
        'Simeticona','Domperidona','Metoclopramida','Bromuro de Pinaverio','Sales de Rehidratación Oral',
        'Losartán Potásico','Enalapril Maleato','Amlodipino Besilato','Hidroclorotiazida','Furosemida',
        'Atorvastatina Cálcica','Rosuvastatina Cálcica','Fenofibrato','Ezetimiba','Ácido Acetilsalicílico 100mg',
        'Metformina Clorhidrato','Glibenclamida','Sitagliptina','Empagliflozina','Insulina Glargina',
        'Sertralina','Fluoxetina','Escitalopram','Sulpirida','Mirtazapina',
        'Salbutamol Sulfato','Budesonida','Beclometasona Dipropionato','Fluticasona Propionato','Montelukast Sódico',
        'Hidrocortisona','Betametasona','Clobetasol','Mometasona','Prednisona',
        'Ácido Ascórbico','Colecalciferol','Complejo Vitamínico B','Tiamina','Piridoxina',
        'Cianocobalamina','Ácido Fólico','Biotina','Tocoferol','Retinol',
        'Magnesio Citrato','Zinc Quelado','Hierro Aminoquelado','Calcio + Vitamina D3','Selenio',
        'Omega 3 EPA/DHA','Colágeno Hidrolizado Tipo II','Glucosamina + Condroitina','Proteína de Suero de Leche','Creatina Monohidrato',
        'BCAA 2:1:1','L-Glutamina','L-Carnitina','Beta Alanina','L-Arginina'
    ] AS ingredient,
    ARRAY[
        'Comprimidos','Comprimidos Recubiertos','Comprimidos Efervescentes','Comprimidos Masticables','Comprimidos Sublinguales',
        'Cápsulas','Cápsulas Blandas','Cápsulas de Liberación Prolongada','Jarabe','Suspensión Oral',
        'Gotas Orales','Solución Inyectable','Crema Tópica','Gel Tópico','Ungüento',
        'Spray Nasal','Inhalador','Parche Transdérmico','Óvulos Vaginales','Supositorios'
    ] AS pres,
    ARRAY[
        '100mg','200mg','250mg','400mg','500mg',
        '600mg','750mg','800mg','850mg','875mg',
        '1000mg','10mg','20mg','25mg','40mg',
        '50mg','75mg','100mg/mL','200mg/mL','5mg/mL'
    ] AS conc,
    ARRAY[
        '6','10','12','14','16','20','30','60'
    ] AS units
) AS src
ON CONFLICT (tenant_id, sku) DO NOTHING;

-- =============================================================================
-- 3b. IMÁGENES MASIVAS (50,000) — un placeholder SVG por producto según categoría
-- =============================================================================
INSERT INTO farmacia.product_images (tenant_id, product_id, base64_data, mime_type, is_primary, sort_order)
SELECT
    '00000000-0000-0000-0000-000000000001',
    p.id,
    img.data,
    'image/svg+xml',
    true,
    0
FROM farmacia.products p
CROSS JOIN LATERAL (
    SELECT CASE
        WHEN p.category_id IN ('c2000000-0000-0000-0000-000000000001','c2000000-0000-0000-0000-000000000004','c2000000-0000-0000-0000-000000000006','c2000000-0000-0000-0000-000000000007') THEN 'PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCA4MCA4MCI+PHJlY3QgeD0iMTUiIHk9IjIwIiB3aWR0aD0iMjAiIGhlaWdodD0iMTIiIHJ4PSI2IiBmaWxsPSIjNEE5MEQ5Ii8+PHJlY3QgeD0iMTUiIHk9IjM1IiB3aWR0aD0iMjAiIGhlaWdodD0iMTIiIHJ4PSI2IiBmaWxsPSIjMkM2REI1IiBvcGFjaXR5PSIwLjYiLz48cmVjdCB4PSI0NSIgeT0iMTUiIHdpZHRoPSIxOCIgaGVpZ2h0PSIyMiIgcng9IjkiIGZpbGw9IiNFNzRDM0MiLz48cmVjdCB4PSI0NyIgeT0iMTciIHdpZHRoPSIxNCIgaGVpZ2h0PSIxOCIgcng9IjciIGZpbGw9IiNFQzcwNjMiLz48L3N2Zz4='
        WHEN p.category_id IN ('c2000000-0000-0000-0000-000000000002') THEN 'PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCA4MCA4MCI+PHJlY3QgeD0iMTUiIHk9IjMyIiB3aWR0aD0iMjAiIGhlaWdodD0iMTAiIHJ4PSI1IiBmaWxsPSIjMjdBRTYwIi8+PHJlY3QgeD0iMjUiIHk9IjMyIiB3aWR0aD0iMTAiIGhlaWdodD0iMTAiIHJ4PSI1IiBmaWxsPSIjRjFDNDBGIi8+PHJlY3QgeD0iNDUiIHk9IjI1IiB3aWR0aD0iMTYiIGhlaWdodD0iMjQiIHJ4PSI5IiBmaWxsPSIjMjdBRTYwIi8+PHJlY3QgeD0iNTMiIHk9IjI1IiB3aWR0aD0iOCIgaGVpZ2h0PSIyNCIgcng9IjQiIGZpbGw9IiNGMUM0MEYiLz48L3N2Zz4='
        WHEN p.category_id IN ('c2000000-0000-0000-0000-000000000003') THEN 'PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCA4MCA4MCI+PHJlY3QgeD0iMzAiIHk9IjUiIHdpZHRoPSIyMCIgaGVpZ2h0PSIxMCIgcng9IjIiIGZpbGw9IiM4QjQ1MTMiLz48cmVjdCB4PSIyNSIgeT0iMTUiIHdpZHRoPSIzMCIgaGVpZ2h0PSI1MCIgcng9IjUiIGZpbGw9IiNENEE1NzQiLz48cmVjdCB4PSIyOCIgeT0iMTciIHdpZHRoPSIyNCIgaGVpZ2h0PSI0NCIgcng9IjMiIGZpbGw9IiNGNURFQjMiIG9wYWNpdHk9IjAuNyIvPjx0ZXh0IHg9IjQwIiB5PSI0NSIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZm9udC1zaXplPSIxMCIgZmlsbD0iIzU1NSIgZm9udC1mYW1pbHk9InNhbnMtc2VyaWYiPm1sPC90ZXh0Pjwvc3ZnPg=='
        WHEN p.category_id IN ('c2000000-0000-0000-0000-000000000005') THEN 'PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCA4MCA4MCI+PHJlY3QgeD0iMTUiIHk9IjMyIiB3aWR0aD0iMjAiIGhlaWdodD0iMTAiIHJ4PSI1IiBmaWxsPSIjMjdBRTYwIi8+PHJlY3QgeD0iMjUiIHk9IjMyIiB3aWR0aD0iMTAiIGhlaWdodD0iMTAiIHJ4PSI1IiBmaWxsPSIjRjFDNDBGIi8+PHJlY3QgeD0iNDUiIHk9IjI1IiB3aWR0aD0iMTYiIGhlaWdodD0iMjQiIHJ4PSI5IiBmaWxsPSIjMjdBRTYwIi8+PHJlY3QgeD0iNTMiIHk9IjI1IiB3aWR0aD0iOCIgaGVpZ2h0PSIyNCIgcng9IjQiIGZpbGw9IiNGMUM0MEYiLz48L3N2Zz4='
        WHEN p.category_id IN ('c2000000-0000-0000-0000-000000000008','c2000000-0000-0000-0000-000000000009','c2000000-0000-0000-0000-000000000016') THEN 'PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCA4MCA4MCI+PHJlY3QgeD0iMjUiIHk9IjE1IiB3aWR0aD0iMzAiIGhlaWdodD0iNDUiIHJ4PSI1IiBmaWxsPSIjRjM5QzEyIi8+PHJlY3QgeD0iMjgiIHk9IjE4IiB3aWR0aD0iMjQiIGhlaWdodD0iMzgiIHJ4PSIzIiBmaWxsPSIjRjVDQkE3Ii8+PHJlY3QgeD0iMzAiIHk9IjUiIHdpZHRoPSIyMCIgaGVpZ2h0PSIxMCIgcng9IjMiIGZpbGw9IiNFNjdFMjIiLz48dGV4dCB4PSI0MCIgeT0iNDIiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGZvbnQtc2l6ZT0iMTAiIGZpbGw9IiNEMzU0MDAiIGZvbnQtZmFtaWx5PSJzYW5zLXNlcmlmIiBmb250LXdlaWdodD0iYm9sZCI+VklUPC90ZXh0PjxjaXJjbGUgY3g9IjUwIiBjeT0iMzAiIHI9IjMiIGZpbGw9IiNFNzRDM0MiIG9wYWNpdHk9IjAuNCIvPjxjaXJjbGUgY3g9IjMwIiBjeT0iNDUiIHI9IjIuNSIgZmlsbD0iIzM0OThEQiIgb3BhY2l0eT0iMC40Ii8+PC9zdmc+'
        WHEN p.category_id IN ('c2000000-0000-0000-0000-000000000010') THEN 'PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCA4MCA4MCI+PGNpcmNsZSBjeD0iNDAiIGN5PSIzNSIgcj0iMTgiIGZpbGw9IiNGMUM0MEYiLz48bGluZSB4MT0iNDAiIHkxPSI1IiB4Mj0iNDAiIHkyPSIxNyIgc3Ryb2tlPSIjRjM5QzEyIiBzdHJva2Utd2lkdGg9IjQiLz48bGluZSB4MT0iNDAiIHkxPSI1MyIgeDI9IjQwIiB5Mj0iNjUiIHN0cm9rZT0iI0YzOUMxMiIgc3Ryb2tlLXdpZHRoPSI0Ii8+PGxpbmUgeDE9IjEyIiB5MT0iMzUiIHgyPSIyMiIgeTI9IjM1IiBzdHJva2U9IiNGMzlDMTIiIHN0cm9rZS13aWR0aD0iNCIvPjxsaW5lIHgxPSI2OCIgeTE9IjM1IiB4Mj0iNTgiIHkyPSIzNSIgc3Ryb2tlPSIjRjM5QzEyIiBzdHJva2Utd2lkdGg9IjQiLz48cmVjdCB4PSIyNSIgeT0iNjAiIHdpZHRoPSIzMCIgaGVpZ2h0PSIxNSIgcng9IjUiIGZpbGw9IiMzNDk4REIiLz48L3N2Zz4='
        WHEN p.category_id IN ('c2000000-0000-0000-0000-000000000011','c2000000-0000-0000-0000-000000000012','c2000000-0000-0000-0000-000000000013') THEN 'PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCA4MCA4MCI+PHJlY3QgeD0iMzAiIHk9IjgiIHdpZHRoPSIyMCIgaGVpZ2h0PSIxMiIgcng9IjMiIGZpbGw9IiMzNDk4REIiLz48cGF0aCBkPSJNMjggMjAgTDMyIDY1IEw0OCA2NSBMNTIgMjAgWiIgZmlsbD0iIzg1QzFFOSIvPjxyZWN0IHg9IjMwIiB5PSIxMCIgd2lkdGg9IjIwIiBoZWlnaHQ9IjUiIHJ4PSIyIiBmaWxsPSIjMjk4MEI5Ii8+PC9zdmc+'
        WHEN p.category_id IN ('c2000000-0000-0000-0000-000000000014') THEN 'PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCA4MCA4MCI+PHJlY3QgeD0iMzAiIHk9IjUiIHdpZHRoPSIyMCIgaGVpZ2h0PSIxMCIgcng9IjIiIGZpbGw9IiM4QjQ1MTMiLz48cmVjdCB4PSIyNSIgeT0iMTUiIHdpZHRoPSIzMCIgaGVpZ2h0PSI1MCIgcng9IjUiIGZpbGw9IiNENEE1NzQiLz48cmVjdCB4PSIyOCIgeT0iMTciIHdpZHRoPSIyNCIgaGVpZ2h0PSI0NCIgcng9IjMiIGZpbGw9IiNGNURFQjMiIG9wYWNpdHk9IjAuNyIvPjx0ZXh0IHg9IjQwIiB5PSI0NSIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZm9udC1zaXplPSIxMCIgZmlsbD0iIzU1NSIgZm9udC1mYW1pbHk9InNhbnMtc2VyaWYiPm1sPC90ZXh0Pjwvc3ZnPg=='
        WHEN p.category_id IN ('c2000000-0000-0000-0000-000000000015') THEN 'PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCA4MCA4MCI+PHBhdGggZD0iTTE1IDIwIEw2NSAyMCBMNzAgNTUgUTcwIDcwIDQwIDcwIFExMCA3MCAxMCA1NSBaIiBmaWxsPSIjQUVENkYxIi8+PHBhdGggZD0iTTIwIDIyIEw2MCAyMiBMNjMgNTAgUTYzIDYwIDQwIDYwIFExNyA2MCAxNyA1MCBaIiBmaWxsPSIjRDZFQUY4Ii8+PGVsbGlwc2UgY3g9IjQwIiBjeT0iNDIiIHJ4PSI4IiByeT0iNSIgZmlsbD0iIzg1QzFFOSIgb3BhY2l0eT0iMC41Ii8+PC9zdmc+'
        WHEN p.category_id IN ('c2000000-0000-0000-0000-000000000017') THEN 'PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCA4MCA4MCI+PGNpcmNsZSBjeD0iNDAiIGN5PSIyMiIgcj0iMTgiIGZpbGw9IiNFOERBRUYiLz48Y2lyY2xlIGN4PSI0MCIgY3k9IjIyIiByPSIxNCIgZmlsbD0iI0QyQjRERSIvPjxyZWN0IHg9IjE1IiB5PSI0MCIgd2lkdGg9IjUwIiBoZWlnaHQ9IjE4IiByeD0iMyIgZmlsbD0iI0Y1QjdCMSIvPjxyZWN0IHg9IjE1IiB5PSI0NCIgd2lkdGg9IjUwIiBoZWlnaHQ9IjEwIiByeD0iMiIgZmlsbD0iI0YxOTQ4QSIvPjxsaW5lIHgxPSIyMCIgeTE9IjQ5IiB4Mj0iNjAiIHkyPSI0OSIgc3Ryb2tlPSIjRjVCN0IxIiBzdHJva2Utd2lkdGg9IjEiLz48bGluZSB4MT0iMjAiIHkxPSI1MiIgeDI9IjYwIiB5Mj0iNTIiIHN0cm9rZT0iI0Y1QjdCMSIgc3Ryb2tlLXdpZHRoPSIxIi8+PC9zdmc+'
        WHEN p.category_id IN ('c2000000-0000-0000-0000-000000000018') THEN 'PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCA4MCA4MCI+PHJlY3QgeD0iMTAiIHk9IjEwIiB3aWR0aD0iNjAiIGhlaWdodD0iNDUiIHJ4PSI1IiBmaWxsPSIjMzQ0OTVFIi8+PHJlY3QgeD0iMTUiIHk9IjE1IiB3aWR0aD0iNTAiIGhlaWdodD0iMzAiIHJ4PSIzIiBmaWxsPSIjMkVDQzcxIi8+PHRleHQgeD0iNDAiIHk9IjM0IiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBmb250LXNpemU9IjEyIiBmaWxsPSIjZmZmIiBmb250LWZhbWlseT0ic2Fucy1zZXJpZiIgZm9udC13ZWlnaHQ9ImJvbGQiPjEyMC84MDwvdGV4dD48Y2lyY2xlIGN4PSI0MCIgY3k9IjUwIiByPSI1IiBmaWxsPSIjRUNGMEYxIi8+PHBhdGggZD0iTTM1IDU4IFEyMCA2NSAxNSA3NSIgc3Ryb2tlPSIjN0Y4QzhEIiBzdHJva2Utd2lkdGg9IjMiIGZpbGw9Im5vbmUiLz48cmVjdCB4PSIxNSIgeT0iNjUiIHdpZHRoPSIxMCIgaGVpZ2h0PSIzIiByeD0iMSIgZmlsbD0iIzk1QTVBNiIvPjwvc3ZnPg=='
        ELSE 'PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCA4MCA4MCI+PHJlY3QgeD0iMzIiIHk9IjEwIiB3aWR0aD0iMTYiIGhlaWdodD0iMjUiIHJ4PSI0IiBmaWxsPSIjOEU0NEFEIi8+PHJlY3QgeD0iMzQiIHk9IjEyIiB3aWR0aD0iMTIiIGhlaWdodD0iMjAiIHJ4PSIyIiBmaWxsPSIjRDJCNERFIiBvcGFjaXR5PSIwLjYiLz48cmVjdCB4PSIzNiIgeT0iMzUiIHdpZHRoPSI4IiBoZWlnaHQ9IjUiIHJ4PSIxIiBmaWxsPSIjN0QzQzk4Ii8+PGVsbGlwc2UgY3g9IjQwIiBjeT0iNTAiIHJ4PSI2IiByeT0iOCIgZmlsbD0iI0FGN0FDNSIgb3BhY2l0eT0iMC41Ii8+PC9zdmc+'
    END AS data
) AS img
WHERE p.sku LIKE 'FAR-%'
ON CONFLICT DO NOTHING;

-- =============================================================================
-- 4. INVENTARIO (100,000) — 2 bodegas por producto masivo
-- =============================================================================
INSERT INTO farmacia.inventory (tenant_id, product_id, warehouse_location, batch_number, expiration_date, quantity_available, quantity_reserved, quantity_minimum, last_restock_date, next_restock_eta_days)
SELECT
    '00000000-0000-0000-0000-000000000001',
    p.id,
    wh.name,
    'LOTE-' || UPPER(SUBSTRING(MD5(p.id::text), 1, 8)) || '-' || wh.suffix,
    CURRENT_DATE + ((g % 24) + 6 || ' months')::interval,
    (random() * 500 + 1)::int,
    (random() * 50)::int,
    (random() * 20 + 5)::int,
    NOW() - ((random() * 60)::int || ' days')::interval,
    (random() * 30 + 1)::int
FROM farmacia.products p
CROSS JOIN (VALUES ('Farmacia ZentSalud Santiago Centro', 'A'), ('Farmacia ZentSalud Providencia', 'B'), ('Farmacia ZentSalud Viña del Mar', 'C'), ('Farmacia ZentSalud Concepción', 'D')) AS wh(name, suffix)
CROSS JOIN LATERAL generate_series(1,1) AS g  -- 1 fila; cada producto x cada warehouse = 4 warehouses x 50K = 200K, queremos 100K aprox
WHERE p.sku LIKE 'FAR-%'
  AND random() < 0.5  -- muestreo aleatorio: ~2 warehouses por producto
ON CONFLICT (tenant_id, product_id, warehouse_location, batch_number) DO NOTHING;

-- =============================================================================
-- 5. CLIENTES (25,000)
-- =============================================================================
INSERT INTO farmacia.customers (tenant_id, external_id, rut, name, email, phone, city, region, birth_date, health_insurance_id, loyalty_tier, created_at)
SELECT
    '00000000-0000-0000-0000-000000000001',
    'cust-' || LPAD(g::text, 5, '0'),
    (LPAD((g * 7 + 1000000)::text, 8, '0') || '-' || (g % 10)),
    first_name[1 + (g % array_length(first_name, 1))] || ' ' || last_name1[1 + (g % array_length(last_name1, 1))] || ' ' || last_name2[1 + (g % array_length(last_name2, 1))],
    lower(first_name[1 + (g % array_length(first_name, 1))] || '.' || last_name1[1 + (g % array_length(last_name1, 1))] || (g % 100)) || '@email.cl',
    '+56 9 ' || LPAD((g * 3 + 1000000)::text, 8, '0'),
    (ARRAY['Santiago','Providencia','Las Condes','Viña del Mar','Concepción','La Serena','Antofagasta','Temuco','Valparaíso','Puerto Montt'])[1 + (g % 10)],
    (ARRAY['RM','RM','RM','V','VIII','IV','II','IX','V','X'])[1 + (g % 10)],
    ('1970-01-01'::date + ((g * 17) % 18250 || ' days')::interval),
    (SELECT id FROM farmacia.health_insurance WHERE tenant_id = '00000000-0000-0000-0000-000000000001' OFFSET (g % 8) LIMIT 1),
    CASE WHEN g % 10 = 0 THEN 'gold' WHEN g % 5 = 0 THEN 'silver' ELSE 'bronce' END,
    NOW() - ((g % 730) || ' days')::interval
FROM generate_series(1, 25000) AS g
CROSS JOIN LATERAL (
    SELECT ARRAY[
        'María','Carmen','Ana','Rosa','Patricia','Claudia','Carolina','Francisca','Valentina','Daniela',
        'Juan','Carlos','Luis','José','Jorge','Pedro','Eduardo','Manuel','Roberto','Miguel',
        'Sofía','Isabella','Camila','Gabriel','Diego','Pablo','Fernando','Ricardo','Alejandro','Felipe',
        'Andrea','Verónica','Javiera','Constanza','Antonia','Catalina','Florencia','Martín','Nicolás','Cristóbal'
    ] AS first_name,
    ARRAY[
        'González','Muñoz','Rojas','Díaz','Pérez','Soto','Contreras','Silva','Martínez','López',
        'Fernández','Morales','Valenzuela','Araya','Herrera','Riquelme','Cáceres','Bustamante','Vega','Tapia',
        'Leiva','Farías','Guzmán','Espinoza','Fuentes','Carrasco','Figueroa','Ortiz','Pizarro','Cortés'
    ] AS last_name1,
    ARRAY[
        'Pérez','González','Rodríguez','López','Martínez','Sánchez','Ramírez','Torres','Flores','Rivera',
        'Gómez','Hernández','Moreno','Jiménez','Ruiz','Álvarez','Castillo','Navarro','Vásquez','Mendoza'
    ] AS last_name2
) AS names
ON CONFLICT (tenant_id, external_id) DO NOTHING;

-- =============================================================================
-- 6. RECETAS MÉDICAS (5,000)
-- =============================================================================
INSERT INTO farmacia.prescriptions (tenant_id, prescription_code, patient_rut, patient_name, doctor_name, doctor_rut, diagnosis, observations, issue_date, expiration_date)
SELECT
    '00000000-0000-0000-0000-000000000001',
    'RX-2026-' || LPAD(g::text, 6, '0'),
    (LPAD(((g * 7 + 1000000) % 25000000)::text, 8, '0') || '-' || (g % 10)),
    'Paciente ' || g,
    dr_name[1 + (g % array_length(dr_name, 1))],
    (LPAD(((g * 13 + 5000000) % 25000000)::text, 8, '0') || '-' || ((g * 3) % 10)),
    diag[1 + (g % array_length(diag, 1))],
    CASE WHEN g % 3 = 0 THEN 'Control en 30 días. Ajustar dosis según respuesta.' WHEN g % 3 = 1 THEN 'No suspender tratamiento bruscamente.' ELSE 'Mantener dosis indicada.' END,
    ('2026-01-01'::date + ((g * 7) % 210 || ' days')::interval),
    ('2026-01-08'::date + ((g * 7) % 210 + 30 || ' days')::interval)
FROM generate_series(1, 5000) AS g
CROSS JOIN LATERAL (
    SELECT ARRAY[
        'Dr. Andrés Valenzuela Muñoz','Dra. María Teresa Barrientos','Dr. Juan Carlos Morales R.',
        'Dra. Carolina Espinoza Tapia','Dr. Roberto Martínez Herrera','Dra. Paulina Figueroa Soto',
        'Dr. Fernando Gómez Leiva','Dra. Alejandra Pizarro Cortés','Dr. Ricardo Fuentes Araya',
        'Dra. Marcela Vásquez Toledo','Dr. Eduardo Navarro Villalobos','Dra. Ximena Castillo Rojas',
        'Dr. Patricio Mendoza Díaz','Dra. Lorena Torres Contreras','Dr. Felipe Cáceres Herrera',
        'Dra. Daniela Rojas Bustamante','Dr. Cristián López Carrasco','Dra. Tamara Ortiz Flores',
        'Dr. Sebastián Guzmán Pérez','Dra. Bárbara Silva González'
    ] AS dr_name,
    ARRAY[
        'Hipertensión arterial esencial grado 1','Hipertensión arterial grado 2 no controlada',
        'Diabetes mellitus tipo 2 + dislipidemia mixta','Hipotiroidismo primario',
        'Asma bronquial persistente moderada','EPOC leve-moderado',
        'Depresión mayor recurrente','Trastorno de ansiedad generalizada',
        'Artritis reumatoide seropositiva','Osteoartritis de rodilla bilateral',
        'Gastritis crónica por H. pylori','Reflujo gastroesofágico grado B',
        'Rinitis alérgica perenne','Urticaria crónica idiopática',
        'Infección urinaria baja recurrente','Faringoamigdalitis bacteriana aguda',
        'Sinusitis aguda bacteriana','Otitis media aguda supurada',
        'Dermatitis atópica moderada-severa','Psoriasis en placas'
    ] AS diag
) AS med
ON CONFLICT (tenant_id, prescription_code) DO NOTHING;

-- =============================================================================
-- 7. VENTAS (50,000) — optimizado sin subqueries correlacionados
-- =============================================================================
TRUNCATE farmacia.sales CASCADE;

INSERT INTO farmacia.sales (tenant_id, product_id, customer_id, quantity, unit_price, total_amount, payment_method, payment_amount, health_insurance_id, insurance_covered_amount, prescription_id, order_status, sale_date, channel)
SELECT
    '00000000-0000-0000-0000-000000000001'::uuid,
    prod_ids[1 + (g % 50000)],
    'cust-' || LPAD(((g * 7) % 25000 + 1)::text, 5, '0'),
    (g % 3 + 1),
    ((g * 17 + 500 * (g % 50) + 1000) % 40000 + 1500)::decimal(12,2),
    ((g % 3 + 1) * ((g * 17 + 500 * (g % 50) + 1000) % 40000 + 1500))::decimal(14,2),
    (ARRAY['Efectivo','Débito','Tarjeta Crédito','Transferencia'])[1 + (g % 4)],
    ((g % 3 + 1) * ((g * 17 + 500 * (g % 50) + 1000) % 40000 + 1500))::decimal(14,2),
    hi_ids[1 + (g % 8)],
    0.00,
    CASE WHEN g % 8 = 0 THEN rx_ids[1 + (g % 5000)] ELSE NULL END,
    CASE WHEN g % 20 = 0 THEN 'cancelled' WHEN g % 50 = 0 THEN 'refunded' ELSE 'completed' END,
    NOW() - ((g % 365) || ' days')::interval,
    (ARRAY['presencial','presencial','presencial','web','app'])[1 + (g % 5)]
FROM generate_series(1, 50000) AS g
CROSS JOIN LATERAL (
    SELECT ARRAY(SELECT id FROM farmacia.products WHERE sku LIKE 'FAR-%' ORDER BY id) AS prod_ids
) AS p
CROSS JOIN LATERAL (
    SELECT ARRAY(SELECT id FROM farmacia.health_insurance WHERE tenant_id = '00000000-0000-0000-0000-000000000001' ORDER BY id) AS hi_ids
) AS hi
CROSS JOIN LATERAL (
    SELECT ARRAY(SELECT id FROM farmacia.prescriptions WHERE tenant_id = '00000000-0000-0000-0000-000000000001' ORDER BY id) AS rx_ids
) AS rx;

-- =============================================================================
-- 8. RESEÑAS DE PRODUCTOS (150,000)
-- =============================================================================
TRUNCATE farmacia.product_reviews CASCADE;

INSERT INTO farmacia.product_reviews (tenant_id, product_id, customer_id, rating, title, comment, is_verified_purchase, helpful_count, created_at)
SELECT
    '00000000-0000-0000-0000-000000000001'::uuid,
    prod_ids[1 + (g % 50000)],
    'cust-' || LPAD(((g * 3) % 25000 + 1)::text, 5, '0'),
    CASE
        WHEN g % 10 = 0 THEN 1 WHEN g % 10 <= 2 THEN 2
        WHEN g % 10 <= 4 THEN 3 WHEN g % 10 <= 7 THEN 4
        ELSE 5
    END,
    titles[1 + (g % array_length(titles, 1))],
    comments[1 + (g % array_length(comments, 1))],
    g % 3 != 0,
    g % 200,
    NOW() - ((g % 365) || ' days')::interval
FROM generate_series(1, 150000) AS g
CROSS JOIN LATERAL (
    SELECT ARRAY(SELECT id FROM farmacia.products WHERE sku LIKE 'FAR-%' ORDER BY id) AS prod_ids
) AS p
CROSS JOIN LATERAL (
    SELECT ARRAY[
        'Excelente medicamento','Muy efectivo','Mejoró mis síntomas','Bueno pero caro','No vi resultados',
        'Lo recomiendo totalmente','Regular nada más','Me causó efectos secundarios','Salvador','Cumple lo que promete',
        'Económico y bueno','Malo no me gustó','Increíble cambio','No me funcionó','Bastante bien',
        'Superó mis expectativas','Calidad precio insuperable','Me arrepentí de la compra','Lo volvería a comprar','No lo recomiendo',
        'Efecto rápido','Demora en hacer efecto','Mejor que la competencia','Debería ser más barato','Producto imprescindible',
        'Buen sabor','Fácil de tomar','Difícil de tragar','Envase práctico','Presentación mejorable'
    ] AS titles,
    ARRAY[
        'Lo compré por recomendación de mi médico y en 3 días ya noté mejoría. Excelente calidad del laboratorio.',
        'Llevo usando este medicamento por meses y nunca me ha fallado. Controla mis síntomas perfectamente.',
        'Me lo recetaron en urgencias y funcionó rapidísimo. Ya lo tengo siempre en mi botiquín.',
        'El precio me pareció elevado comparado con otras farmacias, pero la calidad lo compensa.',
        'No noté diferencia después de una semana de uso. Quizás necesito más tiempo.',
        'Mi farmacéutico de confianza me lo recomendó y no se equivocó. Producto de primera calidad.',
        'Hace lo que dice pero esperaba más por el precio que pagué. Hay opciones más económicas.',
        'Me dio dolor de estómago los primeros días pero después se me pasó. El efecto terapéutico es bueno.',
        'Sufría de esto por años y ningún tratamiento me funcionaba hasta que probé este producto.',
        'Lo uso para toda la familia. Mi esposa y mis hijos también lo toman cuando se enferman.',
        'Compré la versión genérica antes y no es lo mismo. Este de laboratorio reconocido es muy superior.',
        'Llevo 15 días de tratamiento y los análisis de laboratorio ya muestran mejoría significativa.',
        'El envase es muy cómodo, cabe en cualquier cartera y las instrucciones son muy claras.',
        'Tenía dudas por ser un laboratorio que no conocía, pero me sorprendió para bien.',
        'Lo compro regularmente para mi mamá que es adulta mayor. Ella lo tolera muy bien.',
        'La presentación de 30 comprimidos es ideal, dura todo el mes sin tener que volver a comprar.',
        'Me molestó que no viniera con prospecto en español. Tuve que buscar las indicaciones en internet.',
        'Después de 2 meses de uso continuo mis síntomas han disminuido un 80%. Muy agradecida.',
        'El formato en jarabe es mucho más fácil de administrar que los comprimidos, sobre todo para niños.',
        'Tuve una reacción alérgica leve el primer día. Suspendí y consulté a mi médico. No era para mí.'
    ] AS comments
) AS review_texts;

-- =============================================================================
-- 9. VISTA MATERIALIZADA
-- =============================================================================
DROP VIEW IF EXISTS farmacia.vw_product_catalog;
DROP MATERIALIZED VIEW IF EXISTS farmacia.vw_product_catalog;

CREATE MATERIALIZED VIEW farmacia.vw_product_catalog AS
SELECT
    p.id, p.name, p.sku, p.active_ingredient, p.concentration, p.presentation_unit,
    p.requires_prescription, p.registration_number, p.price, p.description, p.tags,
    s.name AS supplier,
    c.name AS category,
    pc.name AS parent_category,
    COALESCE(sls.total_sold, 0) AS units_sold,
    COALESCE(sls.total_revenue, 0) AS total_revenue,
    COALESCE(rev.avg_rating, 0) AS avg_rating,
    COALESCE(rev.review_count, 0) AS review_count,
    COALESCE(inv.total_stock, 0) AS in_stock
FROM farmacia.products p
LEFT JOIN farmacia.suppliers s ON p.supplier_id = s.id
LEFT JOIN farmacia.categories c ON p.category_id = c.id
LEFT JOIN farmacia.categories pc ON c.parent_id = pc.id
LEFT JOIN (
    SELECT product_id, SUM(quantity) AS total_sold, SUM(total_amount) AS total_revenue
    FROM farmacia.sales WHERE order_status = 'completed' GROUP BY product_id
) sls ON p.id = sls.product_id
LEFT JOIN (
    SELECT product_id, ROUND(AVG(rating), 1) AS avg_rating, COUNT(*) AS review_count
    FROM farmacia.product_reviews GROUP BY product_id
) rev ON p.id = rev.product_id
LEFT JOIN (
    SELECT product_id, SUM(quantity_available - quantity_reserved) AS total_stock
    FROM farmacia.inventory GROUP BY product_id
) inv ON p.id = inv.product_id;

-- =============================================================================
-- Stats
-- =============================================================================
DO $$
BEGIN
    RAISE NOTICE '=== FARMACIA ZENTSALUD — DATA GENERATION COMPLETE ===';
    RAISE NOTICE 'Products: %', (SELECT COUNT(*) FROM farmacia.products);
    RAISE NOTICE 'Sales: %', (SELECT COUNT(*) FROM farmacia.sales);
    RAISE NOTICE 'Inventory: %', (SELECT COUNT(*) FROM farmacia.inventory);
    RAISE NOTICE 'Reviews: %', (SELECT COUNT(*) FROM farmacia.product_reviews);
    RAISE NOTICE 'Customers: %', (SELECT COUNT(*) FROM farmacia.customers);
    RAISE NOTICE 'Prescriptions: %', (SELECT COUNT(*) FROM farmacia.prescriptions);
    RAISE NOTICE 'Suppliers: %', (SELECT COUNT(*) FROM farmacia.suppliers);
    RAISE NOTICE 'Health Insurance: %', (SELECT COUNT(*) FROM farmacia.health_insurance);
END $$;
