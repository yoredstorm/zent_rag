# 00 — Baseline de realidad

Fecha de corte: `2026-10-23`.
SHA: `0cbb494ce4264077a1e6d4823f4520fbc32928b9`.
Rama: `master`.
Modo: P00, solo auditoría y pruebas. Sin cambios de runtime, sin activar
producción, sin credenciales reales.

## 1. Entorno

| Componente | Valor |
|---|---|
| OS | Windows (win32) |
| Python | 3.13.7 |
| uv | 0.12.13 |
| Node | v22.22.1 |
| npm | 11.17.0 |
| Postgres/Redis | disponibles para la suite local (conexión establecida) |
| Qdrant/LLM real | no usados en P00 |

Evidencia: `artifacts/certification/p00/sha.txt`, `branch.txt`, `git-status.txt`,
`git-diff-stat.txt`, `worktree.diff`, `untracked.txt`.

## 2. Árbol de trabajo

El corte no está limpio. Hay 14 archivos modificados y 4 untracked previos a
P00, más los artefactos de esta fase:

```
 M docs/architecture/ai-workflow-studio/14-workflow-simulation.md
 M docs/architecture/universal-studio/03-gap-matrix.md
 M docs/architecture/universal-studio/12-release-gold.md
 M portal/src/components/WorkflowRunInspector.test.tsx
 M portal/src/components/WorkflowRunInspector.tsx
 M portal/src/components/workflowStudio/WorkflowTestPanel.test.tsx
 M portal/src/components/workflowStudio/WorkflowTestPanel.tsx
 M portal/src/lib/workflowGraph.test.ts
 M portal/src/lib/workflowGraph.ts
 M src/platform/workflows/engine.py
 M src/platform/workflows/runtime.py
 M src/platform/workflows/workflow_simulation.py
 M tests/test_workflow_graph.py
 M tests/test_workflow_partial_runs.py
?? portal/src/lib/workflowEffects.test.ts
?? portal/src/lib/workflowEffects.ts
?? src/platform/workflows/effect_verification.py
?? tests/test_workflow_effect_verification.py
```

Diff acumulado: 14 archivos, 374 inserciones, 47 eliminaciones. El WIP incluye
la clasificación run-level de efectos (`effect_verification.py`) y cambios de
`WorkflowTestPanel`/`WorkflowRunInspector`. No se revierte ni se commitea. Los
resultados de abajo aplican a este árbol, no a un `0cbb494` limpio; cualquier
fallo atribuible al WIP se marca como tal.

## 3. Migraciones, flags y CI

| Elemento | Estado verificado |
|---|---|
| Alembic head | `163_role_profiles_and_solutions.py` (`revision="163"`, `down_revision="162"`); no existe 164 |
| `ZENT_GOLD_RELEASE_ENABLED` | `false` por defecto (`src/core/config.py:202`) |
| `WORKFLOW_ARCHITECT_ENABLED` | `true` por defecto (`src/core/config.py:198`) |
| CI principal | `.github/workflows/ci.yml`: lint, pip-audit, invariants, pytest completo, `tests/certification/workflows`, SDKs, portal typecheck/lint/test/build, Playwright, build |
| Nightly | `.github/workflows/nightly.yml`: full suite, restart real (`RAG_CERT_REAL_RESTART=1`), baterías, estabilidad |
| Docs previos | `12-release-gold.md` = NO-GO; `03-gap-matrix.md` mantiene U-01/U-02/U-03/U-06 P0 |

## 4. Comandos y resultados

Todos los comandos se ejecutaron sobre el árbol descrito. Los JUnit quedan en
`artifacts/certification/p00/`.

