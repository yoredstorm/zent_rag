# Workflow Business UX — Auditoría y Contratos (Commit 1)

> **Status:** ADR + capa de schemas. El motor actual no cambia.
> **Fecha:** 2026-09-13
> **Base:** `feat/knowledge-cognitive-os` @ `c9dab79`
> **Objetivo:** "Decirle a Zent qué quiero automatizar" en lugar de "construir un workflow".
> **Regla de oro:** UX simple arriba, motor potente abajo. El Graph IR sigue siendo el IR canónico.

Este documento es el **SOURCE OF TRUTH** de la auditoría previa al refactor. Todo lo
listado como "existe" fue verificado contra el repositorio (no contra suposiciones).

---

## 1. CURRENT — arquitectura actual

### 1.1 Hay dos generaciones de workflow coexistiendo

| | v1 (legacy) | v2 (Studio) |
|---|---|---|
| Tabla | `workflow_definitions` | `workflows` |
| Módulo | `src/platform/workflows/workflows.py` | `src/platform/workflows/engine.py` |
| Modelo | `steps[]` lineal con `then`/`else` | `WorkflowGraph` (nodes/edges/ports) |
| Scheduler | `workflow_scheduler_loop()` (cron 5 campos) | `run_due_scheduled_workflows()` (daily/weekly/monthly/cron/every_minutes) |
| API | (sin rutas propias activas) | `/api/v1/workflows/*` |
| Estado | compatibilidad; no crear features nuevas aquí | **superficie de trabajo del refactor** |

`engine.py` adapta `steps[]` a grafo vía `LegacyWorkflowAdapter` (`ir.py`), por lo que
**todo workflow v1 sigue ejecutándose**. Nada del refactor puede romper esa ruta.

### 1.2 Backend v2 — mapa real

```
src/api/routes/workflows.py     API REST (CRUD, runs, versiones, triggers, marketplace, hook público)
src/platform/workflows/
  engine.py        run_workflow() + ExecutionContext + CRUD + schedules v2 + aprobaciones + dashboard
  runtime.py       execute_graph() DAG: entrypoints, edges, join/merge, for_each, retries,
                   timeouts, error policies, dry-run, permisos por capability, resume
  nodes.py         registry node_type → NodeTypeDef (label, category, risk, capabilities, execute)
                   handlers: llm, kb_query, api_call, condition, notify, marketplace_action,
                   query_business_data, set_variable, business_result, for_each, join, merge,
                   filter, human_approval, stop, business_node, end, triggers
  ir.py            WorkflowGraph/WorkflowNode/WorkflowEdge, validate_graph(), LegacyWorkflowAdapter,
                   resolve_stable_references() ({{nodes.id.output.x}}, {{trigger.x}})
  events.py        workflow_event_triggers + dispatch_event_to_workflows() sobre el bus Redis
                   existente (rag:events); anti-loop por `_wf_chain`, dedupe 60s
  versions.py      workflow_versions (snapshot/promote/restore/publish), no toca secrets
  capabilities.py  contexto marketplace del canvas, cost_estimate, install_inline, ports_for_action,
                   draft_marketplace_flags
  copilot.py       build_draft() — heurísticas/regex ES/EN → DraftPlan (steps legacy)
```

Endpoints actuales (todos bajo `/api/v1/workflows`):

- `GET/POST /`, `POST /validate`, `GET /templates`, `POST /templates/{slug}/install`
- `GET/POST/DELETE /triggers`
- `GET /runs/{id}`, `GET /runs/{id}/approvals`, `POST /runs/{id}/approvals/{aid}/decide`
- `GET/PATCH/DELETE /{id}`, `POST /{id}/activate|pause|run`, `GET /{id}/runs`
- `POST /{id}/hook-secret/rotate`, `GET /{id}/versions`, `POST /{id}/versions`,
  `POST /{id}/versions/{vid}/promote|restore`, `POST /{id}/publish`
- `GET /marketplace/context`, `POST /marketplace/install`, `GET /marketplace/ports/{action_id}`,
  `POST /marketplace/recommend`, `POST /cost-estimate`
- Público: `POST /api/v1/public/workflows/{id}/hook` (header `X-Zent-Workflow-Secret`)
- Copilot actual: `POST /api/v1/intelligence/workflow/draft` (heurísticas → `steps[]` legacy)
  y `GET /api/v1/intelligence/assist/options` (kbs/agents/sources/installs).

### 1.3 Base de datos relevante

