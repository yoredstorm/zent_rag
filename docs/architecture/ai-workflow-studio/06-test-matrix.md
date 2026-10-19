# 06 — Matriz de pruebas

> La matriz distingue **existente** (ejecutada en esta auditoría o localizable en el repo) de **faltante** (no cubre el hallazgo).

## 1. Inventario existente relevante

| Suite | Archivo | Cubre | Estado en esta auditoría |
|---|---|---|---|
| Architect unitario | `tests/test_workflow_architect.py` | compile de venta con refs semánticas, validator (ciclos, deps, KB, agente, permisos) | ✅ verde |
| Architect patch | `tests/test_workflow_architect_patch.py` | `patch_workflow_plan` (LLM y heurístico) | ✅ verde |
| Architect eval (50 intents) | `tests/test_workflow_architect_eval.py` + `tests/data/workflow_architect_cases.json` | trigger, selección de nodos, agente innecesario, operación KB, requisitos, clarificaciones, readiness/simulation | ✅ verde (22 tests con los dos anteriores) |
| Runtime de grafo | `tests/test_workflow_graph.py` | validación, ejecución, dry-run, parcial | ✅ verde |
| Catálogo semántico | `tests/test_workflow_node_catalog.py` | cobertura metadata↔registry, disponibilidad, siguiente pasos | ✅ verde |
| Durabilidad | `tests/test_workflow_durable_instances.py` | WAIT/RESUME, timeout por puerto, suspensión, cancelación | ✅ verde |
| Join/merge/filter/for_each | `tests/test_workflow_join_merge.py` | semántica de ramas, `for_each` con `_branch` y warning de costo | ✅ verde |
| Marketplace de workflows | `tests/test_workflow_marketplace.py` | canvas context, install inline, costos, recomendaciones | ✅ verde |
| Studio | `tests/test_workflow_studio.py` | endpoints del studio | ✅ verde |
| Núcleo semántico | `tests/test_workflow_semantic_core.py` | contexto, contribuciones, decisiones | ✅ verde |
| Certificación gold | `tests/certification/workflows/test_gold_sales_funnel.py` | funnel retail end-to-end (commerce + pagos + wait + loop + broker de conversación) | ✅ **4 tests verdes** |
| Certificación durable/señales/portabilidad | `tests/certification/workflows/*` | señales, durabilidad tras reinicio, tenant isolation, portabilidad, addons, pagos | localizable, no re-ejecutada completa en esta fase |

## 2. Cobertura de hallazgos (antes)

| Hallazgo | ¿Test que lo detecte hoy? | Comentario |
|---|---|---|
| F-01 UI legacy vs Architect | ❌ | `AskZent.test.tsx` solo prueba el camino legacy |
| F-02 eco silencioso | ❌ | No hay test que publique un grader sin agente y verifique el resultado |
| F-03 publish sin gate | ❌ | No hay test de "activar con readiness en error" |
| F-04 durables en trigger schedule/webhook | ⚠️ parcial | `test_workflow_durable_instances` siempre usa `/instances`; no prueba schedule/hook |
| F-05 `for_each` sin `_branch` | ⚠️ parcial | `test_workflow_join_merge` usa `_branch` explícito; no cubre el grafo compilado |
| F-06 fallback pierde ramas | ❌ | No hay test del fallback con draft ramificado |
| F-07 estado de acción | ❌ | `test_workflow_marketplace` cubre el canvas, no el planner |
| F-08/F-09 cobertura de vocabulario | ❌ | No hay test que exija cobertura registry ↔ plan types |
| F-10 digest | ❌ | No hay test de contenido del prompt |
| F-11 precondiciones del validator | ⚠️ parcial | Cubre permisos/disponibilidad, no runtime |
| F-12 riesgo/aprobación de acción | ❌ | — |
| F-13 puerto `timeout` | ⚠️ | Cubierto a nivel runtime, no a nivel compiler |
| F-14 patch de estructura | ❌ | `patch/apply` no tiene caso "agregar nodo" |
| F-15 trazas | ❌ | — |
| F-16 intent no usado | ❌ | — |
| F-17 costo | ❌ | No hay caso con schedule `daily` |

## 3. Pruebas nuevas requeridas (por fase)