| # | Comando | Resultado | Duración | Evidencia |
|---|---|---|---|---|
| 1 | `pytest` dirigido: architecture, authority, authorization, flags, safety, openapi, test_report, durable_instances, role_profiles, studio, architect_canonical | **146 passed**, 0 failed | 450.53 s | `junit-targeted.xml` |
| 2 | `pytest tests/red` (xfail estricto) | **8 xfailed**, 0 failed | 66.03 s | `junit-red-xfail.xml` |
| 3 | `pytest tests/red --runxfail` | **8 failed** por las causas P0 documentadas | 65.98 s | `junit-red-proof.xml` |
| 4 | `npm run typecheck` | exit 0 | < 300 s | salida de consola |
| 5 | `npm run lint` | exit 0, 0 errors, 22 warnings preexistentes | > 300 s; primer intento timeout a 300 s, segundo con 600 s OK | salida de consola |
| 6 | `npm test` | **124 files passed**, 781 tests passed, 1 expected fail (P00 red) | 584.58 s | salida de consola |
| 7 | `npm run build` | exit 0, built in 1 m 10 s | 70 s | salida de consola |
| 8 | `pytest tests/` completo | **NOT_VERIFIED**: el proceso terminó con exit 1 tras 17 m 33 s sin JUnit y con log vacío; no se declara verde | 17 m 33 s | sin `junit-full.xml` (no generado) |
| 9 | `pytest tests/certification/workflows/test_gold_sales_funnel.py` | **1 passed** | 269.27 s | `junit-gold-sales.xml` |
| 9b | `pytest tests/certification/workflows/test_durability_restart.py::test_restart_resumes_same_instance_and_sells_exactly_once` | **1 passed** | 258.90 s | `junit-restart.xml` |
| 9c | Subconjunto de 7 tests Gold sales + restart | **2 passed y timeout** a los 600 s en el tercer test (`test_gold_duplicate_webhook_has_single_business_effect`); resto `NOT_VERIFIED` | 600 s | salida de consola, sin JUnit |
| 10 | Playwright `e2e/workflows.spec.ts` | no ejecutado; no se levantó API/servidor en P00 | N/A | `NOT_VERIFIED` |

### 4.1 Detalle de los rojos (prueba real, no xfail)

`pytest tests/red --runxfail` falla en:

| Test | Causa observada |
|---|---|
| `test_publish_effectful_workflow_without_server_certificate_is_denied` | `POST /publish` devuelve 200 y activa un workflow con `capability_call` sin certificado |
| `test_activate_rejects_client_supplied_certificate` | `POST /activate` devuelve 200 con un certificado forjado en `graph.metadata` |
| `test_manual_run_of_wait_graph_creates_durable_instance` | `POST /run` devuelve `status=failed` sin `instance_id` (`state.append requiere una instancia durable`) |
| `test_schedule_due_of_wait_graph_creates_durable_instance` | el schedule dispara pero `workflow_instances` queda en 0 |
| `test_instance_list_does_not_leak_across_workspaces` | el listado con `X-Workspace-Id: B` incluye la instancia de A |
| `test_signal_from_other_workspace_is_denied` | una señal desde B resume y completa la instancia de A |
| `test_notify_node_is_denied_without_permission` | `notify` ejecuta con `permissions=frozenset()` y termina `simulated`, no `denied` |
| `test_wellness_capability_decision_is_wired_into_workflow_runtime` | `nodes.py`/`runtime.py` no contienen `capability_decision`; la autonomía del rol de bienestar no se consulta en el runtime |

El test de portal `WorkflowTestPanel.p00.red.test.tsx` queda `1 expected fail`:
selecciona `provider`, ejecuta y el request a `/run` no contiene `test_level`.

## 5. Limitaciones y estados no verificados

- **Suite completa**: terminó con exit 1 a los 17 m 33 s, sin escribir
  `junit-full.xml` y con log vacío. No hay evidencia de qué test falló ni de que
  el resto pase. Estado: `NOT_VERIFIED`; no se declara verde.
