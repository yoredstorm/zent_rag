# 13 — P11: Operations Console y recuperación

Fecha: `2026-10-23`. Base: `0cbb494ce4` + P00–P10.

## 1. Cola de operación

`GET /api/v1/workflows/operations/queue` proyecta `workflow_instances` sin crear
estado ni scheduler nuevo. Incluye:

- `FAILED` y `EXPIRED`;
- `SUSPENDED`;
- `WAITING` con evento humano/aprobación;
- `retry_scheduled`.

Cada item trae `kind`, `fault`, `recommended_action`, antigüedad, business key y
workspace. `build_operations_queue` es la función pura de priorización; no
incluye el `state` para no filtrar datos sensibles.

La UI de Operación muestra la cola real y mantiene la línea de tiempo
`project_business_timeline` ya redactada. Las acciones disponibles son las
existentes: cancelar, suspender y reanudar; no se añadió un “retry pagos” ni un
segundo bus.

## 2. Timeline y acciones seguras

- `GET /instances/{id}/timeline` devuelve runs, señales, eventos y
  `business_timeline`; payloads con secretos se redactan.
- Cancelar/suspender/reanudar exigen `workflows:run` y respetan workspace.
- Un fallo de política se clasifica `policy`; contrato, confianza y configuración
  tienen categorías propias.
- No se reejecuta un pago desde la consola: la recuperación segura es cancelar y
  abrir una nueva ejecución idempotente.

## 3. Métricas y SLO

`record_transition` mantiene el contador Prometheus existente
`zent_workflow_operations_total` (`workflow_start`, `success`, `failure`,
`waits`, `expired`, `cancelled`). Los dashboards/alertas siguen en el stack
existente (Prometheus/Grafana/Loki); P11 no crea otro colector.

SLO propuestos para staging: procesos WAIT reanudados < 5 min al recibir señal;
cola de fallos revisada < 1 día; 0 señales duplicadas con efecto; 0 acciones
cruzadas de workspace. El runbook de recuperación está en la sección 5.

## 4. Presupuestos concurrentes

El presupuesto del planner y de runs existentes sigue vigente. **No se añadió
un presupuesto concurrente por tenant/workflow/rol en P11**; queda `NOT_VERIFIED`
y no se declara implementado. La cola sí expone la presión operativa real.

## 5. Runbook de recuperación

1. **Cola**: abrir `/operations`, filtrar `failed`/`needs_human`.
2. **Diagnóstico**: abrir timeline; revisar `fault`, nodo y señal. No copiar
   payloads sensibles.
3. **Acción segura**: suspender/cancelar; para una nueva ejecución usar la
   entrada idempotente del workflow, no reenviar el webhook a ciegas.
4. **Infra**: si PostgreSQL/Redis caen, el proceso queda `WAITING`/`FAILED`; no
   se marca éxito. Tras recuperar dependencias, reintentar la entrada con la
   misma idempotency key y verificar que no se duplicó el efecto.
5. **Evidencia**: conservar JUnit/timeline y reportar `UNVERIFIED` si no hubo
   prueba real.

## 6. Pruebas

| Comando | Resultado |
|---|---|
| `pytest tests/test_workflow_operations_queue.py -q` | **3 passed** |
| `ruff check src/platform/workflows/operations.py src/api/routes/workflows.py` | OK |
| Portal `npm run typecheck` | OK |

Cubre cola, prioridad de fallos/espera humana, exclusión de completados y API
vacía tenant-scoped.

## 7. Límites

- Sin presupuesto concurrente por tenant/workflow/rol.
- Sin simulación de caída real de Redis/Postgres en este corte; el runbook y los
  tests existentes de resiliencia no equivalen a un drill ejecutado.
- El “retry” automático de efectos no existe por diseño: la consola es segura,
  no un segundo motor.
- Sin proveedor real ni alertas desplegadas en staging desde este entorno.

## 8. Dictamen

**GO P11 staging parcial** en cola, timeline, acciones seguras y métrica
existente. **NO-GO release:** presupuestos concurrentes y drills reales de
infraestructura siguen pendientes.
