# 08 — Hallazgos, plan de implementación, riesgos y evidencia

## 1. Tabla de hallazgos

| ID | Sev | Hallazgo (una línea) | Evidencia (archivo:línea) | Módulo dueño | Fase de fix |
|---|---|---|---|---|---|
| F-01 | P0 | El portal usa el Copilot legacy; el Architect no tiene interfaz | `AskZent.tsx:85,101`; `routes/workflows.py:180-219`; sin refs a `architect` en `portal/src` | Portal + routes | M2 |
| F-02 | P0 | `llm` sin agente devuelve eco con `succeeded` | `nodes.py:2056-2057,2042-2051`; `architect_validator.py:208-218`; `readiness.py:109-123` | nodes / validator | M1, M3, M4 |
| F-03 | P0 | Publicación/activación sin gate para workflows nativos | `versions.py:303-311`; `packages.py:618-619`; `routes:748-770,1058-1077` | versions / routes | M3 |
| F-04 | P0 | `wait_event`/`loop` publicables pero no ejecutables desde schedule/webhook/manual | `nodes.py:2941-2944,3018-3019`; `engine.py:1548-1557,1598+`; `routes:772-797,800-838` | engine / instances | M1, M3, M4 |
| F-05 | P0 | `for_each` compilado sin `_branch`: no ejecuta cuerpo | `nodes.py:2628-2632,2656-2668`; `architect_compiler.py:245-254`; `portal/src/lib/workflowGraph.ts:609` | archivo: architect_compiler | M1 |
| F-06 | P0 | Fallback heurístico descarta ramas/acciones anidadas | `architect.py:162-223,269-277`; `copilot.py:101-141` | architect | M5 |
| F-07 | P1 | Disponibilidad de acciones desalineada (enabled/credenciales/purpose) | `plan_compiler.py:125-141` vs `runtime.py:1253-1259,1267-1283,1353`; `capabilities.py:112-169` | plan_compiler / discovery | M1 |
| F-08 | P1 | El planner no puede expresar `capability_call` (commerce/conversación/pagos) | `architect_models.py:15-34`; `nodes.py:3116-3155`; `commerce/contracts.py:47-70` | architect_models / compiler | M1, M4 |
| F-09 | P1 | El planner no puede expresar `loop`, `ai_decision`, `api_call`, `set_variable`, `business_node`, `end` | enumeración registry (29) vs `PLAN_STEP_TYPES` (18) | architect_models | M1 |
| F-10 | P1 | Digest del prompt más pobre que el del Copilot legacy | `architect_discovery.py:202-240` vs `node_catalog.py:742-777` | architect_discovery | M1 |
| F-11 | P1 | Validator sin precondiciones de runtime | `architect_validator.py:53-354` | architect_validator | M1 |
| F-12 | P1 | El planner no ve `requires_approval`/riesgo de acciones | `capabilities.py:92-108` vs `architect_discovery.py:126-133`; `runtime.py:1260-1265` | architect_discovery | M1 |
| F-13 | P1 | Puerto `timeout` de `wait_event` nunca conectado | `architect_compiler.py:186,382-398`; `plan_compiler.py:467-483`; `runtime.py:651-657` | architect_compiler | M1 |
| F-14 | P1 | Edición conversacional partida (no agrega/quita pasos en workflows existentes) | `patches.py:89-98`; `architect_patch.py:126-172`; `AskZent.tsx:294-302` | patches / architect_patch | M2, M5 |
| F-15 | P1 | Sin trazas persistidas de intent/plan | `architect.py:569-660`; `docs/architecture/workflow-architect.md:202` | architect + migración | M1 |
| F-16 | P1 | `ArchitectIntent` no influye en la compilación | `architect_compiler.py:305-310` | architect_compiler | M1 |
| F-17 | P2 | Costo mensual mal estimado en schedules `daily`/`weekly` | `architect.py:348-358`; `capabilities.py:391-398` | architect / capabilities | M1 |
| F-18 | P2 | 9/29 nodos sin schema de negocio | `parameters.py:797` | parameters | M4 |
| F-19 | P2 | `NODE_NEXT_STEPS` sin `loop` | `node_catalog.py:40-72` | node_catalog | M4 |
| F-20 | P2 | Métricas del Architect solo en proceso | `architect_metrics.py` | architect_metrics | M5 |
| F-21 | P2 | `semantic_preview` sin entradas para `wait`/`state`/`stop` | `architect.py:298-315` | architect | M1 |
| F-22 | P2 | Readiness sin severidad por nodo completo | `readiness.py:109-123,221-245` | readiness | M3 |
| F-23 | P2 | Workflows v2 creados con `steps: []` | `AskZent.tsx:132-144`; `engine.py:837-848` | portal / engine | M2 |
| F-24 | P0 | El Architect devuelve un grafo que `validate_graph` rechaza (nunca valida el resultado) | `architect.py:607-611`; `architect_compiler.py:186,387-388`; `engine.py:837-840` | architect / architect_compiler | M1 |
| F-25 | P1 | Gate de permisos parcial: solo `external_actions:execute` y `agents:execute` se exigen a nivel nodo | `nodes.py:43-47`; `routes:777,460`; `notifications:send` y `business_results:write` no existen en `src/` | nodes / rbac | M3 (decisión de producto) |