- **Certification workflows**: se verificaron individualmente el Gold de ventas
  (`test_gold_retail_sales_funnel_end_to_end`) y el reinicio con venta exacta
  (`test_restart_resumes_same_instance_and_sells_exactly_once`). El intento de
  correr los 7 tests juntos pasó 2 y excedió 600 s en el tercero
  (`test_gold_duplicate_webhook_has_single_business_effect`). Los 5 restantes
  quedan `NOT_VERIFIED`, incluida la suite completa de certification.
- **Playwright**: no se levantó API ni servidor de portal; estado `NOT_VERIFIED`.
  Comando exacto en staging: `cd portal; npx playwright test e2e/workflows.spec.ts`.
- **Lint**: el primer intento excedió 300 s sin fallar; el segundo con 600 s
  terminó con 0 errores. Se registra la duración como `> 300 s`, no como un
  pase instantáneo.
- **WIP**: los archivos modificados pueden alterar resultados respecto al SHA
  limpio. No se atribuyen al HEAD estable sin comparación.

## 6. Diferencias respecto al corte de referencia del documento

- El corte de referencia cita `0cbb494ce4`; coincide con el SHA actual.
- El árbol tiene WIP posterior que no está en ese commit, principalmente
  `effect_verification` y cambios de UI de test. La auditoría los trata como
  parte del estado actual, no como código de `0cbb494`.
- `docs/architecture/universal-studio/README.md` cita la migración 162; el HEAD
  tiene 163. Se registra como deuda documental P2-01.

## 6.1 Actualización P01

P01 cerró P0-01/P0-02/P0-03: `release_policy.py`, migración 164 y
`tests/test_workflow_publication_gate.py` (9 passed). El rojo histórico de
`tests/red/test_p00_publish_gate_red.py` se retiró al quedar verde; su JUnit
sigue en `artifacts/certification/p00/junit-red-proof.xml`. La suite roja actual
tiene 6 tests (durables, workspace y policy), no 8. Detalle y límites en
`03-p01-release-gate.md`.

## 6.2 Actualización P02

P02 cerró P0-04 y P1-05: `ingress.py` + migraciones 165/166; triggers manual,
schedule, hook y event abren `WorkflowInstance` cuando el grafo tiene WAIT,
approval o loop. Evidencia: 7 tests de ingress, **440 tests workflow passed**,
Gold ventas + reinicio 2/2. La suite roja actual baja a 4 tests (workspace y
policy); detalle en `04-p02-durable-ingress.md`. El head de migraciones es 166.

## 6.3 Actualización P03

P03 agregó `solution_compiler.py`, migración 167, endpoints
`/studio/solutions/{compile,materialize}` y la página `/solutions/new`. Una
misión genera blueprint portable, rol, agente activo y workflow draft, con
idempotencia y rollback. Evidencia: 9 tests P03, 32 tests de rol/migración/gate
y 3 tests de UI. Detalle en `05-p03-solution-compiler.md`; el head de
migraciones es 167.

## 6.4 Actualización P04

P04 agregó `planner_budget.py`, `planner_diagnostics.py`, caché de tools,
clarificaciones estructuradas, fases COMPILE/READINESS/COST y estado
fail-closed para agente ausente. El harness de evaluación registra provenance,
separa métricas y puede fallar por umbrales. Evidencia: 45 tests P04/planner y
39 tests Architect. La calidad real con proveedor y el dataset ≥100/dominio
siguen `NOT_VERIFIED`; detalle en `06-p04-planner.md`.

## 6.5 Actualización P05

P05 agregó `policy_enforcement.py` como PEP único de nodos, exige
`workflows:run` para nodos internos, aplica rol/autonomía y guardrail de
bienestar, filtra instancias/signals por workspace y congela el rol en
`definition_snapshot.policy_snapshot`. Evidencia: 56 tests de policy/workspace/
aprobaciones/RBAC, 110 tests de grafos directos y 41 tests core de workflow. Los P0-05,
P0-06 y P0-08 quedan cerrados; memoria por workspace se cerró en P06. Detalle en
`07-p05-policy-enforcement.md`.