| Tabla | Origen | Notas |
|---|---|---|
| `workflows` | `69-workflows.sql`, `79-workflow-studio.sql`, `088_workflow_graph.py` | `graph JSONB`, `workflow_version`, `graph_source`, `workspace_id`, `editor_state`, `last_run_at`, `trigger_config` |
| `workflow_runs` / `workflow_run_steps` | `42/69` + `088` | `trigger_payload`, `correlation_id`, `actor_*`, `simulate`, `node_id/node_type/attempt/idempotency_key` |
| `workflow_templates` | `69` + `79` | `trigger_config` + `steps[]`; 5 plantillas seed |
| `workflow_event_triggers` | `088` | unique `(workflow_id, event_type)` |
| `workflow_approvals` | `088` | aprobación humana |
| `workflow_versions` | `109` / `81-workflow-versions.sql` | snapshot publicable |
| `integration_actions` | `089` + `092` | `input_schema`, `output_schema`, `renderer`, `cost_model`, `risk_level` |
| `installed_integrations` | marketplace | `credential_ref`, `purpose`, `enabled_actions` |

RBAC ya existe: `workflows:*`, `workflow_runs:read`, `workflow_events:subscribe`,
`workflow_secrets:manage`, `workflow_approvals:approve`, `integrations:*`,
`external_actions:execute` (migración `088`).

### 1.4 Frontend actual (portal React + Vite)

```
portal/src/pages/Workflows.tsx            lista + plantillas + activar/pausar/borrar
portal/src/pages/WorkflowStudio.tsx       estudio full-bleed: canvas + dock Probar + drawers API/Avanzado
portal/src/components/
  WorkflowCanvas.tsx                      render del grafo (drag, zoom, overlay de runs)
  WorkflowCanvasEditor.tsx                librería + canvas + inspector + marketplace drawer + costos
  NodeLibrary.tsx                         rail de nodos + sección marketplace (installed/available/recs)
  NodeConfigPanel.tsx                     inspector: FieldDef (text/number/select/json), políticas,
                                          data refs con `{{nodes.id.output.x}}` visible
  WorkflowRunInspector.tsx                detalle de pasos
  workflowStudio/WorkflowTestPanel.tsx    dock "Probar" (simulate/run real, runs recientes)
  workflowStudio/WorkflowApiPanel.tsx     hook URL, secret, snippets curl/fetch
  workflowStudio/WorkflowVersionsPanel.tsx snapshot/promote/restore/publish
  workflowStudio/types.ts                 tipos compartidos + normalizeTestPayload + answerFromSteps
portal/src/lib/workflowGraph.ts           espejo del IR + NODE_LIBRARY (FieldDef/NodeMeta) +
                                          referenceOptions() (Data Picker actual, hardcoded)
```

Tests que fijan comportamiento actual (no romper):

- `tests/test_workflow_graph.py` (603 líneas) — IR, DAG, aislamiento, dry-run, aprobaciones, schedules.
- `tests/test_workflow_studio.py` (399) — secret rotation, versiones, publish/restore.
- `tests/test_workflows.py` (536) — CRUD/runs legacy.
- `tests/test_workflow_marketplace.py` (253) — contexto marketplace, ports, costos, draft flags.
- `portal/src/lib/workflowGraph.test.ts`, `portal/src/components/workflowStudio/*.test.tsx`.

---

## 2. CURRENT UX PAIN POINTS (con evidencia)

1. **El canvas es la puerta de entrada.** `Workflows.tsx` → "Nuevo workflow" → nombre → canvas
   vacío. No existe camino "describir en lenguaje natural" dentro de Workflows.
2. **El Copilot actual produce `steps[]` legacy**, no `WorkflowGraph`, y vive en Intelligence
   (`/intelligence/workflow/draft`), lejos del Studio. No hay "Entendí esto" ni preguntas
   bloqueantes: `build_draft()` devuelve un draft fijo (brief de ventas o RUC) con regex.
3. **Inspector técnico.** `NodeConfigPanel` muestra `n.type · v1`, puertos `in: json`,
   riesgo, `max_attempts`, `timeout_ms`, `error_policy` siempre; los campos avanzados se
   ocultan con un solo toggle (`adv`) sin niveles Guided.
4. **Referencias crudas.** El data picker inserta y muestra `{{nodes.<id>.output.total}}`;
   `referenceOptions()` usa `OUTPUT_FIELDS` hardcoded por tipo de nodo.