## 2. Plan de implementación por archivos

Orden por dependencia. "Flag" indica la palanca de rollback.

| # | Archivo | Cambio | Fase | Depende de | Flag / rollback |
|---|---|---|---|---|---|
| 1 | `src/platform/workflows/capabilities.py` | exponer `_installed_status` y `_org_manifests` como API estable (sin `_`) para discovery | M1a | — | rename interno |
| 2 | `src/platform/workflows/architect_discovery.py` | snapshot con `capabilities[]`, `actions[]` con estado, KBs con nombre, canales, watchers; digest desde `build_node_catalog()` | M1a | 1 | claves nuevas |
| 3 | `src/platform/workflows/node_catalog.py` | `NODE_EXECUTION_CONTRACT` (retry/timeout/error/durabilidad) + `NODE_NEXT_STEPS["loop"]` + `requires_instance(node_type)` | M1a | — | constante |
| 4 | `src/platform/workflows/architect_models.py` | `PLAN_STEP_TYPES` v2 + `for_each.body` + `wait.on_timeout_step` + `state.path` obligatorio | M1b | 3 | aditivo; planes v1 válidos |
| 5 | `src/platform/workflows/architect_validator.py` | precondiciones (`03` §4), cuerpos anidados, severidades, `requirements` accionables | M1b | 2,4 | issues nuevos |
| 6 | `src/platform/workflows/architect_compiler.py` | `_branch`, puerto `timeout`, `capability_call`, `loop`, `ai_decision`, `api_call`, `set_variable`, `business_node`, políticas del contrato, `end` opcional; usar `intent` para trigger/costo; **puerto correcto por tipo de predecesor** (no `then/else` sobre `wait_event`) | M1c | 4,5 | grafo v2 |
| 7 | `src/platform/workflows/architect.py` | trazas, preview corregido, costo con schedule real, fallback honesto, **`validate_graph` obligatorio del resultado compilado** | M1d/M5 | 6 | escritura de trazas |
| 8 | `src/infrastructure/db_init/versions/15x_workflow_plan_traces.py` | tabla append-only de trazas | M1d | — | tabla aditiva |
| 9 | `src/platform/workflows/architect_patch.py` | patch sobre vocabulario v2 (cuerpos, `capability_call`, `wait` con rama) | M1d | 4,6 | ops aditivas |
| 10 | `src/platform/workflows/readiness.py` | checks de durabilidad, binding, destinatarios, riesgo, agente obligatorio en v2; `node_issues` completo | M3 | 3,5 | checks nuevos |
| 11 | `src/platform/workflows/versions.py` | gate por fases (report-only/warn/block) + `acknowledge_blockers` | M3 | 10 | flag `workflow_publish_gate` |
| 12 | `src/api/routes/workflows.py` | `acknowledge_blockers` en publish/activate; `trace_id` en patch; usar readiness en activate | M3 | 11 | parámetro opcional |
| 13 | `src/platform/workflows/engine.py` | `graph_requires_instance()` + arranque de instancia en scheduler/hook/evento/manual | M3 | 3,5 | decisión determinística |
| 14 | `src/platform/workflows/instances.py` | endpoint/servicio de arranque reutilizable desde triggers (sin lógica nueva) + auditoría del modo | M3 | 13 | — |
| 15 | `src/platform/workflows/nodes.py` | eco solo para grafos legacy; error accionable en v2 | M3 | 6 | ADR-6 |
| 16 | `portal/src/components/workflowStudio/AskZent.tsx` | cliente del Architect, preview, clarificaciones, requisitos, patch con `trace_id`, dry-run | M2 | 6,7 | flag `workflow_studio_architect` |
| 17 | `portal/src/components/workflowStudio/WorkflowPatchPanel.tsx` | soportar `add_step`/`remove_step` (payload del backend) | M5 | 9 | — |
| 18 | `src/platform/workflows/parameters.py` | schemas de `capability_call`, `wait_event`, `state_*`, `loop` | M4 | 3 | aditivo |
| 19 | `src/platform/workflows/bindings.py` | helper de lectura para discovery (`list_bindings` ya existe) + contrato de estado | M4 | 1 | — |
| 20 | `tests/data/workflow_architect_cases.json` + `tests/test_workflow_architect_eval.py` | 8 casos nuevos + aserciones de cobertura | M5 | 4,6 | — |
| 21 | `docs/architecture/workflow-architect.md` | actualizar estado real (UI no conectada, gaps) | M0 | — | — |

