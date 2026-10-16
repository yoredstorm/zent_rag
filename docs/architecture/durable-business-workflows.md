# Workflows de negocio durables (WorkflowInstance)

Estado: implementado (migraciones 153–156)
Fecha: 2026-10-16

## Principio

```
AGENT UNDERSTANDS. WORKFLOW OWNS STATE. ADDONS EXECUTE. EVENTS RESUME.
```

El motor v2 (`execute_graph`) sigue siendo el único scheduler de ejecución.
Por encima se añade una entidad durable que representa el proceso de negocio
vivo: **WorkflowInstance**. Los runs dejan de ser el proceso; son *segmentos*
ejecutados entre checkpoints.

```
WorkflowDefinition (workflows.graph)   qué debe ocurrir (portable)
WorkflowInstance   (workflow_instances) ESTE proceso vivo + estado durable
WorkflowRun        (workflow_runs)      segmento entre checkpoints (instance_id)
```

## Qué NO se creó

- No hay Workflow V3 paralelo: `execute_graph` y el node registry no cambian
  de contrato (solo parámetros opcionales nuevos, default = comportamiento
  actual bit a bit).
- No hay segundo scheduler: `workflow_v2_scheduler_loop` (engine.py) suma un
  sweep de timeouts/expiración; nada más.
- No hay segundo event bus: el consumer de `rag:events` (events.py) además de
  despachar triggers despierta instancias WAITING.
- Ningún worker queda bloqueado: WAIT termina el segmento y libera el worker.

## Modelo de datos (153–156)

`workflow_instances` (153):

| columna | uso |
| --- | --- |
| `definition_snapshot` | definición congelada (graph + versión + trigger) al nacer |
| `workflow_version` | versión con la que nació (v7 vive en v7 aunque salga v8) |
| `status` | NEW / RUNNING / WAITING / COMPLETED / FAILED / CANCELLED / EXPIRED / SUSPENDED |
| `conversation_id`, `participant_id` | correlación conversacional |
| `business_key` | idempotencia de arranque (unique parcial sobre estados activos) |
| `state`, `state_version` | estado de negocio durable (JSONB, CAS) |
| `waiting_for`, `waiting_event_type`, `waiting_correlation_key`, `wait_deadline`, `wait_seq` | checkpoint del WAIT |
| `last_run_id`, `run_seq` | segmento actual |
| `expires_at` | expiración global del proceso |

`workflow_runs.instance_id` / `instance_seq` (nullable): los runs existentes
sin instancia quedan idénticos. `workflow_run_events.instance_id`: timeline.

`workflow_signals` (154): inbox durable. Uniques parciales por
`(org, event_type, external_event_id)` y `(org, idempotency_key)`: el mismo
webhook jamás ejecuta dos veces una operación.

## WAIT como primitiva

Nodo `wait_event` (presets `message`, `webhook`, `payment`, `timer`, `human`,
`signal`). El handler devuelve `control="wait_event"` con:

```json
{
  "event_type": "conversation.message",
  "correlation": {"conversation_id": "..."},
  "timeout_seconds": 86400,
  "on_timeout": "branch|expire|fail|continue",
  "port": "out"
}
```

El runtime (`runtime.py`) trata el control como suspensión: persiste outputs +
contexto + checkpoint, marca la instancia WAITING y termina el segmento con
status `waiting`. `human_approval` sigue existiendo (control
`wait_approval`); en instancias el cierre es el mismo WAIT con evento
`approval.decided`.

`on_timeout` (expiración del wait): `branch` (puerto `timeout` si existe edge),
`expire` (default sin rama), `fail`, `continue` (default en preset `timer`).

## Reanudación = segmento nuevo (sin re-ejecutar)

`instances.py`:

1. Claim atómico `WAITING → RUNNING` (`UPDATE ... WHERE status='WAITING'
   RETURNING`). Exactly-one-winner por construcción.
2. Se cargan el checkpoint acumulado (`load_instance_preload`: union de steps
   exitosos de TODOS los segmentos) y el contexto (`load_run_context` del
   último segmento).
3. `run_workflow(..., instance_id, graph_override=snapshot, source_run_id,
   preload_ports)` ejecuta con `resolve_preload_edges=True`: los edges de los
   nodos preloaded se re-derivan (incluido el puerto real del wait; se persiste
   en el step) y el scheduler continúa exactamente desde el próximo nodo. Cero
   re-ejecución de lo ya hecho.
