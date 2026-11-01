# P19-06 — Conector PostgreSQL externo y certificación local

- **Estado:** `external_postgres` CERTIFIED LOCAL para lectura; otros dialectos
  NOT_SUPPORTED.
- **Base externa:** `ops/p19-external`, fuera del compose de ZENT.
- **Conexión:** `host.docker.internal:55432` desde `rag-api`; `127.0.0.1:55432`
  desde el host.
- **Credencial:** usuario `p19_reader` read-only; password en `.env` local no
  versionado.

## 1. Base externa creada

| Elemento | Valor |
|---|---|
| Proyecto compose | `p19-external` (separado de `zent_rag`) |
| Contenedor | `p19-external-postgres` |
| Imagen | `postgres:16` |
| Puerto host | `55432` |
| Red | `p19-external-net` propia |
| Volumen | `p19_external_p19_external_data` |
| DB | `zent_external_mvp` |
| Admin | `p19_admin` (solo init) |
| Runtime | `p19_reader` con `default_transaction_read_only=on` |
| Schemas | `catalog`, `loyalty`, `sales` |

Fixtures sintéticas:

- `catalog.product_prices`: ARR-001 retail 5.00 PEN, ARR-002 6.50 PEN,
  ARR-001 wholesale 4.50 PEN, EXP-001 vencido, USD-001 en USD.
- `loyalty.loyalty_balances`: CUST-A 120, CUST-B 40, CUST-C inactivo.
- `sales.orders`: ORD-1001 shipped, ORD-1002 delivered, ORD-2001 pending.

No son datos de clientes reales.

## 2. Adaptador implementado

`src/platform/workflows/bindings.py::_execute_connected_select`:

- Solo acepta plan canónico `zent.data.query.binding/v1`; legacy connected_db
  no se ejecuta.
- `connection_ref` es el `connectors.id` autorizado del tenant/workspace.
- Verifica organización, workspace y estado `active`.
- Solo `postgres`/`postgresql`; cualquier otro dialecto devuelve
  `PROVIDER_NOT_SUPPORTED`.
- Credencial desde Secret Store; nunca se devuelve en output ni logs.
- Engine aislado `pool_size=1`, `max_overflow=0`, `pool_pre_ping`, dispose al
  terminar.
- `default_transaction_read_only=on` + `statement_timeout` del plan.
- Reutiliza el mismo compilador/ejecutor del plan de P19-01; no hay SQL nuevo.
- SSL opcional por `config.ssl`.
- Errores: `RESOURCE_NOT_EXPOSED`, `NEEDS_CONFIGURATION`, `NEEDS_CREDENTIALS`,
  `PROVIDER_NOT_SUPPORTED`, `TIMEOUT`, `CONNECTION_FAILED`.

## 3. Catálogo y UI

- `GET /api/v1/workflows/data-sources` incluye `connector:<uuid>` con estado
  `CONNECTED`/`DEGRADED`.
- `GET .../resources` incluye los recursos de planes `connected_db`.
- `GET .../schema` para conector devuelve columnas del plan con
  `introspected=false`; la introspección física completa queda pendiente.
- `POST /data-query/preview` ejecuta el plan externo con los mismos límites y
  redacción.

## 4. Tenant demo

- Portal: `p19.demo@example.com` / `P19Demo!2026`.
- Organización: `P19 External MVP`.
- Conector: “ERP externo P19”.
- Planes publicados: `p19.external.price`, `p19.external.loyalty`,
  `p19.external.order`.

La contraseña de la DB externa está en `ops/p19-external/.env` (ignorado por
git). Cambiarla antes de cualquier uso fuera de desarrollo.

## 5. Pruebas

```powershell
$env:P19_EXTERNAL_HOST="127.0.0.1"
$env:P19_EXTERNAL_PORT="55432"
$env:P19_EXTERNAL_DB="zent_external_mvp"
$env:P19_EXTERNAL_USER="p19_reader"
$env:P19_EXTERNAL_PASSWORD="p19_reader_dev_2026"
.\.venv\Scripts\python.exe -m pytest tests/test_workflow_data_p19_external.py -q
```

Resultado: **2 passed**.

- Lee `ARR-001` desde `catalog.product_prices` sin Managed DB.
- Inyección `ARR-001' OR 1=1 --` devuelve `NOT_FOUND`.
- Conector inexistente devuelve `RESOURCE_NOT_EXPOSED`.
- Host y API container conectan por IP/puerto; `p19_reader` solo lee.

Matriz:

| Tecnología | Estado |
|---|---|
| `managed_postgres` | CERTIFIED LOCAL (P19-01) |
| `external_postgres` | CERTIFIED LOCAL (P19-06) |
| MySQL | NOT_SUPPORTED |
| SQL Server | NOT_SUPPORTED |
| Oracle | NOT_SUPPORTED |
| DB2 | NOT_SUPPORTED |

## 6. Límites

- La introspección de schema externo usa el plan, no `information_schema`
  completo (`introspected=false`).
- No hay allowlist de host/red para SSRF más allá de la configuración
  administrativa del conector.
- No hay rotación automática de credenciales ni health check programado.
- No hay pool compartido por tenant; se crea y destruye por consulta.
- No hay prueba TLS real.
- Otros dialectos no se declaran soportados.

## 7. Rollback

- `docker compose -f ops/p19-external/docker-compose.yml down` detiene la base
  externa; `down -v` elimina el volumen sintético.
- Revertir `_execute_connected_select` y el dispatch `connected_db` restaura
  `PROVIDER_NOT_SUPPORTED`.
- Los bindings externos quedan inertes; no se borran workflows ni datos de ZENT.

## 8. Veredicto

**P19-06 COMPLETADO para PostgreSQL externo local.** La conexión es real por
IP/puerto/usuario/password, fuera del compose de ZENT. No se certifican otros
dialectos ni producción.
