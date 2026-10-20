# Prompt 04 — Semantic Compiler Enterprise

> **Actualización Prompt 05:** la resolución de fuentes, autoridad y bindings se
> implementa en [`13-business-resources.md`](13-business-resources.md); el plan
> sigue usando referencias lógicas y no IDs físicos.

> **Fase:** evolución del lenguaje semántico y su compilador. **Fecha:** 2026-10-19.
> **Base:** `047c345` (Agentic Planner). **Alcance:** `SemanticPlan`,
> `architect_compiler`, `architect_validator`, IR v2 y runtime existente.
> **No** se creó otro motor, scheduler, bus ni cola.

## 1. Resultado

El plan semántico puede expresar todas las primitivas relevantes del runtime y
sigue compilando a `WorkflowGraph` v2:

```text
INTENCIÓN → SEMANTICPLAN v2 → GRAPH IR v2 → execute_graph()/WorkflowInstance
```

No hay traducciones manuales por ejemplo. El compilador es determinista y el
validator bloquea grafos que solo pasaron Pydantic.

## 2. Esquema v2 y compatibilidad

`SemanticPlan.schema_version`:

- `"1.0"`: planes persistidos antes de esta entrega.
- `"2.0"`: contratos tipados y primitivas nuevas.
- `normalize_semantic_plan(plan)` es el adapter explícito; no muta el plan
  original. Compilador, validator y sesión agéntica lo aplican.

Tipos semánticos nuevos:

| Tipo | Compila a | Uso |
|---|---|---|
| `trigger_conversation` | `trigger_event` con `conversation.message` | Inicio por mensaje del cliente |
| `compensation` | `capability_call` o `marketplace_action` en rama `error` | Compensación de una acción fallida |

El resto del vocabulario se apoya en primitivas existentes:

`trigger_event`, `trigger_schedule`, `trigger_manual`, `business_query`,
`knowledge_query`, `capability_call`, `agent_analysis`, `decision`, `filter`,
`join`, `merge`, `human_approval`, `wait`, `state`, `loop`, `notify`,
`integration_action`, `business_result`, `stop`.

## 3. Contratos tipados

`architect_step_contracts.py` valida los `params` principales:

- `CapabilityCallParams`: capability, inputs, contract_version,
  outputs_expected, idempotency.
- `IntegrationActionParams`: action_id, install_id, inputs, versión,
  outputs_expected, idempotency.
- `WaitParams`: preset, event_type, correlation, timeout_seconds, on_timeout,
  expected_payload_schema.
- `LoopParams`: target, max_iterations, exit_condition, state_dependencies.
- `StateParams`: op, path, value_type, source_reference, value.
- `CompensationParams`: target_step, capability/action_id, inputs, versión,
  idempotency.
- `TriggerConversationParams`, `StopParams`, `BusinessResultParams`,
  `HumanApprovalParams`, `KnowledgeQueryParams`.

Los modelos aceptan claves extra para no romper planes históricos; las claves
conocidas dejan de ser `Any` sin contrato y producen issues de reparación
`contract.params_invalid`.

`PlanStep` ahora declara también `contract_version`, `outputs_expected` e
`idempotency`.

## 4. Capability Call

El compilador distingue:

- capacidad interna o binding: `capability_call`;
- acción externa instalada: `marketplace_action`.

No convierte capacidades internas a Marketplace. Para `capability_call`
resuelve, en tiempo de compilación, la proyección del snapshot:

- `contract_version` y `contract_hash`;
- `provider_kind` y `source`;
- `risk_level` y `side_effects`;
- `required_permissions`;
- `idempotency`;
- `outputs_expected`.

El binding real, credenciales y ejecución los resuelve `execute_binding()` en
runtime, con `organization/workspace/actor/instance/node`. El planner nunca ve
secretos.

## 5. WAIT y RESUME

`WaitStep` compila a `wait_event` con:

- `preset` y `event_type`;
- `correlation` con referencias reales:
  `{"order_id": {"step": "crear", "field": "order_id"}}` →
  `{{nodes.<id>.output.order_id}}`;
- `timeout_seconds` y `on_timeout`;
- `expected_payload_schema`;
- `resume_mode="durable_instance"`.

El runtime existente suspende la instancia y libera el worker. La reanudación
usa el checkpoint y el segmento del wait, no reinicia el workflow. El schema
esperado se guarda en `waiting_for`; al llegar un signal, `_claim_and_resume`
valida el payload **antes** de reclamar la instancia. Un payload inválido queda
`payload_invalid` y no consume la instancia.

La correlación de conversación sigue usando `conversation_id` de la instancia
para `preset="message"`. Para pagos/webhooks/signals el validator recomienda
correlación explícita y timeout; no inventa una correlación silenciosa.

## 6. LOOP

`LoopStep` compila a `loop` con:

- `target` resuelto a node id;
- `max_iterations` entre 1 y 100;
- `exit_condition` validada contra una decisión/espera;
- `state_dependencies`;
- edge explícito de re-entrada al target.

El grafo ordinario sigue acíclico: el IR excluye el edge que sale de `loop`.
La instancia durable conserva estado y checkpoint del cuerpo. La salida real del
loop la expresa la decisión que corta la repetición; el `loop` solo materializa
el reingreso acotado. Nunca hay un `while` generado por el LLM.

