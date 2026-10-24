# Evidencia P02

Base: `0cbb494ce4264077a1e6d4823f4520fbc32928b9` + P00/P01.

| Archivo | Resultado |
|---|---|
| `junit-ingress.xml` | 7 passed — manual WAIT, schedule idempotente, hook duplicado, event duplicado, event draft bloqueado, retry pendiente, claim huérfano |
| `junit-workflows.xml` | 440 passed — suite `test_workflow_*.py` completa (1667 s) |
| `junit-gold-restart.xml` | 2 passed — Gold ventas end-to-end + reinicio con venta exacta (779.5 s) |
| `junit-red-xfail.xml` / `junit-red-proof.xml` | 4 xfailed / 4 failed — workspace y policy siguen abiertos |

## Estado

- Migraciones 163→164→165→166 aplicadas en base local.
- PostgreSQL local se levantó con `pg_ctl` (el servicio Windows está detenido).
- No se ejecutaron proveedores reales ni pagos.

## No verificado

- Redis caído / replay del bus: `NOT_VERIFIED`; el bus sigue siendo pub/sub sin
  outbox. Webhooks/schedule ya persisten en Postgres antes de procesar.
- Playwright y suite completa del portal no se reejecutaron en P02.
