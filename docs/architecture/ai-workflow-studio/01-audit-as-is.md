# 01 — Auditoría AS-IS

> Evidencia: rutas y líneas verificadas en el árbol `70620a9`. Los conteos se obtuvieron ejecutando el registry real con `.venv` (ver `08-findings-plan-risks.md` §4).

## Índice

1. [Auditoría de capacidades](#1-auditoría-de-capacidades)
2. [Auditoría de recorridos (UI → runtime)](#2-auditoría-de-recorridos-ui--runtime)
3. [Puntos de bifurcación y redundancia](#3-puntos-de-bifurcación-y-redundancia)

---

## 1. Auditoría de capacidades

### 1.1 Superficies y conteos verificados

| Superficie | Conteo | Fuente |
|---|---|---|
| Tipos de nodo en el registry (ejecutables) | 29 | `src/platform/workflows/nodes.py:3585-3893` |
| Metadata semántica por nodo | 29 (cobertura total) | `src/platform/workflows/node_catalog.py:125-729` |
| Schemas de negocio (parámetros + outputs) | 20 | `src/platform/workflows/parameters.py:797-798` |
| Tipos de paso del `SemanticPlan` | 18 | `src/platform/workflows/architect_models.py:15-34` |
| Operaciones de conocimiento | 7 (`search, answer, find_evidence, extract_facts, compare, check_conflicts, investigate`) | `architect_models.py:38-46`, `nodes.py:50` |
| Capacidades commerce | 14 | `src/platform/commerce/contracts.py:47-62` |
| Capacidades de pago | 5 | `src/platform/commerce/contracts.py:64-70` |
| Capacidades de conversación | 1 (`conversation.send`) | `src/platform/workflows/conversation_capability.py:42` |
| Presets de WAIT | 6 (`message, webhook, payment, timer, human, signal`) | `instances.py:91-98` |
| Acciones de marketplace (dev DB) | 14 activas en 10 manifiestos | `integration_actions` (inspección local) |
| Slugs de capability con provider publicado (dev DB) | 8 | `integration_capabilities` (inspección local) |
| Endpoints del Architect consumidos por el portal | 0 | `portal/src/components/workflowStudio/AskZent.tsx:85,101` |

### 1.2 Matriz de capacidades por nodo

Columnas: **Contrato in** = config que el handler lee; **Contrato out** = claves de salida referenciables; **Permiso** = permiso que el **runtime** exige (mapa `_CAPABILITY_PERMISSION`, `nodes.py:43-47`: solo `external_actions:execute` y `agents:execute`); **Disp.** = disponibilidad que conoce el Architect (`architect_discovery._node_capabilities`); **Comp.** = el compiler del Architect puede emitirlo; **Validación** = chequeo del validator; **Cert.** = evidencia de test de ejecución real.

| Capacidad (node_type) | Módulo | Contrato in (config) | Contrato out | Permiso | Dependencias | Ejecutor real | Disp. | Comp. | Validación | Cert. |
|---|---|---|---|---|---|---|---|---|---|---|
| `trigger_event` | nodes.py:164-179 | `event_type`, `filters` | `{}` (el runtime inyecta payload) | — | evento registrado | runtime (disparo externo) | Sí (catálogo eventos) | Sí | `plan.trigger` (1 disparador) | `test_signals.py`, gold |
| `trigger_schedule` | nodes.py:129-147 | `daily`/`weekly`/`every_minutes`/`cron`/`timezone` | `{}` | — | scheduler único | `run_due_scheduled_workflows` | Sí | Sí | idem | gold (`test_gold_sales_funnel`) |
| `trigger_webhook` | nodes.py:148-163 | `{}` | payload del hook | — | `hook_secret_hash` | `run_workflow_from_hook` | Sí | Sí (desde `trigger_manual`) | idem | `test_workflows.py` |
| `query_business_data` | nodes.py:2528-2622 | `ask` (NL) | `answer, rows, columns, query_id, metrics, answerability, evidence_ids, source_freshness` | — (el runtime no exige permiso de nodo) | managed DB / semantic pipeline | RAG orchestrator | Sí (`managed_db`) | Sí | `missing.managed_db` | gold + `test_cognitive_workflows_e2e.py` |
| `kb_query` | nodes.py:1737-1836 | `operation`, `query`, `knowledge_base_id`, `limit`, `compare_left/right`, `subject` | `answer/status/chunks/citations/evidence/claims/...` por operación | — | KB existente | retrieval + cognitive OS | Parcial (solo flag `knowledge_bases`) | Sí (7 operaciones) | `missing.knowledge_bases`, `plan.knowledge_operation` | `test_workflow_knowledge_*` |
| `llm` (agente) | nodes.py:1959-2080 | `agent_id`, `prompt`, `context_mode`, `context_selectors`, `output_type`, `output_schema` | `text, agent_id, model, cost, status, context_summary` + campos del schema | `agents:execute` | agente activo | AgentRuntime | Parcial (nombre + propósito + tools) | Sí | `missing.agents`, `plan.agent_needs_selection` (**warning**) | `test_workflow_agent_context` |
| `condition` | nodes.py:2236-2260 | `field`/`rules` (grupo), `operator`, `value` | `condition, result` | — | ninguno | evaluador determinístico | No aplica | Sí | `missing.decision_input` | `test_workflow_conditions` |
| `ai_decision` | nodes.py:2263-2350 | `decision_kind`, `question`, `options`, `confidence_min`, `on_low_confidence` | `result, route, choice, confidence, needs_llm, approval_id` | — | Decision Engine / JEV | Decision Engine | Sí (metadata) | **No** | **Ninguna** | `test_zent_runtime.py` (unit del intérprete), `test_workflow_node_catalog.py`; **sin e2e del nodo** |
| `filter` | nodes.py:2821-2888 | `items`, `conditions[]`, `op` | `filtered, count, total, conditions` | — | — | determinístico | Sí (metadata) | Sí | `missing.filter_items` | `test_workflow_join_merge` |
| `for_each` | nodes.py:2625-2698 | `collection`, `max_iterations`, `concurrency`, `fail_policy`, **`_branch`** | `items_processed, results, errors, warnings, billable_calls_estimate` | — | `_branch` (subgrafo) | runtime (`_run_branch`) | Sí (metadata) | **Sí, pero sin `_branch`** | `missing.loop_collection` | `test_workflow_join_merge` |
| `join` | nodes.py:2728-2766 | `branch_labels` | `branches, count` | — | ≥2 ramas | determinístico | Sí | Sí | — | `test_workflow_join_merge` |
| `merge` | nodes.py:2768-2819 | `strategy`, `source_node_id` | `merged, source` | — | ramas | determinístico | Sí | Sí | — | `test_workflow_join_merge` |
| `set_variable` | nodes.py:2891-2898 | `name`, `value` | `variable, value` | — | — | determinístico | Sí | **No** | — | `test_workflow_durable_instances.py:54`, `test_workflow_join_merge.py:77` |
| `human_approval` | nodes.py:3166-3197 | `action`, `summary`, `expires_minutes` | `approval_id, status, action, summary, context` | `workflow_approvals:approve` (decisión) | run `pending_approval` | runtime + approvals | Sí | Sí | — | `test_workflow_graph.py::test_human_approval_flow`, `test_workflow_approval_context.py` |
| `wait_event` | nodes.py:2928-2989 | `preset`, `event_type`, `correlation`, `timeout_seconds`, `on_timeout` | `waiting, event_type, correlation, timeout_seconds` | — | **instancia durable** | runtime + `instances` | Sí (metadata) | Parcial (nunca conecta puerto `timeout`) | **Ninguna** | `test_workflow_durable_instances`, `test_signals` |
| `loop` | nodes.py:2992-3055 | `target`, `max_iterations` | `looping, target, iteration` | — | **instancia durable** | runtime + `instances._continue_loop` | Sí (metadata) | **No** | **Ninguna** | gold (`volver_al_catalogo`) |
| `state_get/set/merge/append/remove` | nodes.py:3056-3114 | `path`, `value` | `value/ok/removed` | — | estado de instancia | `mutate_instance_state` | Sí (metadata) | Sí (paso `state` con `params.op`) | **Ninguna** (no valida path) | gold |
| `capability_call` | nodes.py:3116-3155 | `capability`, `inputs` | salida del provider + `capability, provider_kind` | según binding | **binding del tenant** | `bindings.execute_binding` | **No** (bindings no entran a discovery) | **No** | **Ninguna** | gold + `test_addon_contracts` |
| `marketplace_action` | nodes.py:3329-3391 | `install_id`, `action_id`, `inputs`, `purpose` | `ok, data, evidence_id, cost, cached` | `external_actions:execute` | instalación activa + acción habilitada + credenciales + purpose | `marketplace.runtime.execute_action` | Parcial (`action_id` + `install_id`, sin estado) | Sí | `missing.integration` (solo existencia) | `test_gold_sales_funnel`, `test_marketplace_dependency_resolution` |
| `api_call` | nodes.py:1404-1505 | `url`, `method`, `headers`, `json_body`, `json_path` | `status_code, ok, extracted, url` | `external_actions:execute` | allowlist SSRF | httpx + SSRF check | Sí (metadata) | **No** | **Ninguna** (no valida allowlist) | `test_workflows.py` |
| `notify` | nodes.py:2427-2526 | `channel`, `title`, `message`, `recipients[]` | `sent, channel, deliveries` | — (solo `workflows:run` a nivel endpoint) | canal disponible | `notifyv2.notifications` | Parcial (no hay discovery de canales) | Sí | slack/teams/whatsapp bloquean, email pide destinatario | `test_workflow_notifications` |
| `business_result` | nodes.py:3526-3582 | `title`, `section`, `importance`, `summary`, `metrics`, `entities` | `result_id, importance, entities` | — | — | `save_result` | Sí (metadata) | Sí | — | `test_intelligence.py:129`, `test_cognitive_workflows_e2e.py:483`, `test_workflow_context_store.py` |
| `business_node` | nodes.py:3399-3524 | `title`, `actions[]`, `normalize`, `importance` | `result_id, actions, failures` | `external_actions:execute` | instalaciones de cada acción | `execute_action` por acción | Sí (metadata) | **No** | **Ninguna** | `test_workflow_marketplace.py:146` |
| `stop` | nodes.py:3158-3163 | `status`, `message` | `stopped, message` | — | — | runtime | Sí | Sí | — | sin test directo localizado |
| `end` | nodes.py:3325-3327 | — | `{end: True}` | — | — | virtual | Sí | **No** (el Architect no cierra con `end`) | — | `test_workflow_durable_instances.py`, `test_workflow_readiness.py` |

**Lectura de la matriz**

- **Compilables por el Architect (22 de 29):** `trigger_event`, `trigger_schedule`, `trigger_webhook`, `kb_query`, `query_business_data`, `llm`, `condition`, `filter`, `join`, `merge`, `human_approval`, `wait_event`, `state_get/set/merge/append/remove`, `notify`, `marketplace_action`, `business_result`, `stop`.
- **Ejecutables pero NO planificables (7):** `capability_call`, `loop`, `ai_decision`, `api_call`, `set_variable`, `business_node`, `end`.
- **Parcialidades (2):** `for_each` se compila sin cuerpo (`_branch`) → itera sin ejecutar; `trigger_webhook` solo se alcanza como `trigger_manual` (sin config de filtros).
- **Sin schema de negocio (9 de 29):** `capability_call`, `end`, `loop`, `state_get/set/merge/append/remove`, `wait_event` (`parameters.py:797`). Son exactamente los nodos durables/portables.
- **Certificación de ejecución:** los nodos durables y de negocio se certifican en `tests/certification/workflows/` (gold sales funnel, durabilidad, señales, dependencias marketplace, portabilidad, pagos). No existe certificación end-to-end para `ai_decision`, `business_node`, `api_call` desde el camino del Architect (no puede generarlos).

### 1.3 Descubrimiento de capacidades (lo que el planner puede saber)

`discover_capabilities()` (`architect_discovery.py:103-162`) devuelve exactamente:

| Clave | Contenido real | Fuente | ¿Suficiente para planificar? |
|---|---|---|---|
| `nodes` | `node_type`, `business_name`, `category`, `risk_level`, `supports_simulation`, `requires`, (operaciones KB) | registry + metadata | Parcial: sin contratos de config, sin `when_to_use`, sin outputs |
| `triggers` | listas fijas (`daily/weekly/every_minutes/cron`), `manual: true`, `webhook: true`, eventos | hardcode | Parcial: no valida si el schedule es válido para el tenant |
| `agents` | `id, name, purpose, tools, knowledge_base_ids, source_ids, output_schema` | SQL `agents` | Sí |
| `knowledge_bases` | lista de **ids** | `load_capabilities` | Parcial: sin nombres (el digest ni las lista) |
| `actions` | `action_id, display_name, install_id` | `load_capabilities` | **Insuficiente**: sin estado (habilitada/credenciales/purpose), sin `input_schema` |
| `events` | ids del catálogo | `event_registry.list_catalog` | Parcial: sin campos del evento |
| `managed_db` | bool | SQL | Sí |
| `permissions` | lista del actor | route | Parcial: el digest no la usa para filtrar nodos |
| `available` | 4 flags | derivado | Sí |

**No se descubre:** bindings de capacidades (`bindings.list_bindings`), capacidades de negocio (`commerce/contracts`), acciones con estado real (`capabilities._installed_status`), canales/destinatarios (`notifications.notification_targets`), watchers de datos (`watchers.list_watchers`), catálogo de datos (`data_catalog`), costos (`capabilities.cost_estimate`), ni el detalle de contratos de nodo (`parameters.node_business_schema`).

`capability_digest()` (`architect_discovery.py:202-240`) — el texto que ve el LLM — contiene: lista de `node_type`, agentes con propósito, `action_id` + display name, ids de eventos, y los 4 flags. **No** incluye nombres de KB, esquemas de entrada de acciones, campos de evento, ni `when_to_use`/`when_not_to_use` del catálogo semántico. En contraste, el Copilot legacy (`copilot_v2.py:150-157`) inyecta `planner_hints()` (`node_catalog.py:742-777`), que sí describe qué hace cada nodo y qué está indisponible. **El Architect comunica menos que el Copilot legacy.**

---

## 2. Auditoría de recorridos (UI → runtime)

### 2.1 Creación con Copilot legacy (el camino vivo del portal)

```
AskZent.tsx:85  POST /api/v1/workflows/copilot/intent
   → routes/workflows.py:146-159  require_permission("workflows:create")
   → copilot_v2.propose_workflow() (copilot_v2.py:257-316)
        → load_capabilities()            plan_compiler.py:95-177
        → LLM WorkflowIntent (1 llamada) copilot_v2.py:142-171  [prompt: INTENT_SYSTEM_PROMPT 38-76]
        → fallback heuristic_intent()    copilot_v2.py:174-254  [usa copilot.build_draft]
        → intent_to_plan()               intent.py:713
        → validate_plan()                intent.py:649
   ← intent + plan + summary + questions + issues + confidence
AskZent.tsx:101 POST /api/v1/workflows/copilot/compile  (body.plan)
   → copilot_v2.compile_proposal()      copilot_v2.py:336-352
        → plan_compiler.compile_plan_for_org()  plan_compiler.py:228-352
        → validate_graph()
   ← graph + valid + issues + summary
AskZent.tsx:132 POST /api/v1/workflows   {graph, workflow_version: 2, steps: []}
   → engine.create_workflow()           engine.py:805-885
   → persiste graph (graph_source="graph"), steps=[]
```

Notas verificadas:
- El `WorkflowPlan` legacy es plano: `trigger`, `conditions`, `data_sources`, `analysis`, `actions` (`intent.py:509`). **No expresa** dependencias, ramas, wait/state, loops ni capacidades de negocio.
- `plan_compiler.compile_plan` genera una **cadena lineal**: trigger → data_sources → condition → analysis… → actions → `end` (`plan_compiler.py:234-353`). Un `_action_node` puede ser `wait_event` (`plan_compiler.py:467-483`) con el mismo problema de instancia durable (ver 2.7).
- El portal "Cambiar algo" **no llama a ningún endpoint**: reinicia el formulario (`AskZent.tsx:294-302`).

### 2.2 Creación con Workflow Architect (implementado, no consumido)

```
POST /api/v1/workflows/architect/plan   routes/workflows.py:180-196
   → architect.plan_workflow()          architect.py:569-660
        → discover_capabilities()       architect_discovery.py:103-162
        → extract_intent_with_architect() arquitect.py:126-138   (LLM #1)
        → extract_plan_with_architect()   arquitect.py:141-159   (LLM #2)
        → validate_semantic_plan()        arquitect_validator.py:53-354
        → compile_semantic_plan()         arquitect_compiler.py:305-422
        → cost_estimate()                 capabilities.py:298-441
        → _readiness() + simulation_plan() arquitect.py:482-566
   ← intent + plan + issues + preview + graph + cost + clarifications + requirements
POST /api/v1/workflows/architect/patch   routes/workflows.py:198-219  (requiere que el cliente reenvíe el plan)
```

No existe ningún consumidor en `portal/src`: `grep -r "architect" portal/src` no devuelve coincidencias. El Architect es, hoy, una API sin interfaz.

Además, `plan_workflow` **no valida el grafo que compila** (`architect.py:607-611`): puede devolver `graph` con `issues` vacíos y que `POST /workflows` lo rechace después en `validate_graph` (`engine.py:837-840`). Evidencia reproducible en `08-findings-plan-risks.md` §4.3 y §4.2 (hallazgo F-24).

### 2.3 Creación mediante plantilla

```
POST /workflows/templates/{slug}/install   routes/workflows.py:377-389
   → engine.create_from_template()          engine.py:1154-1203
        → plantilla con graph (v2) → create_workflow(graph=…)
        → plantilla legacy (solo steps) → wire_template_installs() (capabilities.py:574-632)
             instala integraciones demo y sustituye {{_pack.<slug>_install}}
             las que requieren credenciales quedan como `missing_integrations`
```
Evidencia de plantillas durables: `db_init/versions/157_durable_template.py` (usa `capability_call` + `wait_event`).

### 2.4 Edición conversacional (dos caminos inconexos)

| Camino | Endpoint | Base | Operaciones | Quién lo usa |
|---|---|---|---|---|
| Patch del plan semántico | `POST /architect/patch` (`architect.py:361-433`, `architect_patch.py:22-69`) | el **plan que envía el cliente** (no persistido) | `set_param, set_trigger, set_schedule, remove_step, replace_agent, add_step` | nadie |
| Patch del grafo persistido | `POST /{workflow_id}/patch/preview|apply` (`routes:222-260`, `patches.py:89-98`) | grafo real del tenant | `set_value, set_field, change_channel, add_recipient, remove_recipient, change_schedule, rename, replace_agent` | `WorkflowPatchPanel.tsx` |

Consecuencia: **no se pueden agregar/quitar pasos** en un workflow existente por lenguaje natural (el patch de grafo no tiene `add_step`), y el patch que sí lo permite opera sobre un plan que la UI no conserva.

### 2.5 Validación

| Nivel | Mecanismo | Qué cubre | Qué NO cubre |
|---|---|---|---|
| Plan semántico | `validate_semantic_plan` (`architect_validator.py:53-354`) | 1 disparador, ciclos, dependencias, `when` sobre decisiones, permisos (warning), disponibilidad de agentes/KB/DB/acciones, operación KB | bindings, precondición de instancia durable, `_branch` de for_each, destinatarios, allowlist de API, contratos de nodo, presupuesto |
| Plan legacy | `validate_plan` (`intent.py:649`) + `compiled_issues` | forma y coherencia de acciones | lo mismo que arriba |
| Grafo | `validate_graph` (`ir.py:217-287`) | ids únicos, entrypoints, edges existentes, tipos de puerto, self-loops, ciclos (excluye `loop`) | semántica de nodos, contratos de config |
| Publicación | `publication_blockers` (`packages.py:597-629`) | solo workflows **importados** (`package != NULL`); `versions.py:303-311` | workflows nativos: **sin gate** |

### 2.6 Simulación

- Architect: `simulation_plan()` (`architect.py:521-566`) es **texto estático** ("Consulta OK… sin SQL real"), no ejecuta nada.
- Runtime real: `POST /{workflow_id}/run {simulate:true}` (`routes:772-797` → `run_workflow`, `engine.py:481-484`) con pinned data (`pinned.load_pinned_map`) y soporte de run parcial (`run_mode: node|until_node|from_node`).
- UI: `WorkflowTestPanel.tsx` usa ese endpoint. El Architect **no** conecta su preview con el dry-run real.

### 2.7 WAIT / RESUME (proceso durable)

```
POST /{workflow_id}/instances         routes:800-838
   → instances.start_workflow_instance()   instances.py:484-630
        snapshot congelado de la definición (definition_snapshot)
        segmento 1 → engine.run_workflow(instance_id=…)
   → nodo wait_event devuelve control="wait_event"        nodes.py:2980-2989
   → runtime marca run_status="waiting"                    runtime.py:578-584
   → engine.handle_segment_result()                        engine.py:692-714
   → instancia WAITING; worker liberado
   → señal: POST /instances/{id}/signal (routes:546-570) | hook | evento
   → instances.signal_workflow_instance()                  instances.py:1046-1171
   → _claim_and_resume()                                   instances.py:1323-1401
   → nuevo segmento con preload + puerto real (out|timeout)
   → sweep_waiting_instances() (timeouts/expiración)       instances.py:1778-1900
```

**Contraste verificado:** los disparadores normales NO crean instancia.

| Disparador | Código | ¿Crea instancia? |
|---|---|---|
| Scheduler | `engine.run_due_scheduled_workflows()` → `run_workflow(...)` sin `instance_id` (`engine.py:1548-1557`) | No |
| Hook webhook | `run_workflow_from_hook` → `run_workflow` (`engine.py:1598+`) | No |
| Manual (`/run`) | `routes:772-797` | No |
| Evento | `dispatch_event_to_workflows` → `run_workflow` + `signal_instances_from_event` (`events.py:347-366`) | Solo despierta instancias existentes |
| Instancia | `POST /instances` | Sí |

Consecuencia: un grafo con `wait_event` o `loop` publica y activa sin aviso, y **falla en el primer run** por `nodes.py:2941-2944` ("wait_event requiere una instancia durable") o `nodes.py:3018-3019` (loop).

### 2.8 Ejecución de capacidades internas

```
nodo capability_call → nodes._exec_capability_call()        nodes.py:3116-3155
   → bindings.execute_binding(org, capability_ref, inputs)  bindings.py:292-369
        → resolve_binding()                                 bindings.py:194-226
        → provider_kind ∈ {managed_db, connected_db, marketplace_action,
                           semantic_query, rest_api, erp, custom, commerce,
                           payment_provider, conversation}   bindings.py:28-42
        → validación de contrato in/out                     bindings.py:264-279
```
Estado real del tenant (dev DB): 0 bindings creados; el gold workflow los crea por fixture (`gold_support.bind_commerce`). El Architect **no conoce** este ejecutor (no está en `PLAN_STEP_TYPES` ni en discovery).

### 2.9 Instalación y resolución de dependencias del Marketplace

```
POST /workflows/marketplace/install  routes:1232
   → capabilities.install_inline()      capabilities.py:444-535
        → factory.install_product() / runtime.install_integration()
POST /marketplace/recommend            routes:1275 → capabilities.recommend_for_graph()
Paquetes portables                     packages.build_package → inspect_package → publication_blockers
Resolver capability-first              marketplace/resolver.py:105-152 (resolve_capability)
                                       resolver.py:204-244 (resolve_dependency)
```

- `install_product` resuelve dependencias tipadas y reescribe placeholders en workflows (`factory.py:145-214, 418-455`).
- La resolución **existe** y está certificada (`tests/certification/workflows/test_marketplace_dependency_resolution.py`), pero el Architect no la usa: su único punto de decisión de integración es `actions` de `load_capabilities` (`architect_compiler.py:206-223`), sin estado ni proveedores alternativos.

---

## 3. Puntos de bifurcación y redundancia

| # | Bifurcación | Caminos | ¿Redundante? |
|---|---|---|---|
| B1 | Entrada NL | `copilot/intent+compile` (vivo) vs `architect/plan` (sin UI) | Sí: dos planners para el mismo propósito; el nuevo es más estricto y el viejo es el que se usa |
| B2 | Modelo de plan | `WorkflowPlan` legacy (plano) vs `SemanticPlan` (grafo de pasos) | No son redundantes: el legacy no puede expresar ramas/dependencias. Conviven por compatibilidad |
| B3 | Compilador | `plan_compiler.compile_plan` vs `architect_compiler.compile_semantic_plan` | Solo en parte: ambos generan `WorkflowGraph` v2 con reglas distintas (lineal vs DAG) |
| B4 | Patch | patch de plan (no persistido) vs patch de grafo (persistido) | Sí en propósito, complementarios en capacidad; ninguno cubre el ciclo completo |
| B5 | Simulación | `simulation_plan` (texto) vs `/run simulate` (real) | Sí en propósito; el texto no aporta garantía |
| B6 | Validación | `validate_semantic_plan` vs `validate_plan` (legacy) vs `validate_graph` vs `publication_blockers` | Capas disjuntas, ninguna valida precondiciones de runtime |
| B7 | Estado de disponibilidad de integración | `load_capabilities` (sin estado) vs `capabilities._installed_status` (con estado) vs `resolver.resolve_capability` (con proveedores) | Sí: tres lecturas distintas del mismo hecho; solo la del planner está incompleta |
| B8 | Durabilidad | runs normales vs `WorkflowInstance` | No redundante, pero desconectada: no hay decisión automática "este flujo necesita instancia" |
| B9 | Catálogo de pasos de negocio | `NODE_METADATA` (29) vs `NODE_BUSINESS_SCHEMAS` (20) vs `PLAN_STEP_TYPES` (18) | Sí: tres vocabularios del mismo dominio, sin validación cruzada que garantice cobertura |