5. **Condición técnica.** `field`/`operator`/`value` con operadores `==`, `!=`, `>=`…
   (`workflowGraph.ts` COND_OPS). Sin AND/OR ni grupos anidados en UI.
6. **Schedule técnico.** `trigger_schedule` pide `every_minutes`, `daily` como texto
   `hh:mm`, `weekly` como texto `0,2 09:00`, `timezone` (avanzado). Sin preview humano.
7. **Notify limitado.** Canales `in_app|email|webhook`; sin destinatario/plantilla;
   el email real siempre va al primer usuario del tenant (`_owner_email`).
8. **Marketplace pide JSON.** `marketplace_action.inputs` es un textarea JSON aunque
   `integration_actions.input_schema` exista; `ports_for_action()` ya expone schemas.
9. **Errores técnicos.** `validate_graph` devuelve "edge e3: tipo string no compatible con
   number (n2.out → n3.in)"; el runtime devuelve "permiso insuficiente: …".
10. **No hay readiness check ni resumen legible.** `graphIssues()` solo marca `llm` sin agente,
    `kb_query` sin query y nodos inalcanzables.
11. **No hay patch por lenguaje natural.** Editar = arrastrar/tipear en inspector.
12. **Test mode ya existe pero es técnico**: `WorkflowTestPanel` habla de "payload",
    `{{trigger.message}}`, "nodos de escritura", JSON.

---

## 3. WHAT MUST BE REUSED (no reimplementar)

| Capacidad | Reusar |
|---|---|
| Ejecución | `engine.run_workflow()` + `runtime.execute_graph()` + `ExecutionContext` |
| Grafo | `ir.WorkflowGraph` + `validate_graph()` + `LegacyWorkflowAdapter` |
| Nodos | `nodes.registry` (handlers, capabilities, risk) |
| Scheduler | `next_trigger_at()` / `run_due_scheduled_workflows()` (daily/weekly/monthly/cron) |
| Eventos | `events.dispatch_event_to_workflows()` + `STANDARD_EVENTS` + bus Redis existente |
| Versionado | `versions.py` snapshot/promote/restore/publish |
| Marketplace | `capabilities.canvas_context/ports_for_action/cost_estimate/install_inline`, runtime marketplace |
| Notificaciones | `notifyv2.notifications.notify()` (in_app/email/webhook) |
| Agentes | `AgentRuntime` + `AgentRunRequest`; `config_json.output_schema` + `deployments/output_schema.py` |
| LLM | `infrastructure/llm/provider.py` (LiteLLM + router + circuit breaker), `api/deps.get_llm_provider` |
| RBAC / tenancy | `require_permission`, workspace header, `_workspace_id()` |
| Auditoría | `_audit_run_access()` + `AuditLogService` |
| Test mode | flag `simulate` + `planned_effects` + `workflow_run_steps.status='simulated'` |
| Plantillas | `workflow_templates` + `create_from_template()` (se evolucionan a Recipes, misma tabla) |

## 4. WHAT MUST NOT BE DUPLICATED

- **NO** segundo engine/executor de grafos.
- **NO** segundo scheduler (el schedule builder solo escribe `trigger_config` v2).
- **NO** segundo AgentRuntime.
- **NO** segundo message bus (se reusa `rag:events`).
- **NO** segundo sistema de notificaciones (el Notification Builder compila a `notify`).
- **NO** Graph IR paralelo: `WorkflowPlan` compila a `WorkflowGraph`, no lo reemplaza.
- **NO** secrets en claro en `graph`: se mantiene `hook_secret_hash` y `credential_ref`.

---

## 5. TARGET — capas nuevas

```
Lenguaje natural / formulario guiado / canvas
        │
        ▼
WorkflowIntent          (lo que el usuario quiso decir; el LLM propone)
        │  backend valida + pregunta lo imprescindible
        ▼
WorkflowPlan            (representación de negocio: trigger/condiciones/análisis/acciones)
        │  compiler (determinístico)
        ▼
WorkflowGraph (IR v2)   ← el MISMO que ya ejecutan engine.py + runtime.py
```

### 5.1 Modos de entrada (Home)

1. **Crear con IA** (default) — "Describe qué quieres automatizar" → Intent → Plan → preview.
2. **Usar una plantilla** — Business Recipes (misma tabla `workflow_templates`, con preguntas).
3. **Diseñar manualmente** — Advanced Canvas actual, intacto.

### 5.2 Niveles de configuración

