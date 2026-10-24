# Evidencia P11

| Archivo | Resultado |
|---|---|
| `junit-p11.xml` | 3 passed — cola de operación, prioridad y API tenant-scoped |

## Estado

- `GET /workflows/operations/queue` sobre `workflow_instances`; sin estado nuevo.
- Cola de fallos, expirados, suspendidos, aprobaciones y esperas humanas.
- Priorización por antigüedad y fault; acción recomendada segura.
- UI de Operación muestra la cola real.
- Timeline y acciones existentes mantienen redacción/workspace.

## No verificado

- Presupuesto concurrente por tenant/workflow/rol.
- Drill real de caída de Redis/Postgres.
- Retry automático de efectos (no existe por diseño).
