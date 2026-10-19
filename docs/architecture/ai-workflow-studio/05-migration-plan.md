# 05 — Plan de migración incremental y reversible

> Reglas: nada toca instancias activas ni `definition_snapshot`; toda fase es activable/desactivable por flag; cada fase deja el sistema coherente si se detiene.

## Principios

1. **Compatibilidad total hacia atrás.** `WorkflowGraph` v1/v2, `steps[]`, planes legacy, workflows persistidos y paquetes importados siguen funcionando igual.
2. **Aditivo antes que sustitutivo.** Se añaden claves a las respuestas antes de cambiar consumidores.
3. **Un solo cambio de comportamiento por fase**, con flag y telemetría.
4. **Sin migraciones destructivas.** Toda tabla nueva es aditiva; ningún `UPDATE` masivo sobre `workflows`, `workflow_runs` o `workflow_instances`.
5. **Reversible.** Cada fase define su rollback exacto (flag off / revert del commit).

## Fases

### M0 — Instrumentación y línea base (sin cambios de comportamiento)

| Cambio | Archivo | Detalle |
|---|---|---|
| Métricas de uso del Architect | `src/platform/workflows/architect_metrics.py` | contadores ya existentes; asegurar que `/architect/plan` y `/architect/patch` registren `source` (`llm`/`heuristics`) |
| Telemetría del camino legacy | `src/api/routes/workflows.py` | log estructurado en `/copilot/*` con `workflow_id` resultante (para medir adopción y retirar el legacy con datos) |
| Baseline de readiness | `readiness.py` | endpoint ya existente: registrar cuántos workflows nativos tendrían `error` (fase report-only de ADR-5) |

**Rollback:** quitar logs/contadores.
**Riesgo:** nulo (solo observación).

### M1 — Cerrar la brecha de planificación (backend, sin UI)

| Cambio | Archivo | Detalle |
|---|---|---|
| Snapshot de capacidades con estado | `architect_discovery.py` | `capabilities[]`, `actions[]` con estado (reusar `_installed_status`), KBs con nombre, canales, `requires_approval`/`risk_level`/`read_only`/`cost` |
| Digest desde el catálogo autorizado | `architect_discovery.py`, `node_catalog.py` | `capability_digest` compone `build_node_catalog()` por tenant (contratos, `when_to_use`, `what_it_needs`) |
| Vocabulario v2 del plan | `architect_models.py` | tipos nuevos + `for_each.body` + `wait.on_timeout_step` + `state.path` obligatorio |
| Precondiciones y severidades | `architect_validator.py` | tabla de `03-target-architecture.md` §4; cuerpos anidados |
| Contrato de ejecución por nodo | `node_catalog.py` | constantes `NODE_EXECUTION_CONTRACT` (retry/timeout/error/durability) |
| Compilación completa | `architect_compiler.py` | `_branch`, puerto `timeout`, `capability_call`, `loop`, `ai_decision`, `api_call`, `set_variable`, `business_node`; políticas desde el contrato |
| Patch sobre vocabulario v2 | `architect_patch.py` | `add_step`/`remove_step` con cuerpos anidados |
| Trazas | nueva migración `…_workflow_plan_traces.py`, `architect.py` | append-only (ADR-7) |

**Rollback:** el vocabulario es aditivo; desactivar la escritura de trazas no afecta la planificación.
**Riesgo principal:** nuevos `error` del validator pueden rechazar planes que antes compilaban (deseado, pero comunicarlo). Mitigación: `source="heuristics"` y reporte de `requirements` claros.

### M2 — Adoptar el Architect en el portal (flag)

| Cambio | Archivo | Detalle |
|---|---|---|
| Cliente del Architect | `portal/src/components/workflowStudio/AskZent.tsx` | `POST /architect/plan`; preview de negocio (`preview`), clarificaciones, requisitos, costo, readiness |
| Cambio conversacional | `AskZent.tsx` | `POST /architect/patch` con `trace_id`; conservar el plan en memoria de la sesión |
| Ver flujo avanzado | `AskZent.tsx` | usa el `graph` del Architect (ya viene compilado y validado) |
| Crear | `AskZent.tsx` | `POST /workflows` con `graph` + `metadata.architect` + `trace_id` |
| Compatibilidad | feature flag `workflow_studio_architect` | off = comportamiento actual; on = Architect |

**Rollback:** flag off.
**Riesgo:** UX de clarificaciones (más preguntas que el copilot). Mitigación: máximo de preguntas priorizadas (ya existe `build_clarifications`).

### M3 — Gate de publicación y durabilidad (por fases, ADR-5)

