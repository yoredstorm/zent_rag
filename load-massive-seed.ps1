# Script para cargar el seed masivo contra PostgreSQL (1.2M+ registros)
# Tiempo estimado: 3-10 minutos

Write-Host "=== Cargando datos masivos para pruebas de rendimiento ==="
Write-Host "  - 100,000 productos"
Write-Host "  - 1,200,000 ventas"
Write-Host "  - 300,000 reseñas"
Write-Host "  - 50,000 clientes"
Write-Host "  - 200,000 registros de inventario"
Write-Host ""

docker exec rag-postgres psql -U rag_user -d rag_platform -c "SELECT 'Iniciando carga masiva...' AS status;"

# Copiar el archivo SQL al contenedor y ejecutarlo
docker cp "src/infrastructure/db_init/05-massive-seed-performance.sql" rag-postgres:/tmp/seed.sql
docker exec rag-postgres psql -U rag_user -d rag_platform -f /tmp/seed.sql

Write-Host ""
Write-Host "=== VERIFICACIÓN ==="
docker exec rag-postgres psql -U rag_user -d rag_platform -c "SELECT 'Products' AS tabla, count(*) FROM retail.products UNION ALL SELECT 'Sales', count(*) FROM retail.sales UNION ALL SELECT 'Reviews', count(*) FROM retail.product_reviews UNION ALL SELECT 'Customers', count(*) FROM retail.customers UNION ALL SELECT 'Inventory', count(*) FROM retail.inventory;"