| Fase | Tipo | Test | Criterio de aceptación |
|---|---|---|---|
| M1 | unit | `test_architect_discovery.py::test_capabilities_snapshot_states` | `capabilities[]` refleja `_installed_status` (habilitada/credenciales/purpose) y `actions[]` coincide con el canvas |
| M1 | unit | `test_architect_discovery.py::test_digest_includes_contracts_and_kb_names` | el digest contiene `when_to_use` de al menos 10 nodos, nombres de KB y estado de acciones |
| M1 | unit | `test_workflow_architect.py::test_capability_call_step_compiles` | plan con `capability_call` → nodo `capability_call` con `capability`+`inputs`; sin binding → `error` con `requirement` |
| M1 | unit | `test_workflow_architect.py::test_for_each_body_compiles_to_branch` | plan con `for_each.body` → `config._branch` con los ids de los nodos del cuerpo; sin cuerpo → `error` |
| M1 | unit | `test_workflow_architect.py::test_wait_timeout_branch_wires_port` | `on_timeout_step` → edge desde el puerto `timeout`; **el grafo compilado siempre pasa `validate_graph`** (regresión de F-24) |
| M1 | unit | `test_workflow_architect.py::test_validator_requires_durable` | plan con `wait`/`loop` → issue `runtime.requires_instance` + action `run_as_process` |
| M1 | unit | `test_workflow_architect.py::test_node_execution_contract_applied` | el grafo generado usa retry/timeout del contrato (no 60s fijo) |
| M1 | unit | `test_workflow_plan_traces.py` | `/architect/plan` persiste traza; el hash del plan coincide con el que aplica `/architect/patch` |
| M1 | regresión | `test_workflow_architect_eval.py` | los 50 casos siguen verdes + 8 casos nuevos (wait, loop, capability_call, for_each con cuerpo, ai_decision, api_call, estado, timeout) |
| M3 | integración | `test_workflow_readiness_gate.py` | fase `warn`: publish devuelve `blockers` y exige `acknowledge`; fase `block`: 422; fase `report-only`: publica y registra |
| M3 | integración | `test_workflow_durable_triggers.py` | workflow con `wait_event` disparado por schedule **y** por hook **y** por evento arranca instancia y queda `WAITING`; sin nodos durables sigue siendo run normal |
| M3 | unit | `test_workflow_nodes_echo_contract.py` | grafo v2 sin agente → `failed` con mensaje accionable; grafo v1 → eco marcado y readiness `error` |
| M2 | UI | `AskZent.test.tsx` (ampliado) | con flag on llama `/architect/plan`; muestra preview/clarificaciones/requisitos; "Cambiar algo" llama `/architect/patch` con `trace_id` |
| M4 | certificación | `test_gold_sales_funnel.py` (invariante) | ningún cambio de engineering altera el resultado del gold |
| M4 | certificación | nuevo `test_architect_generates_commerce_flow.py` | el planner (provider plantilla) genera un grafo con `capability_call` para `catalog.products.search` y el validator lo acepta con bindings del fixture del gold |
| M5 | integración | `test_architect_simulation.py` | `/architect/plan` con `simulate=true` ejecuta dry-run sin efectos y devuelve `planned_effects` |
| M5 | unit | `test_architect_fallback.py` | fallback con draft ramificado devuelve plan completo o `requirements`; nunca omite pasos en silencio |

## 4. Matriz capacidad → cobertura objetivo

| Conjunto de capacidades | Unitario | Integración | Certificación |
|---|---|---|---|
| Triggers (event/schedule/webhook/manual) | ✔ | ✔ | gold + señales |
| Datos (`query_business_data`, `kb_query`) | ✔ | ✔ | knowledge_* + data_catalog |
| IA (`llm`, `ai_decision`) | ✔ | ✔ (v2) | semantic_core / jev |
| Lógica (`condition`, `filter`, `join`, `merge`, `set_variable`) | ✔ | ✔ | join_merge + gold |
| Iteración (`for_each` con cuerpo, `loop`) | ✔ (nuevo) | ✔ (nuevo) | gold (loop) |
| Durabilidad (`wait_event` + señales + timeout) | ✔ | ✔ (nuevo disparador) | durable_instances + señales |
| Estado (`state_*`) | ✔ | ✔ | gold |
| Capacidades de negocio (`capability_call`) | ✔ (nuevo) | ✔ (nuevo) | gold + addon_contracts |
| Marketplace (`marketplace_action`, install/resolución) | ✔ | ✔ | marketplace_dependency_resolution |
| Salidas (`notify`, `business_result`) | ✔ | ✔ | notifications + gold |
| Seguridad (permisos, SSRF, tenant) | ✔ | ✔ | tenant_isolation + provider_failure |

## 5. Reglas de verificación

1. Ninguna capacidad se declara terminada sin: (a) test unitario del contrato, (b) ejecución real (no mock del executor) en integración o certificación, (c) evidencia en el PR.
2. Los tests del eval del Architect usan provider determinístico; la corrida con LLM real es un job opcional y nunca el único gate.
3. Todo test nuevo debe fallar antes del cambio (regla TDD) y quedar registrado en `08-findings-plan-risks.md` §4 con el resultado.
