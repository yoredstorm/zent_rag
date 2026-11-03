# P19 external PostgreSQL

Base PostgreSQL 16 fuera del compose de ZENT, para probar `connected_db` real.

## Arranque

```powershell
cd ops/p19-external
docker compose --env-file .env -f docker-compose.yml up -d
```

- Host: `127.0.0.1`
- Puerto: `55432`
- DB: `zent_external_mvp`
- Runtime: `p19_reader` / password en `.env`
- Admin: `p19_admin` / password en `.env`

Desde `rag-api` el host es `host.docker.internal` y el puerto `55432`.

## Contenido

- `catalog.product_prices`
- `loyalty.loyalty_balances`
- `sales.orders`
- `bodega.products` (30 productos peruanos)
- `bodega.stock`, `bodega.stock_movements`, `bodega.orders`, `bodega.order_items`

Datos sintéticos. No usar como producción.

## Bodega y flujo de aprobación

```powershell
docker cp ops/p19-external/bodega.sql p19-external-postgres:/tmp/bodega.sql
docker exec -e PGPASSWORD=p19_admin_dev_2026 p19-external-postgres `
  psql -U p19_admin -d zent_external_mvp -f /tmp/bodega.sql

$env:ORG_ID="<organization-uuid>"
$env:WORKSPACE_ID="<workspace-uuid>"
$env:P19_EXTERNAL_HOST="host.docker.internal"
$env:P19_EXTERNAL_PORT="55432"
$env:P19_EXTERNAL_USER="p19_reader"
$env:P19_EXTERNAL_PASSWORD="<reader-password>"
$env:P19_WRITER_USER="p19_writer"
$env:P19_WRITER_PASSWORD="<writer-password>"
.\.venv\Scripts\python.exe ops\p19-external\seed_tenant.py
.\.venv\Scripts\python.exe ops\p19-external\create_bodega_workflow.py
```

`create_bodega_workflow.py` crea el workflow, inicia el pedido y muestra la
aprobación pendiente. Aprobarla en el portal descuenta stock de forma
idempotente.

## Publicar en un tenant

```powershell
$env:PYTHONPATH="D:\zent_RAG"
$env:ORG_ID="<organization-uuid>"
$env:WORKSPACE_ID="<workspace-uuid>"
$env:P19_EXTERNAL_HOST="host.docker.internal"
$env:P19_EXTERNAL_PORT="55432"
$env:P19_EXTERNAL_DB="zent_external_mvp"
$env:P19_EXTERNAL_USER="p19_reader"
$env:P19_EXTERNAL_PASSWORD="<password>"
.\.venv\Scripts\python.exe ops\p19-external\seed_tenant.py
```

Crea el conector y publica `p19.external.price`, `p19.external.loyalty` y
`p19.external.order`.

## Apagar

```powershell
docker compose -f docker-compose.yml down
```

`down -v` elimina el volumen sintético.