### Piezas que NO se tocan

`src/platform/workflows/runtime.py` (salvo la lectura del nuevo puerto ya soportada), `src/platform/workflows/ir.py`, `src/platform/workflows/context_store.py`, `src/platform/workflows/contributions.py`, `src/platform/marketplace/**`, `src/platform/commerce/**`, `tests/certification/workflows/gold_support.py`.

## 3. Riesgos de regresión

| # | Riesgo | Prob. | Impacto | Mitigación | Detección |
|---|---|---|---|---|---|
| R1 | Nuevos `error` del validator rechazan planes que hoy compilan | Alta | Medio | Fase `report-only` en readiness + `requirements` accionables; mantener severidad `warning` para KB ambigua en el primer release | eval de 50 casos + telemetría de `requirements` |
| R2 | Arranque durable en scheduler genera más instancias y carga | Media | Medio | Activarlo solo si `graph_requires_instance`; `expires_at` y `business_key` ya existen | certificación durable + métricas de instancias |
| R3 | Eco → error en v2 rompe workflows existentes | Media | Alto | Discriminar por `workflow_version`/`metadata.legacy` (ADR-6) | test de contrato + gold + regresión de `test_workflows.py` |
| R4 | Cambio del prompt del planner degrada calidad | Media | Medio | Mantener el eval determinístico como gate; comparar `valid_rate` antes/después | `tests/test_workflow_architect_eval.py` |
| R5 | `_branch` mal calculado produce ejecuciones incorrectas | Baja | Alto | Validator exige ≥1 paso en el cuerpo y referencias existentes; test de compiler + ejecución con `for_each` real | `test_workflow_join_merge` + nuevo test |
| R6 | El gate de publicación bloquea workflows válidos en producción | Media | Alto | Fases + `acknowledge_blockers`; nunca bloquear `pause`/`deactivate` | test de gate + monitoreo de 4xx en publish |
| R7 | Trazas almacenan datos sensibles | Baja | Alto | Guardar hash del prompt + plan normalizado; nunca el prompt crudo por defecto; retención por política del tenant | revisión de esquema + test de redacción |
| R8 | Duplicidad de lógica entre `plan_compiler` y `architect_compiler` | Alta | Medio | Marcar `plan_compiler` como camino legacy de compatibilidad; no añadir features nuevas ahí | revisión de cambios |
| R9 | Regresión en instancias activas | Baja | Crítico | Ninguna fase escribe `workflow_instances` ni `definition_snapshot`; prohibido en NO-GO (N6) | certificación de durabilidad tras reinicio |
| R10 | Deriva entre `PLAN_STEP_TYPES` y registry | Media | Medio | Test de cobertura automática (registry ↔ plan types ↔ schemas) | test nuevo de cobertura |