- **Simple:** solo campos de negocio (`BusinessParameterSchema.advanced=False`).
- **Guided:** campos no peligrosos + explicaciones, sin JSON/cron/refs crudas.
- **Advanced:** JSON, cron, referencias, timeouts, retries, raw API, puertos, error policies.

Los tres guardan **el mismo `WorkflowGraph`**; el nivel es solo una vista
(`editor_state.config_level`).

### 5.3 Contratos nuevos (implementados en este commit)

- `src/platform/workflows/business_schema.py`
  - `BusinessParameterSchema` (24 tipos, `advanced`, `secret`, `dynamic_options`,
    `data_source`, `unit`, `validation`, `help`, `business_group`).
  - `BusinessOutputField` / `NodeOutputContract` para declarar salidas tipadas
    (Data Picker + Live Preview).
- `src/platform/workflows/intent.py`
  - `WorkflowIntent` (name, description, trigger, conditions, data_sources, actions,
    agents, schedule, recipients, questions, risk, estimated_cost, confidence).
  - `WorkflowPlan` (versión normalizada que consume el compiler).
  - `ConditionOperator` canónico + alias ES ("es mayor que" → `gt`) + mapeo al motor
    (`gt` → `>`); `ConditionGroup` AND/OR anidado.
  - `PlanSchedule` con `to_trigger_config()` / `describe()` (mapea al scheduler v2).
  - `SemanticWorkflowPatch` (edición por lenguaje natural, commit 6).
  - `validate_intent()` / `validate_plan()`: el LLM propone, el backend valida.

### 5.4 Errores humanos

Los mensajes técnicos se traducen en la capa de presentación
(`portal/src/lib/workflowErrors.ts`, commit 7) usando el contexto del plan
(label del nodo + label del campo). El backend seguirá devolviendo detalle técnico
para Advanced; Simple recibe mensaje de negocio + CTA (`Conectar Slack`).

---

## 6. FILES TO MODIFY / CREATE (por commit)

### Commit 1 — Audit + schemas (este)

- **CREATE** `docs/architecture/workflow-business-ux.md` (este documento).
- **CREATE** `src/platform/workflows/business_schema.py`.
- **CREATE** `src/platform/workflows/intent.py`.
- **CREATE** `tests/test_workflow_business_schema.py`.

### Commit 2 — Business parameter renderer

- CREATE `src/platform/workflows/parameters.py` (registry `node_type → [BusinessParameterSchema]`
  + `business_parameters_for(node_type)` y `business_outputs_for(node_type)`).
- MODIFY `src/api/routes/workflows.py`: `GET /api/v1/workflows/node-schemas`.
- CREATE `portal/src/components/workflowStudio/BusinessParameterForm.tsx`.
- MODIFY `portal/src/components/NodeConfigPanel.tsx` (render por schema; fallback a FieldDef).
- MODIFY `portal/src/lib/workflowGraph.ts` (tipos espejo + nivel config).

### Commit 3 — Condition Builder + Data Picker

- CREATE `src/platform/workflows/conditions.py` (compilar grupos a config de `condition`/`filter`).
- CREATE `portal/src/components/workflowStudio/ConditionBuilder.tsx`.
- CREATE `portal/src/components/workflowStudio/DataPicker.tsx` (consume output contracts).
- MODIFY `NodeConfigPanel.tsx`, `workflowGraph.ts` (`referenceOptions` desde contratos).

### Commit 4 — Schedule + Notification Builder

- CREATE `portal/src/components/workflowStudio/ScheduleBuilder.tsx` (preview humano).
- CREATE `portal/src/components/workflowStudio/NotificationBuilder.tsx` (canales disponibles +
  recipients + variable picker).
- MODIFY `WorkflowCanvasEditor.tsx` / `NodeConfigPanel.tsx`.
- Backend: `GET /api/v1/workflows/notification-targets` (personas/equipos/emails).

### Commit 5 — Copilot V2 / Intent / Plan / compiler

- MODIFY `src/platform/workflows/copilot.py` (mantener heurísticas como fallback;
  extracción LLM vía `get_llm_provider`).
- CREATE `src/platform/workflows/plan_compiler.py` (`WorkflowPlan → WorkflowGraph` validado).
- CREATE `src/platform/workflows/copilot_v2.py` (pipeline NL → Intent → preguntas → Plan).
- MODIFY `src/api/routes/workflows.py`: `POST /copilot/intent`, `POST /copilot/plan`,
  `POST /copilot/plan/compile` (nunca publica solo).