## 6.6 Actualización P06

P06 agregó scope/workspace/sujeto/consentimiento a `memory_records` (migración
168), un único `context_service` que aplica la política del rol, memoria
autorizada en el contexto del agente, revocación/borrado, endpoint “qué sabe el
agente”, drawer de memoria y una ruta real para `data_mapper`. Evidencia: 68
tests backend, 15 tests de portal y typecheck/lint OK. La
memoria sigue siendo la existente; no hay store paralelo. Detalle en
`08-p06-context-memory.md`.

## 6.7 Actualización P07

P07 publicó `SubflowDefinition` con snapshot congelado, estado y puertos;
bloquea WAIT/LOOP/aprobación inline; añadió `error_contract.py` con ocho puertos
tipados, límites de fan-out, plan de compensación en orden inverso, API de
biblioteca y drawer **Subflujos**. Evidencia: 95 tests backend, 17 tests de
portal y typecheck/lint OK. No hay migración. Detalle en
`09-p07-subflows-errors.md`.

## 6.8 Actualización P08

P08 añadió el endpoint canónico `/workflows/{id}/test`, nivel efectivo decidido
por servidor, reporte persistido en `workflow_test_reports` (migración 169) con
hashes de grafo/plan/rol/bindings, degradación explícita de sandbox/provider y
panel sin `PROVIDER_VERIFIED` falso. Evidencia: 88 tests backend, 30 tests de
portal, typecheck/lint OK. El rojo P0-07 quedó retirado. Detalle en
`10-p08-test-studio.md`.

## 6.9 Actualización P09

P09 añadió `/solutions/:solutionId` con estado real, barra persistente, modos
Simple/Guiado/Avanzado, pestañas de resumen/proceso/configuración/conversación,
primer uso, publicación solo con gate `ALLOW`, copiloto de diff y undo/redo del
canvas. Evidencia: 5 + 1 + 13 + 1 tests de portal, typecheck y eslint de
archivos P09 OK. Multi-select,
estudio con 5 usuarios y E2E de accesibilidad quedan NOT_VERIFIED. Detalle en
`11-p09-solution-workspace.md`.

## 6.10 Actualización P10

P10 auditó el marketplace global y añadió `GET /workflows/capabilities/discover`
sobre el mismo `canvas_context`; el canvas enlaza a la tienda y solo inserta
acciones instaladas. `return_to` sigue saneado, la instalación contextual
reutiliza el mismo registro y el blueprint portable no cambia. Evidencia: 40
tests backend. Detalle en `12-p10-marketplace.md`.

## 6.11 Actualización P11/P12

P11 añadió la cola de operación/dead-letter y resumen en la consola sobre
`workflow_instances`, sin estado nuevo. P12 formalizó la matriz de seis roles y
el reporte de gates: GO para staging; NO_GO para piloto controlado/GA por UX de
5 usuarios, proveedor real y chaos de Redis/Postgres no verificados. Evidencia
en `13-p11-operations.md`, `14-p12-certification.md` y
`artifacts/certification/p11|p12`.

## 7. Dictamen P00

**GO P00 (auditoría), NO-GO release.**

- Los P0 están confirmados por código y por rojo reproducible
  (`pytest tests/red --runxfail`: 8 fallos con la causa documentada).
- Los entregables de auditoría existen y citan `file:line`.
- No hay cambios nuevos en `src/` atribuibles a P00: el estado de `src/` sigue
  siendo el WIP preexistente (engine, runtime, workflow_simulation,
  effect_verification).
- La suite completa, el lote de certification y Playwright quedan
  `NOT_VERIFIED`; por tanto este GO no autoriza release ni producción. P01
  puede planificarse, pero debe reauditar el HEAD y no reutilizar estos
  resultados como evidencia de release.
- `ZENT_GOLD_RELEASE_ENABLED` permaneció apagado. No se usaron proveedores,
  pagos ni credenciales reales.
