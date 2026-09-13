# Zent Living Workflows — Event Sources, Data Watchers y Proactive Assistants

> **Status:** Phase A+B contracts implementados; Phase C+E MVP de watchers implementado en esta entrega.
> **Fecha:** 2026-09-13
> **Base:** `feat/knowledge-cognitive-os` @ `473de25` (workflow business UX refactor completo)
> **Principio:** WORKFLOW IS ALWAYS READY. AGENT WAKES ONLY WHEN NEEDED.
> **Prohibido:** LLMs en loop, segundo motor de workflows, segundo event bus, polling sin límites, scans completos, DB triggers automáticos.

Este documento es el SOURCE OF TRUTH de la auditoría previa a Living Workflows.
Todo lo listado como "existe" fue verificado contra el repositorio actual.

---

## 1. CURRENT — qué existe hoy (verificado)

### 1.1 Bus de eventos y dispatcher

```
publish_event(event_type, payload)
  src/platform/realtime/stream.py
  Redis Pub/Sub canal `rag:events` (EVENTS_CHANNEL)

workflow_event_consumer_loop()
  src/platform/workflows/events.py
  subscribe rag:events -> dispatch_event_to_workflows(event_type, payload)

dispatch_event_to_workflows()
  - workflow_event_triggers (event_type + filters + status)
  - _filters_match() comparación por igualdad (str o nativo)
  - anti-loop `_wf_chain` (máx depth 4)
  - dedupe Redis TTL 60s: mkt:wfevt:{workflow_id}:{event_type}:{org}:{entity_id|id}
  - run_workflow(...) por cada trigger que matchea
```

Catálogo `STANDARD_EVENTS` (events.py): `source.connected`, `source.synced`,
`document.uploaded`, `document.processed`, `entity.created`, `entity.updated`,
`semantic.mapping.approved`, `agent.run.completed`, `invoice.detected`,
`customer.created`, `sales.closed`, `workflow.completed`, `integration.connected`,
`workflow.run`. Además se aceptan `custom.*`.

### 1.2 Loops en el proceso API

`src/api/main.py` (lifespan) arranca en tareas asyncio:

- `workflow_v2_scheduler_loop()` (schedule daily/weekly/monthly/cron/every_minutes)
- `workflow_event_consumer_loop()` (Redis pub/sub)
- `webhook_deliveries_loop`, knowledge refresh, catalog discovery, spider, region health, etc.

`worker_entry.py` es SOLO ingestion. NO hay worker dedicado de workflows/eventos hoy.

### 1.3 Persistencia y ejecución

- `workflows` (graph JSONB, workflow_version, graph_source, trigger_config, status), `workflow_runs`,
  `workflow_run_steps`, `workflow_versions`, `workflow_event_triggers`, `workflow_approvals`.
- `run_workflow()` crea run + `execute_graph()` (DAG, retries, timeout, error_policy, simulate,
  permisos por capability, aprobaciones).
- `simulate` y `planned_effects` YA existen: el "dry-run" de efectos es reusable.

### 1.4 Consultas SQL existentes (para watchers)

- `src/platform/managed_db/service.py::open_managed_query_session(org, workspace)`:
  sesión reader-only contra la managed DB del workspace (o None).
- `src/infrastructure/postgres/readonly_session.py::get_readonly_session()`:
  fallback de lectura del DB interno.
- `src/agents/tools/sql_expert_postgres.py::_run_query` ya combina ambos con timeout,
  `LIMIT` y transacción read-only.
- Conectores externos: `ConnectorPlugin` (test/discover) y catálogo `catalog_sources`;
  NO existe hoy una API genérica "ejecutar SELECT contra source externo". Los watchers
  MVP usan la managed DB / readonly; el adapter a conectores externos queda como fase futura.

### 1.5 Seguridad y gobierno existentes

RBAC workflows:*, workspace isolation, ExecutionContext explícito, auditoría,
`purpose` en integraciones, `human_approval`, cost estimation, rate limits del
marketplace por integración. No existe service identity específica de workflows
(ni límites por workflow) — se planifica en Phase G.

### 1.6 Lo que NO existe

- `BusinessEvent` normalizado (hoy los eventos son dicts sueltos).
- `EventSchemaRegistry`/catálogo de negocio de eventos (la UI hardcodea `EVENTS_OPTIONS`).
- Watchers / data watchers / transition detection / cooldown / debounce.
- Inbox durable de eventos y outbox transaccional (dedupe es solo Redis TTL 60s).
- TriggerDefinition business-level (hoy: trigger_type schedule|webhook|event + trigger_config).
- EventSource abstraction, delivery guarantees, retries con dead letter.
- Rate limits y circuit breaker por workflow (existe por integración marketplace).
- Explicación "por qué corrió / por qué no corrió" (existe run history técnico).

---

## 2. TARGET — modelo objetivo

### 2.1 Trigger model v2 (compatibilidad total)

`TriggerDefinition` conceptual (se persiste/deriva, no rompe nada):

| Conceptual | Hoy (graph/engine) |
|---|---|
| MANUAL | `POST /{id}/run` (sin trigger node) |
| SCHEDULE | `trigger_schedule` + `trigger_config` (scheduler v2) |
| WEBHOOK | `trigger_webhook` + `hook_secret_hash` |
| INTERNAL_EVENT | `trigger_event` + `workflow_event_triggers` |
| CONNECTOR_EVENT | `trigger_event` con `custom.*` de conectores |
| DATA_CHANGE | **nuevo**: watcher timestamp/watermark polling |
| CONDITION_WATCH | **nuevo**: watcher con transición ON_ENTER/ON_EXIT |

Los tipos actuales siguen siendo el runtime. Los nuevos compilan a eventos
internos (`trigger_event`) o a watchers, nunca a un motor nuevo.