- CREATE `portal/src/components/workflowStudio/AskZent.tsx` ("Entendí esto").
- MODIFY `portal/src/pages/Workflows.tsx` (tres modos de entrada).

### Commit 6 — Natural-language patch

- CREATE `src/platform/workflows/patches.py` (NL → `SemanticWorkflowPatch` → diff → aplicar).
- MODIFY `src/api/routes/workflows.py`: `POST /{id}/patch/preview`, `POST /{id}/patch/apply`.
- CREATE `portal/src/components/workflowStudio/PatchDiff.tsx`.

### Commit 7 — Testing UX + readiness

- CREATE `src/platform/workflows/readiness.py` (checks de negocio, mensajes humanos).
- MODIFY `src/api/routes/workflows.py`: `GET /{id}/readiness`, `GET /{id}/summary`.
- CREATE `portal/src/components/workflowStudio/ReadinessPanel.tsx` + `WorkflowSummary.tsx`.
- MODIFY `WorkflowTestPanel.tsx` (PROBAR AUTOMATIZACIÓN: generate sample / last sample / edit).

---

## 7. DB CHANGES

**Commit 1: ninguna.** Los schemas son Pydantic en memoria.

Previsión para commits posteriores (todas aditivas, con `IF NOT EXISTS`):

| Commit | Cambio | Uso |
|---|---|---|
| 2 | — | schemas derivados de `nodes.py` + `integration_actions` |
| 3 | — | condiciones viven en `graph` |
| 4 | — | recipients en `notify.config.data` |
| 5 | `workflows.plan JSONB DEFAULT '{}'` (opcional, migración nueva) | trazabilidad Intent/Plan |
| 5 | `workflows.metadata JSONB` o reuso de `editor_state` | provenance LLM |
| 6 | — | patch aplica sobre `graph` existente |
| 7 | — | readiness se calcula en request |

Regla: ninguna migración destructiva; `graph` y `steps` nunca se eliminan.

## 8. BACKWARD COMPATIBILITY

- Workflows `graph_source='legacy'` siguen ejecutándose por `LegacyWorkflowAdapter`.
- `steps[]` se sigue aceptando en POST/PATCH (`_clean_steps`).
- `trigger_config` legacy (`every_minutes`, `daily`, `weekly`, `monthly`, `cron`) intacto.
- Plantillas actuales (`slug`, `steps`, `trigger_config`) se leen igual; las Recipes
  agregan campos opcionales.
- El canvas actual sigue siendo el editor Advanced; los builders Simple/Guided
  escriben el mismo `graph`.
- El endpoint `/api/v1/intelligence/workflow/draft` no se elimina; Copilot V2 es aditivo.
- Secretos: nada nuevo en claro; `hook_secret_hash` y `credential_ref` como hoy.

## 9. RISKS

| Riesgo | Mitigación |
|---|---|
| LLM inventa nodos/acciones inexistentes | `validate_plan()` contra registry + capabilities antes de compilar; nunca autopublicar |
| Regresión en workflows legacy | Tests existentes (`test_workflows.py`, `test_workflow_graph.py`) corren sin cambios |
| Doble fuente de verdad de parámetros (FieldDef vs BusinessParameterSchema) | El backend manda: `NODE_LIBRARY` queda como fallback visual hasta commit 2 |
| Cron/zonas mal mapeadas | `PlanSchedule.to_trigger_config()` se prueba contra `next_trigger_at()` |
| Duplicar scheduler/notificaciones | El compilador solo emite nodos `trigger_*`, `condition`, `notify`, `llm`, etc. |
| Deriva de idioma en mensajes | Mensajes humanos centralizados en `workflowErrors.ts` (commit 7) |
| Costos/secretos expuestos en Simple | `advanced`/`secret` en el schema; secrets nunca viajan al browser |

## 10. ACCEPTANCE TEST (mission §26)

"Cuando el stock sea menor a 10, avisa por correo al equipo de compras."

- Simple pide solo: ¿dónde está el inventario? ¿qué campo es stock? ¿quién recibe?
- Resultado compila a `WorkflowGraph` v2 válido:
  `trigger_event/trigger_schedule → condition(stock < 10) → notify(channel=email, recipients=Compras)`.
- Sin JSON, cron, HTTP, node ids, refs, SQL ni payloads visibles.
- El workflow resultante se ejecuta con `engine.run_workflow()` sin cambios en el motor.
