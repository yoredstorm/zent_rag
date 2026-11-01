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

Datos sintéticos. No usar como producción.

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
