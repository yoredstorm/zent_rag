# Prompt 06 — Workflow Simulation, Validation y Self-Repair

> **Fase:** certificación funcional previa a publicación. **Fecha:** 2026-10-19.
> **Base:** `91a3e18` (Resource Resolution).
> **Alcance:** validación estática, simulación ejecutable aislada, escenarios,
> reportes, reparación semántica acotada y readiness.
> **No** se creó un segundo motor.

## 1. Reutilización del runtime

La simulación ejecutable es `simulate_semantic_plan` / `WorkflowSimulationRunner`.
`simulation_plan()` del Architect queda como **preview teórico**
(`simulation_preview`) y no se presenta como certificación. El Planner agéntico
devuelve `simulation: null` hasta que se ejecuta el endpoint de simulación.

La simulación llama al mismo `execute_graph()` y usa el mismo
`WorkflowGraph` v2, scheduler, nodos, condiciones, WAIT, LOOP y estado durable.
No hay un intérprete alternativo.

Se agregaron controles de ejecución aislada:

- `ExecutionContext.simulate=True`;
- `simulation_state` y `simulation_loops` en memoria, sin DB;
- `execute_graph(..., persist=False)` para no escribir `workflow_run_steps`;
- `pinned` para respuestas de proveedores;
- `pinned_failures` para simular errores de proveedor.

## 2. Validación estática (Parte A)

Antes de simular:

1. `validate_semantic_plan` (existencia, permisos, bindings, contratos,
   aprobación, WAIT/LOOP, versiones).
2. `compile_semantic_plan` al IR v2.
3. `validate_graph` estructural y de puertos.
4. Errores de readiness/binding del snapshot.

Un solo error crítico produce `FAILED_VALIDATION`; no se ejecuta ningún
escenario. Los warnings no se convierten en PASS.

## 3. Simulación ejecutable (Parte B)

`WorkflowSimulationRunner` ejecuta nodos deterministas reales:

- trigger, condition, filter, join, merge, state, notify, business_result,
  approval simulado y stop;
- condiciones y ramas reales;
- referencias de salida reales;
- WAIT y LOOP simulados sin worker esperando;
- estado durable en memoria y transiciones;
- timeout de WAIT como evento de escenario.

Los nodos con efecto externo (`capability_call`, `marketplace_action`,
`api_call`, `llm`, `query_business_data`, `kb_query`, `business_node`) se
sustituyen por `pinned`:

- respuesta del escenario;
- error del escenario;
- o `UNVERIFIED_EXTERNAL_EFFECT` con
  `{"unverified_external_effect": true}`.

Nunca se llaman proveedores reales, no se cobra, no se escribe inventario, no se
envían mensajes y no se crean aprobaciones. El payload de `pinned` se valida
contra `output_schema` cuando existe.

## 4. Escenarios (Parte C)

`SimulationScenario` contiene:

- `initial_inputs`;
- `events` secuenciales (`event_type`, `payload`, `correlation`,
  `idempotency_key`, `port`);
- `responses` por `step_id`, `capability_ref` o `action_id`;
- `expected_state`;
- `expected_outputs`;
- `expected_result` (`PASSED|FAILED|WAITING|UNVERIFIED`);
- `allowed_effects` y `forbidden_effects`;
- `max_segments`.

WAIT se reanuda por segmentos reales del runtime con el payload del evento.
Timeout se representa con `workflow.wait.timeout` o `port="timeout"`.
Señales duplicadas por `idempotency_key` se ignoran y no reejecutan el flujo.
LOOP usa el mismo nodo `loop`, el contador de simulación y el límite; al exceder
el límite el escenario falla.

El escenario comercial del Prompt 06 se representa con eventos/responses
secuenciales; no hay una lista de productos o proveedores hardcodeada.

## 5. Reportes (Parte D)

Cada escenario devuelve `zent.workflow.simulation/v1`:

