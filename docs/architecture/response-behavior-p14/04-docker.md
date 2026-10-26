# P14 — Docker local

Imágenes reconstruidas con P14:

```powershell
docker compose build api ingestion-worker portal
docker compose up -d api ingestion-worker portal
```

Verificación:

| Componente | Estado |
|---|---|
| `rag-api` | healthy, `ZENT_GOLD_RELEASE_ENABLED=False` |
| `rag-portal` | healthy |
| `rag-ingestion-worker` | running |
| PostgreSQL | healthy |
| `alembic_version` | `173` (P14 no agrega migraciones) |

E2E ejecutado contra el stack real (`http://127.0.0.1:8080`):

```powershell
cd portal
$env:E2E_EXTERNAL="1"
$env:E2E_BASE_URL="http://127.0.0.1:8080"
npx playwright test e2e/agent-response-profiles.spec.ts
```

Resultado: **1 passed**. Valida catálogo, selección de Conciso, guardado,
`profile_id`/`structure_policy` por API y persistencia tras recarga.

No se ejecutó preview/comparador contra un proveedor LLM real porque el stack
local no tiene credenciales de proveedor; esos caminos están cubiertos con
adaptadores simulados y tests de API.
