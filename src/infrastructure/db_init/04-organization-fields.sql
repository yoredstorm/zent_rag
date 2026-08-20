-- =============================================================================
-- Organization Fields - Información de empresa para billing
-- =============================================================================
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS company_name VARCHAR(255);
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS ruc VARCHAR(20);
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS phone VARCHAR(30);
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS email VARCHAR(255);
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS country VARCHAR(100);

-- Actualizar dev organization con datos de ejemplo
UPDATE organizations SET
    company_name = 'ZentTech Demo',
    ruc = '12345678-9',
    phone = '+56912345678',
    email = 'demo@zenttech.com',
    country = 'CL'
WHERE id = '00000000-0000-0000-0000-000000000001'
AND company_name IS NULL;
