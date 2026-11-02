# P19.1-07 — Inventario: adaptador, reservas y efectos

- **Estado:** PARTIAL. SQL extraído del core, idempotencia corregida, barrido
  periódico y batch atómico agregados; doble commit/chaos y E2E de crash
  pendientes.

## Hallazgo AS-IS

- `_execute_inventory_action` vivía en `bindings.py` con SQL `bodega.*`.
- `reserve:order:sku` no incluía cantidad/línea/versión; un reintento con otra
  cantidad devolvía `quantity` del payload aunque la reserva existente tuviera
  otra.
- El barrido de expiradas era perezoso dentro de cada operación; no había job.
- No había operación multi-ítem atómica.
- `payment_status`/`order.status` eran estados separados, pero el commit los
  mezclaba con `payment_status='approved_manual'`.

## Implementado

- `src/platform/workflows/inventory_adapter.py`:
  - `execute_inventory_action` con reserve/commit/release;
  - `_execute_inventory_action` en core solo delega;
  - `ALREADY_RESERVED` devuelve la cantidad real de la reserva y la solicitada;
  - `expire_inventory_reservations` con `pg_try_advisory_xact_lock`,
    `FOR UPDATE SKIP LOCKED` y batch.
- `src/scripts/expire_inventory_reservations.py` como entrypoint de cron/worker.
- `reserve_stock_batch` reserva varias líneas en una transacción; todo o nada.
- Invariantes conservadas: `available = on_hand - reserved`, row locks, TTL con
  `NOW()` de DB, ledger `UNIQUE(idempotency_key)`, commit consume una sola vez.

## Pruebas

| Caso | Resultado | Evidencia |
|---|---|---|
| Suite P19 existente (incluye bodega) | PASS | `test_workflow_data_p19_*` |
| External PostgreSQL | PASS | `test_workflow_data_p19_external.py` |
| 100 operaciones, concurrencia 20, stock 10 | PASS: 10 reserved, 90 CONFLICT, reserved=10, active=10, sin negativo | `scripts/cert/p19_inventory_concurrency.py` |
| Doble commit simultáneo | NOT_RUN | falta test concurrente PostgreSQL |
| Multi-ítem atómico | PASS unitario (validación); falta E2E | `reserve_stock_batch` |
| Job de expiración | PARTIAL | función + script; cron no conectado |
| Crash/reboot worker | NOT_RUN | pendiente |
| Garantía `available >= 0` en DB | PARTIAL | CHECK `reserved >=0`; falta constraint que ligue `on_hand - reserved` |

## Rutas/efectos

- `inventory` provider en `execute_binding`.
- `reserve_stock`, `commit_stock`, `release_stock`.
- Script de expiración.
- Trazabilidad: reservation ID, order, SKU, TTL, estado, movement/ALREADY_APPLIED.

## Compatibilidad y rollback

- Sin migración nueva; el adaptador usa el esquema `bodega.*` existente.
- Rollback restaura el core con SQL embebido; no borra datos.
- El script de expiración es opcional y no cambia la semántica si no se agenda.

## Riesgos residuales

- Multi-ítem no es atómico; un fallo parcial requiere compensación manual.
- La clave de idempotencia sigue siendo `reserve:order:sku`; una segunda línea
  del mismo SKU en el mismo pedido no está representada.
- `commit` cambia `payment_status='approved_manual'` sin separar
  `payment_authorized`/`captured`; no hay pasarela real.
- Falta job con leader election real y métricas de expiración.
- Faltan pruebas de deadlock, redelivery y reconciliación ledger vs stock.