| Cambio | Archivo | Detalle |
|---|---|---|
| Readiness con precondiciones | `readiness.py` | durabilidad, binding, destinatarios, riesgo de acción, agente obligatorio en v2 |
| Gate de publicación | `versions.py`, `routes/workflows.py` | `blockers` + `acknowledge_blockers` según fase (report-only → warn → block) |
| Arranque durable transparente | `engine.py` (+ helper puro) | `graph_requires_instance()` → `start_workflow_instance` en scheduler/hook/evento/manual |
| Eco solo en legacy | `nodes.py` | error en grafos v2, eco marcado en v1 (ADR-6) |

**Rollback:** fase bajada a `report-only`; el arranque durable es determinístico por grafo (para volver atrás basta revertir el helper).
**Riesgo:** workflows existentes con nodos durables que hoy "fallan y nadie mira" pasarán a ejecutarse como procesos (mejora, pero con más instancias). Mitigación: `expires_at` y `business_key` ya existen en `instances.py`; evaluar un tope operacional de instancias activas por tenant antes de subir de fase.

### M4 — Cobertura de negocio en el planner

| Cambio | Archivo | Detalle |
|---|---|---|
| Discovery de capacidades de negocio | `architect_discovery.py` + `bindings.py` | bindings activos + providers publicados + addons builtin (`auth_modes NONE`) |
| Paso `capability_call` y `conversation.send` | `architect_models.py`, `architect_compiler.py` | config desde binding (`capability`, `inputs`), sin nombrar proveedor |
| `wait` conversacional/pago | `architect_compiler.py`, `instances.py` (solo lectura de presets) | presets y correlación como ya hace el canvas |
| Schemas de negocio faltantes | `parameters.py` | `capability_call`, `wait_event`, `state_*`, `loop` |
| `NODE_NEXT_STEPS.loop` | `node_catalog.py` | siguientes pasos del bucle |

**Rollback:** revertir el commit; los grafos generados con `capability_call` siguen siendo válidos para el canvas.
**Riesgo:** planes con capacidades mal elegidas; mitigación: el validator exige binding y el runtime devuelve `NEEDS_CONFIGURATION` accionable (ya implementado).

### M5 — Calidad, simulación y cierre

| Cambio | Archivo | Detalle |
|---|---|---|
| Dry-run real encadenado | `architect.py`, `routes/workflows.py` | preview + `run simulate` sobre el grafo persistido (ADR-9) |
| Fallback honesto | `architect.py` | si el fallback no puede representar ramas, devuelve `requirements`/`issues` en vez de plan incompleto (F-06) |
| Dataset ampliado | `tests/data/workflow_architect_cases.json`, `tests/test_workflow_architect_eval.py` | casos con `wait`, `loop`, `capability_call`, `for_each` con cuerpo, `ai_decision`, timeout |
| Retiro del modo compatibilidad | `copilot_v2.py`, `routes/workflows.py`, `AskZent.tsx` | solo tras 2 releases con flag on y métricas de uso ≈0 |

**Rollback:** revertir commit; el legacy ya no existe en la UI pero la API se mantiene hasta el retiro formal.

## Compatibilidad explícita

| Activo existente | Estrategia |
|---|---|
| Workflows `graph_source='legacy'` (steps) | No se reescriben. `LegacyWorkflowAdapter` sigue adaptando en runtime. Los checks de readiness los evalúan igual |
| Workflows `graph_source='graph'` v2 sin `metadata.architect` | El gate de M3 los evalúa; en fase `report-only` no se bloquean |
| Planes legacy (`WorkflowPlan`) | `plan_compiler` intacto; `/copilot/compile` sigue funcionando |
| Paquetes importados (`workflows.package`) | `publication_blockers` sigue igual; M3 le suma los checks nativos por la misma vía de readiness |
| Instancias activas (`RUNNING`/`WAITING`) | **Intocadas**: definición congelada en `definition_snapshot`; ningún cambio de M3/M4 las re-ejecuta |
| Versiones y snapshots publicados | Solo lectura; `restore_version` no cambia |
| Bindings y datos de negocio | Solo lectura desde discovery; ninguna fase escribe bindings |
| Plantillas (`workflow_templates`) | Compatibilidad mantenida; las plantillas nuevas podrán usar el vocabulario v2 |

## Orden sugerido de PRs

| PR | Fase | Contenido | Verificación mínima |
|---|---|---|---|
| 1 | M0 | logging + contadores | suite de workflows verde |
| 2 | M1a | discovery + digest | tests de discovery (nuevos) + eval de 50 casos |
| 3 | M1b | validator + contrato de ejecución | eval + tests de validator |
| 4 | M1c | compiler v2 (+ `_branch`, `timeout`) | tests de compiler + certificación gold |
| 5 | M1d | trazas + patch v2 | tests de patch |
| 6 | M3 | readiness + gate + arranque durable | certificación durable/señales + regresión de runs |
| 7 | M2 | UI con flag | tests de portal (`AskZent.test.tsx` ampliado) |
| 8 | M4 | `capability_call` + schemas | certificación commerce/portabilidad |
| 9 | M5 | simulación + fallback + dataset | eval ampliado + certificación completa |