- `simulation_id`, `workflow_version`, `scenario_id`;
- `result` (`PASSED|FAILED|BLOCKED|UNVERIFIED`);
- `executed_nodes`, `failed_nodes`;
- `branch_coverage`;
- `input_contract_errors`, `output_contract_errors`;
- `unresolved_references`, `missing_dependencies`;
- `unexpected_effects`;
- `state_transitions`;
- `timeline` por segmento y evento;
- `cost_estimate`;
- `repair_suggestions`;
- `unverified_nodes`;
- `trace` read-only.

`zent.workflow.certification/v1` agrega:

`DRAFT`, `NEEDS_CONFIGURATION`, `VALIDATING`, `FAILED_VALIDATION`,
`SIMULATION_PASSED`, `AWAITING_APPROVAL`, `READY_TO_PUBLISH`.

Reglas:

- simulación parcial o `UNVERIFIED` nunca es `READY_TO_PUBLISH`;
- acciones financieras o con aprobación quedan en `AWAITING_APPROVAL`;
- fallo de escenario queda en `FAILED_VALIDATION`;
- solo todos los escenarios PASSED y sin unverified producen `READY_TO_PUBLISH`.

## 6. Reparación (Parte E)

`simulate_with_repair`:

1. simula y obtiene errores estructurados;
2. construye una instrucción mínima con los issues;
3. llama al patch semántico existente (`patch_workflow_plan`);
4. aplica el patch al plan en memoria, nunca al workflow publicado;
5. revalida estática y escenarios afectados;
6. rechaza el patch si aumentan errores estáticos o de simulación;
7. limita intentos (`max_repairs`, máximo 3).

La instrucción prohíbe desactivar validaciones, eliminar ramas críticas, reducir
controles, inventar permisos o credenciales. Si falta configuración o aprobación,
no se simula un éxito; se devuelve el requisito.

Endpoint:

```http
POST /api/v1/workflows/architect/simulate
POST /api/v1/workflows/architect/simulate/repair
```

Ambos son server-side, read-only y requieren `workflows:create`.

## 7. Seguridad y aislamiento

- no SQL del LLM;
- no llamadas HTTP durante la simulación;
- no `execute_binding`;
- no persistencia de nodos/run;
- no aprobaciones reales;
- no instalación ni cambios de permisos;
- el snapshot de capacidades y los bindings son la base de la validación;
- una simulación no autoriza por sí sola la publicación de una acción crítica.

## 8. Pruebas

Archivo `tests/test_workflow_simulation.py`: **15 passed**.

| Escenario | Prueba |
|---|---|
| Lineal real + determinista | `test_linear_simulation...` |
| Ramas y cobertura | `test_branch_simulation...` |
| WAIT + reanudación | `test_wait_simulation...` |
| Timeout | `test_wait_timeout...` |
| LOOP límite | `test_loop_simulation...` |
| Estado durable | `test_state_simulation...` |
| Aprobación simulada sin DB | `test_approval_simulation...` |
| Evento duplicado | `test_duplicate_signal...` |
| Fallo de proveedor | `test_provider_failure...` |
| Externo sin doble | `test_external_without_double...` |
| Efecto prohibido | `test_forbidden_effect...` |
| Plan inválido | `test_invalid_plan...` |
| Contrato de salida | `test_output_contract...` |
| Reparación acotada | `test_bounded_repair...` |
| API | `test_simulation_api...` |

Evidencia adicional: suites de workflows/architect/capability/durable ya
existentes siguen ejecutándose; el runtime conserva `run_workflow` y las
instancias reales para producción.

Regresión ejecutada: `test_workflow_graph`, partial runs, durable instances,
planner agéntico y Semantic v2: **90 passed**.

## 9. Límites declarados

- La simulación de LOOP/WAIT es segmentada sobre el mismo runtime; no usa un
  worker real ni un scheduler en background.
- Las respuestas externas deben declararse en el escenario; si no, el resultado
  es `UNVERIFIED`, nunca PASS.
- La certificación no persiste una simulación en la base; el endpoint la
  devuelve y puede integrarse al gate de publicación en una fase posterior.
- La concurrencia real de señales/instancias se cubre con las pruebas durable
  existentes; la simulación escenifica duplicados y timeouts.
- No se declara Zent listo para producción: falta ejecución con proveedores
  reales y certificación de carga.