## 4. Evidencia de las verificaciones realizadas

Todo lo siguiente se ejecutó en esta máquina sobre el árbol `70620a9`, sin modificar código.

### 4.1 Enumeración del registry (sin mocks)

Comando: `.venv\Scripts\python.exe -c "…registry.all()…"` (ver `06-test-matrix.md` §5).
Resultado:

```
registry            29  ['ai_decision','api_call','business_node','business_result','capability_call',
                         'condition','end','filter','for_each','human_approval','join','kb_query','llm','loop',
                         'marketplace_action','merge','notify','query_business_data','set_variable','state_append',
                         'state_get','state_merge','state_remove','state_set','stop','trigger_event',
                         'trigger_schedule','trigger_webhook','wait_event']
metadata            29  (mismo conjunto)
business_schemas    20  faltan: capability_call, end, loop, state_append, state_get, state_merge,
                         state_remove, state_set, wait_event
plan_step_types     18  ['trigger_event','trigger_schedule','trigger_manual','business_query','knowledge_query',
                         'agent_analysis','decision','filter','for_each','join','merge','human_approval','wait',
                         'state','notify','integration_action','business_result','stop']
reachable_nodes     22  ['business_result','condition','filter','for_each','human_approval','join','kb_query','llm',
                         'marketplace_action','merge','notify','query_business_data','state_append','state_get',
                         'state_merge','state_remove','state_set','stop','trigger_event','trigger_schedule',
                         'trigger_webhook','wait_event']
unreachable_nodes    7  ['ai_decision','api_call','business_node','capability_call','end','loop','set_variable']
```

### 4.2 Mapeo paso semántico → nodo (compilador real)

Ejecutado con `_step_config` sobre los 18 tipos de paso:

```
trigger_event      -> trigger_event        in=[]     out=[out]
trigger_schedule   -> trigger_schedule     in=[]     out=[out]
trigger_manual     -> trigger_webhook      in=[]     out=[out]
business_query     -> query_business_data  in=[in]   out=[out]
knowledge_query    -> kb_query             in=[in]   out=[out]
agent_analysis     -> llm                  in=[in]   out=[out]
decision           -> condition            in=[in]   out=[out,then,else]
filter             -> filter               in=[in]   out=[out]
for_each           -> for_each             in=[in]   out=[out,done]      (sin _branch)
join               -> join                 in=[in]   out=[out]
merge              -> merge                in=[in]   out=[out]
human_approval     -> human_approval       in=[in]   out=[out]
wait               -> wait_event           in=[in]   out=[out,timeout]   (timeout nunca conectado)
state              -> state_set            in=[in]   out=[out]
notify             -> notify               in=[in]   out=[out]
integration_action -> marketplace_action   in=[in]   out=[out]
business_result    -> business_result      in=[in]   out=[out]
stop               -> stop                 in=[in]   out=[out]
```

### 4.3 Observación directa de handlers y del compiler (sin mocks, sin escritura en BD)

Script temporal (`%TEMP%\opencode\zent_prompt00_evidence.py`), ejecutado con `.venv` y `PYTHONPATH` del repo:

| Observación | Resultado real |
|---|---|
| `_exec_llm` con `config={"prompt": "Analiza el riesgo del cliente"}` y sin `agent_id`, permisos `agents:execute` | `error = None`; `output = {"echo": true, "model": "gpt-4o-mini", "text": "[gpt-4o-mini] Analiza el riesgo del cliente", "warning": "El nodo no tiene agente asignado: esto es un eco, no la respuesta de un agente."}` → confirma F-02 |
| `_exec_for_each` con `collection=[1,2,3]` y **sin** `_branch` | `error = None`; `items_processed = 3`; `results = {}` → confirma F-05 |
| `_exec_wait_event` con `preset=payment` y sin instancia | `error = "wait_event requiere una instancia durable (inicia el flujo como proceso)"` → confirma F-04 |
| `compile_semantic_plan` con plan `wait` + rama (`when: {step: w, outcome: false}`) + `for_each` | nodo `wait_event` con puertos `out`/`timeout`; edges `[('t','out','w'), ('w','else','exp'), ('t','out','fe')]`; `issues = []` → la rama sale por el puerto **`else`**, que no existe; el `for_each` queda sin `_branch` |
| `validate_graph` sobre ese grafo | `WorkflowGraphError: edge e2: w no tiene puerto de salida else` → confirma F-24 |

Conclusión: `/architect/plan` puede responder `graph != null` con `issues` vacíos y el grafo es rechazado después por `POST /workflows`.

### 4.4 Suite del Architect
```
.venv\Scripts\python.exe -m pytest tests/test_workflow_architect.py \
    tests/test_workflow_architect_eval.py tests/test_workflow_architect_patch.py -q
→ 22 passed, 3 warnings in 92.02s
```

### 4.5 Certificación end-to-end (Postgres local real)

```
.venv\Scripts\python.exe -m pytest tests/certification/workflows/test_gold_sales_funnel.py -q
→ 4 passed, 3 warnings in 209.79s
```

Conectividad verificada: `SELECT 1` OK; la suite usa la base local (no mocks del executor).

### 4.6 Inspección del catálogo real del entorno local (dev)

| Tabla | Conteo |
|---|---|
| `integration_manifests` | 10 |
| `integration_actions` | 14 (12 read-only, 2 de escritura, 1 con `requires_approval`) |
| `integration_capabilities` | 8 slugs (`conversation.send`, `demo_records`, `echo`, `exchange`, `identity`, `pokemon`, `taxpayer`, `weather`) |
| `marketplace_products` | 30 |
| `workflow_templates` | 14 |
| `installed_integrations` | 0 (tenant local sin instalaciones) |
| `workflows` / `workflow_runs` / `workflow_instances` | 0 / 0 / 0 |

Contraste verificado: `capabilities._ACTION_HINTS` (`capabilities.py:22-27`) referencia `peru.taxpayer.lookup`, `peru.identity.verify`, `currency.current_rate`, `demo.echo`; los cuatro existen como acciones activas en el entorno local.

### 4.7 Suite de workflows ampliada

```
.venv\Scripts\python.exe -m pytest tests/test_workflow_node_catalog.py \
    tests/test_workflow_durable_instances.py tests/test_workflow_join_merge.py \
    tests/test_workflow_graph.py tests/test_workflow_studio.py \
    tests/test_workflow_marketplace.py tests/test_workflow_semantic_core.py -q
→ 86 passed, 3 warnings in 756.01s (0:12:36)
```

### 4.7b Estado del árbol de trabajo

```
git status --short   → ?? docs/architecture/ai-workflow-studio/
git diff --stat      → (vacío)
```

Solo se agregó documentación; ningún archivo versionado fue modificado.

### 4.8 Verificación pendiente / no realizada en esta fase

- Certificación completa de `tests/certification/workflows/` (portabilidad, addons, pagos, tenant isolation, reinicio): localizable, no re-ejecutada en esta fase por presupuesto de tiempo (solo el gold sales funnel, §4.5).
- Corrida con LLM real: **no ejecutada** (el eval usa provider plantilla). No se declara calidad de prompt medida con modelo.
- Verificación en producción: **no realizada** (la base inspeccionada es local/dev).

## 5. Declaración de cierre

- Esta fase **no** modifica código de producción: solo agrega documentación.
- **No** se declara Zent listo para producción.
- La auditoría permite identificar exactamente las piezas a modificar (`§2`) para que un requerimiento empresarial en lenguaje natural se convierta en un `WorkflowGraph` correcto y ejecutable.
- Los hallazgos P0 tienen dueño, evidencia y fase de corrección; los P1 explican las automatizaciones empresariales hoy imposibles.