En cuerpos con acciones financieras, el validator exige/avisa
`idempotency=required`; el runtime usa `instance_id + node_id` como identidad
estable y no duplica cobros/checkouts.

## 7. Estado durable

`StateStep` compila a `state_set/get/merge/append/remove` y acepta:

- `path`;
- `op`;
- `value_type`;
- `source_reference` que se convierte en una referencia de nodo real.

El estado se escribe en `WorkflowInstance`; no vive en memoria del proceso.

## 8. Referencias y tipos

`architect_typecheck.py` resuelve JSON Schema real:

- paths anidados (`producto.id`, `items[0].sku`);
- objetos, arrays, números, enteros, strings, booleanos y null;
- `$ref` local y `allOf` básico;
- inputs literales y referencias entre pasos;
- `outputs_expected` contra el `output_schema`.

Códigos principales:

`contract.output_unknown`, `contract.input_unknown`,
`contract.type_mismatch`, `contract.outputs_missing`,
`contract.literal_type`, `contract.version_mismatch`,
`contract.idempotency_required`.

No se acepta una referencia sintácticamente válida a un campo inexistente. Un
schema desconocido no se inventa: se trata como no verificable, no como
compatible.

## 9. Compensación por fallo

`compensation` compila la acción de reversión como `capability_call` o
`marketplace_action`. El paso protegido recibe:

- `error_policy="branch"`;
- puerto de salida `error`;
- edge `error` hacia la compensación.

El runtime ya existente incorpora una rama de error acotada: un fallo con
`error_policy="branch"` activa el puerto `error`, salta la continuación normal y
permite ejecutar la compensación. La rama debe cerrar preferentemente con `stop(status="failed")`; un
`business_result` es informativo y no convierte el fallo en éxito. Si no hay
cierre fallido, el run termina fallido, nunca como éxito silencioso. No es un
nuevo motor: usa el scheduler, los nodos y los ejecutores existentes.

## 10. Validación y publicación

`validate_semantic_plan` agrega:

- contratos tipados;
- tipos de datos entre pasos;
- versiones de contrato;
- disponibilidad, riesgo y permisos;
- aprobación humana para acciones críticas/financieras;
- WAIT: evento, timeout, rama de timeout, payload schema;
- LOOP: target, orden, límite, salida, idempotencia;
- compensación: target, acción, orden, cierre fallido;
- complejidad.

Al publicar, `_capability_publication_problems` revalida contra el snapshot vivo:

- existencia y ejecución;
- `contract_version`/`contract_hash` del grafo compilado;
- permisos del actor que publica.

Un cambio de capacidad o de permisos entre compilar y publicar bloquea la
publicación.

## 11. Complejidad

- Límite semántico: **80 pasos** (`MAX_SEMANTIC_STEPS`).
- El ejemplo certificado de ventas usa aproximadamente 40 nodos.
- El runtime tiene guard de **10 000** iteraciones del scheduler.
- >40 pasos emite warning `plan.large_complexity` para revisar costo/latencia.
- No se aumentó sin pruebas: la suite cubre 80 como techo del contrato y el
  guard del runtime sigue siendo el límite operativo.

## 12. Pruebas

Archivo `tests/test_workflow_semantic_v2.py`: **18 passed**.

| Escenario obligatorio | Prueba |
|---|---|
| Adapter v1→v2 | `test_v1_plan_adapter...` |
| Workflow lineal + capacidad interna | `test_linear_capability...` |
| Múltiples ramas | `test_multiple_branches...` |
| WAIT | `test_wait_compiles...` |
| Payload del WAIT al siguiente paso | `test_wait_resume_exposes...` |
| LOOP + estado durable | `test_loop_and_state...` |
| Agente + aprobación | `test_agent_and_human_approval...` |
| Operación financiera | `test_financial_action_...` |
| Compensación | `test_compensation_...` y `test_runtime_error_branch...` |
| Referencia de salida inválida | `test_invalid_output_reference...` |
| Cambio de versión | `test_capability_contract_version...` |
| Cambio de permisos al publicar | `test_publish_gate...` |
| Evento duplicado | `test_duplicate_signal...` |
| Payload de señal inválido | `test_wait_payload_schema...` |
| Idempotencia en LOOP | `test_loop_body_financial...` |
| Límite de complejidad | `test_plan_step_limit...` |
| Plan de 80 pasos compila | `test_eighty_step...` |

Evidencia complementaria:

- Architect/canonical/patch/eval: **42 passed**.
- Graph, durable instances, patches, plan, readiness, studio, marketplace:
  **89 passed**.
- Agentic planner: **23 passed**.
- Semantic v2: **18 passed**.
- Semantic core/business schema/node catalog: **53 passed**.
- Certificación de workflows (`tests/certification/workflows`): **37 passed**.
- `ruff src tests`: OK.

## 13. Límites declarados

- La compensación cubre acciones capability/action; no implementa sagas
  arbitrarias con coordinadores externos.
- `exit_condition` se valida contra una decisión/espera; el reingreso real lo
  acota el runtime y el límite del loop.
- El validador de payload implementa el subconjunto usado por los contratos
  (type/required/properties/items); no es un validador JSON Schema completo.
- Los workflows manuales fuera de Architect mantienen su comportamiento; las
  reglas nuevas aplican a grafos nacidos del plan semántico.
- No se declara Zent listo para producción: falta prueba con capacidades reales
  de todos los proveedores y cargas empresariales completas.