4. Cierre del segmento: `waiting` (nuevo checkpoint) o terminal
   (`COMPLETED/FAILED`). `handle_segment_result` es idempotente respecto a
   estados terminales (no pisa CANCELLED).

## Señales

`signal_workflow_instance(organization_id, event_type, correlation, payload,
external_event_id, idempotency_key, instance_id)`:

1. INSERT en inbox (`ON CONFLICT DO NOTHING`): dedupe real por constraints.
2. Match tenant-scoped por `(waiting_event_type, waiting_correlation_key)`
   (índice parcial de WAITING) o directo por `instance_id` (timeouts), con
   validación de correlación en el camino directo.
3. Claim + resume inline; si no hay waiter queda `pending` → cubre la carrera
   **webhook-antes-de-WAIT** (al entrar al wait se consume el pendiente).

Fuentes de señal: endpoint `POST /workflows/instances/{id}/signal`, conversation
router, consumer de `rag:events` (correlaciones estándar del payload:
conversation_id, payment_reference, order_id, ...), sweep de timeouts.

El bus deriva candidatos de correlación y emite hasta 3 señales dirigidas por
evento (más una sin correlación si no hay claves).

## Timeouts y expiración (scheduler único)

Cada 60s `workflow_v2_scheduler_loop` ejecuta `sweep_waiting_instances()`:

- `wait_deadline <= now` → signal interno `workflow.wait.timeout`
  (`idempotency_key = timeout:{instance}:{wait_seq}`, un solo timeout por wait)
  → resume por puerto `timeout` según `on_timeout`.
- `expires_at <= now` → instancia EXPIRED.

## Business state

`instance.state` JSONB + nodos `state_get/set/merge/append/remove` (caminos con
notación de puntos, validación determinista). Separado de las variables de run
(efímeras) y del WorkflowContext (evidencia/citas). El LLM **propone**; el nodo
**aplica**. Lectura por referencias `{{instance.state.<path>}}`. Toda mutación
usa CAS sobre `state_version`.

## Conversation Router

`conversation_router.py`: antes de que el Decision Engine / turn intent trate un
mensaje como solicitud independiente, se verifica si existe una instancia
WAITING para `conversation_id` esperando `conversation.message`; si existe, el
mensaje es un signal y el workflow continúa (misma instancia, mismo estado).

Puntos de entrada: `POST /api/v1/rag/query` (`_maybe_dispatch`), agent runs
(`/{agent_id}/run` con `conversation_id`), embed chat (nuevo campo
`conversation_id` opcional). Si no hay instancia, el routing normal decide
(puede iniciar un proceso con `POST /workflows/{id}/instances`).

## API

- `POST /workflows/{id}/instances` — arranca proceso durable (definición
  congelada, `business_key` idempotente, `expires_in_hours`).
- `GET /workflows/instances` / `GET /workflows/instances/{id}` — estado sin
  secretos.
- `GET /workflows/instances/{id}/timeline` — runs + signals + eventos
  (`wait_entered`, `segment_resumed`, `instance_completed`...).
- `POST /workflows/instances/{id}/signal|cancel|suspend|resume`.

## Operación

- Apagar y levantar la API es seguro: la instancia vive en Postgres; la única
  condición para continuar es recibir la señal.
- Cancelación es cooperativa: si el segmento está RUNNING, la instancia pasa a
  CANCELLED y el cierre del segmento no la revive.
- SUSPENDED pausa la recepción de señales (no consume waits).
- Deuda declarada: señales `pending` sin waiter quedan como auditoría (no hay
  retención automática aún); el puerto histórico de waits con timeout-branch se
  persiste en el step del segmento previo; una instancia RUNNING cuyo proceso
  muere a mitad de segmento queda para reconciliación manual (cancel/suspend)
  — un reaper automático necesita un watchdog de segmento honesto, fuera de v1.

## Tests

`tests/test_workflow_durable_instances.py` cubre: wait libera worker, resume tras
reinicio lógico, duplicate message/webhook, webhook-antes-de-WAIT, repeated
payment success, timeout (expire y branch), expiración global, cancelación,
suspensión, cross-tenant, wrong conversation, exactly-one-winner concurrente,
estado durable (merge/append/remove), versión congelada, business_key
idempotente, portabilidad y compatibilidad de runs sin instancia.
