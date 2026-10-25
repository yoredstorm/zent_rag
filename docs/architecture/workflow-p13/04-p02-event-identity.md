# P13 — 04 P02: identidad de eventos, inbox y outbox

SHA base: `b31b01402a2e10008eb09b77c148e48120af6004`.
Migración: `171_workflow_event_identity.py`.

## 1. Regla de identidad

`event_identity.resolve_identity()` decide una sola clave por evento:

| Fuente | Clave | Modo | Garantía |
|---|---|---|---|
| Provider con ID | `provider:{source}:{workflow}:{id}` | `provider_event_id` | dedupe |
| Cliente con `Idempotency-Key` | clave explícita, aislada por org+workflow | `client_key` | dedupe |
| Schedule | `sched:{workflow}:{occurrence}` | `schedule_occurrence` | dedupe por ocurrencia |
| Evento interno | `evt:{workflow}:{event_id}` | `producer_event_id` | dedupe si el productor persiste ID |
| Webhook sin ID | `webhook:{workflow}:{uuid4}` | `independent` | cada request es una operación |
| Opt-in payload | `payload:{workflow}:{sha256}` | `payload_hash` | solo explícito y auditado |

`payload_hash` se guarda siempre para detectar conflicto, pero no es la
identidad por defecto.

## 2. Conflicto

Misma clave + payload distinto:

```json
{"code": "idempotency_conflict", "status_code": 409}
```

No se ejecuta nada. Misma clave + mismo hash devuelve el estado anterior y el
mismo `instance_id`/`run_id`.

## 3. Migración 171

- `workflow_ingress_events`: `source`, `event_type`, `provider_event_id`,
  `payload_hash`, `dedupe_mode`, `dedupe_key`, `envelope`, `run_id`,
  `heartbeat_at`, `lease_expires_at`, `next_attempt_at`, `max_attempts`,
  `dead_letter_at`, `effect_status`.
- Índice único `(organization_id, workflow_id, source, dedupe_key)`.
- Backfill: `source=trigger_type`, `dedupe_key=ingress_key`,
  `dedupe_mode='legacy'`.
- `workflow_outbox`: evento persistido en la transacción del productor.
- `workflow_effect_intents`: `effect_id`, `external_id`, request hash,
  response, estado y reintentos.

## 4. Inbox y worker

- `route_ingress` registra el evento antes de decidir duración.
- Claim atómico con `attempts`, `claimed_at`, lease de 5 min y heartbeat.
- `drain_ingress_events()` drena `pending|failed`, rehidrata el payload
  persistido y ejecuta.
- Fallo: backoff exponencial con jitter, máximo de intentos y `dead_letter_at`.
- `sweep_ingress_events()` recupera leases vencidos.
- El scheduler existente llama sweep + drain + outbox; no hay segundo scheduler.

## 5. Outbox

`outbox.enqueue(session, ...)` inserta el evento en la misma transacción de
negocio. `dispatch_pending()` publica al bus existente y marca `delivered_at`.
Si Redis/NATS cae, la fila permanece y se reintenta. El consumer usa
`event_id` persistido; Redis deja de ser autoridad de dedupe.

## 6. Efectos externos

`effect_ledger` calcula `effect_id` estable por org/workflow/instancia/run/nodo/
capacidad/inputs. No mantiene transacción DB durante la llamada externa.
`bindings.execute_binding` aplica el ledger a `rest_api` y
`marketplace_action`; pagos/commerce conservan su ledger existente.

## 7. Pruebas

```powershell
uv run --frozen --no-sync pytest tests/test_workflow_event_identity.py -q
```

Resultado: **6 passed**.

- dos payloads idénticos sin ID → 2 operaciones;
- mismo provider_event_id → 1 instancia;
- misma clave + payload distinto → 409;
- 100 requests concurrentes con la misma clave → 1 instancia;
- schedule: misma ocurrencia → 1, distinta → 2;
- outbox: enqueue + dispatch + `delivered_at`.

Regresión: `test_workflow_durable_ingress.py` + `test_workflow_durable_instances.py`
**34 passed**.

## 8. Límites y NOT_VERIFIED

- No se probó caída real de Redis/PostgreSQL con Docker en esta sesión:
  `NOT_VERIFIED`.
- Productores de eventos no migrados siguen publicando directo al bus hasta su
  fase; el outbox cubre los flujos integrados.
- Webhooks sin ID no garantizan dedupe por diseño; para capacidades reguladas
  se exige ID externo autenticado.
- No se ejecutaron cobros reales.