### 2.2 Flujo Living

```
EVENT / WATCHER
      ↓
BusinessEvent (dedupe determinista)
      ↓
workflow_event_triggers → run_workflow() (engine existente)
      ↓
¿necesita razonamiento?
  NO → nodos determinísticos (condition/notify/api/…)
  SÍ → agente vía AgentRuntime / Cognitive OS
      ↓
acción + resultado
      ↓
IDLE (sin LLM corriendo)
```

### 2.3 BusinessEvent (implementado)

`src/platform/workflows/business_events.py`:

`event_id, event_type, event_version, organization_id, workspace_id, source,
source_id, entity_type, entity_id, operation, before, after, changed_fields,
occurred_at, received_at, correlation_id, dedupe_key, delivery, metadata,
security_context`.

- `compute_dedupe_key()` determinista: `org:event@version:entity:operation:hash(after)`
  (sin TTL; el consumidor decide idempotencia).
- `transition_of(before, after)` = `false_to_true | true_to_true | true_to_false | false_to_false`.
- `normalize_legacy_event(event_type, payload)` convierte los payloads actuales del bus.

### 2.4 EventSchemaRegistry + catálogo de negocio (implementado)

`src/platform/workflows/event_registry.py`:

- `EventSchema`: `id`, `version`, `business_name`, `description`, `category`, `icon`,
  `fields[]` (type, business label, example), `delivery`, `source_kind`.
- Catálogo agrupado para UI: Ventas, Inventario, Clientes, Documentos, Knowledge,
  Agentes, Sistema. IDs técnicos viven internamente; el usuario ve nombres de negocio.
- Nuevos eventos de watcher: `inventory.stock.changed`, `inventory.stock.low`,
  `invoice.overdue`, `knowledge.changed`, `sale.created`.

### 2.5 Watchers (Phase C+E implementado en MVP)

`src/platform/workflows/watchers.py` + tablas `workflow_watchers` /
`workflow_watcher_states`:

- `WatcherDefinition`: name, description, source_id, strategy, entity, schema/table,
  primary_key, timestamp_field, selected_fields, condition (field/operator/value),
  transition_mode, interval_seconds, cooldown_seconds, debounce_seconds, checkpoint,
  status, workflow_id, event_type.
- `WatcherState`: last_value, last_payload, last_condition_result, last_event_at,
  last_triggered_at, checkpoint, cooldown_until, pending_since, failure_count, last_error.
- Strategies MVP: `watermark_polling` (PK incremental) y `timestamp_polling`
  (`updated_at > checkpoint`). `query_watch`/CDC quedan como evolución.
- Transiciones: `on_change`, `on_enter`, `on_exit`, `while_true` — evaluadas con el
  `_eval_condition` del engine (mismos operadores que el Condition Builder).
- Cooldown y debounce persistidos. Dedupe determinista + anti-loop `_wf_chain`.
- SQL construido con identificadores whitelisteados, `LIMIT` acotado y sesión
  reader-only existente (`open_managed_query_session` / readonly fallback).
- NUNCA se instalan triggers físicos en la DB del cliente.
- Loop `watcher_scheduler_loop()` (60s) registrado en el lifespan del API, fail-soft.

### 2.6 Endpoints nuevos

- `GET /api/v1/workflows/event-catalog` (catálogo de negocio para el builder).
- `GET/POST /api/v1/workflows/watchers`, `GET/PATCH/DELETE /watchers/{id}`,
  `POST /watchers/{id}/check` (check manual), `GET /watchers/{id}/state`.

---

## 3. FASES Y ESTADO

| Fase | Alcance | Estado |
|---|---|---|
| A | Audit + contratos (BusinessEvent, TriggerDefinition conceptual) | Implementado |
| B | EventSchemaRegistry + catálogo de negocio | Implementado |
| C | Watcher domain + persistencia | Implementado |
| D | Incremental database polling (managed/readonly) | Implementado MVP |
| E | Transition / cooldown / debounce | Implementado |
| F | Durable inbox + retries + dead letter | Pendiente (siguiente entrega) |
| G | Service identity + rate limits + circuit breaker | Pendiente |
| H | UX actividad "por qué corrió / por qué no" | Parcial (run history + readiness; falta UI watcher) |

## 4. NON-NEGOTIABLE (contratos futuros)

- Payload de evento = UNTRUSTED INPUT: nunca se interpreta como instrucciones.
- Aislamiento org/workspace en cada query de watcher/estado/evento; sin caché cross-tenant.
- Sin full table scans: watermark/timestamp + `ORDER BY` + `LIMIT` acotado.
- Sin DB triggers físicos automáticos.
- Sin retries infinitos: fase F define reintentos separados de eventos y acciones con dead letter visible.
- Idempotencia de consumidores (dedupe determinista) antes de AT_LEAST_ONCE.
- Nada de agentes corriendo permanentemente: el watcher es SQL/condición; el agente se despierta
  solo cuando el workflow lo pide.

## 5. RIESGOS

| Riesgo | Mitigación |
|---|---|
| Polling agresivo | interval_seconds mínimo y `LIMIT`; loop 60s; intervalo por watcher |
| Storm de eventos | dedupe + cooldown + (fase G) rate limits por workflow |
| Duplicados por Redis caído | fase F inbox durable; hoy dedupe best-effort documentado |
| Escalación de privilegios vía evento | payload untrusted + ExecutionContext del workflow + permisos de nodo |
| Watcher apuntando a tabla sin índice | exigir timestamp/pk como cursor; validar columnas whitelist |
| Loop workflow→evento→workflow | `_wf_chain` máx depth 4 conservado; dedupe determinista |
