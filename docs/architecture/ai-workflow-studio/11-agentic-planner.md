# Prompt 03 — Agentic Workflow Planner con tool calling

> **Fase:** planificación agéntica. **Fecha:** 2026-10-19.
> **Base:** commits `53b4abd` (auditoría), `d2fb77a` (Architect canónico), `e926050`
> (Capability Registry). **Alcance:** capa de planificación, no runtime.
> **Regla:** el LLM propone; el backend valida, autoriza, compila y persiste.
> Este documento **no declara Zent listo para producción**.

## 1. Problema y resultado

El flujo anterior era de una sola pasada:

`Prompt → ArchitectIntent → SemanticPlan → Graph`

El LLM no podía investigar el catálogo, inspeccionar contratos, resolver
ambigüedades ni corregir errores con evidencia. El nuevo flujo es una sesión con
etapas explícitas:

`UNDERSTAND → DISCOVER(tools) → MATCH → PLAN → VERIFY → REPAIR → PRESENT`

El resultado conserva `WorkflowGraph` v2, `execute_graph()`, `run_workflow()`,
`WorkflowInstance`, WAIT/RESUME, Marketplace, bindings, `capability_call` y los
contratos de comercio. No se agregó motor, scheduler, bus, cola ni runtime.

## 2. Componentes

| Archivo | Responsabilidad |
|---|---|
| `src/platform/workflows/planner_session.py` | `WorkflowPlanningSession`, presupuesto, trazas, loop de acciones, reparación y presentación |
| `src/platform/workflows/planner_tools.py` | catálogo de herramientas read-only, validación estricta de argumentos, despacho y marcado de datos no confiables |
| `src/platform/workflows/planner_verify.py` | verificación determinista de matches, contratos de entrada/salida, aprobaciones críticas, WAIT/LOOP y durabilidad |
| `src/platform/workflows/architect_models.py` | `SemanticPlan` con `loop`, `retries`, `timeout_seconds`, `on_error` y `PlanIssue` estructurado |
| `src/platform/workflows/architect_compiler.py` | LOOP con edge de re-entrada; reintentos/timeout/error policy reales del runtime |
| `src/platform/workflows/architect_validator.py` | WAIT (preset, timeout, evento), estado durable, LOOP acotado y errores con contrato |
| `src/api/routes/workflows.py` | `POST /api/v1/workflows/architect/agentic-plan` con cancelación y presupuesto |
| `portal/src/components/workflowStudio/ArchitectAskZent.tsx` | muestra matches, trazas, durabilidad y mantiene el guardado canónico |

## 3. LLM Gateway y tool calling

Se inspeccionó el Gateway real. `LLMProvider.generate()` acepta `prompt`,
`system_prompt`, `model`, `max_tokens` y `temperature`; **no existe** soporte
nativo de `tools`/`tool_calls` en el puerto (`src/core/ports/rag_ports.py:219`).
Por eso se implementó el adaptador permitido por el prompt: **acciones JSON con
esquema estricto, validadas y despachadas exclusivamente por el servidor**.

El LLM solo puede devolver:

```json
{"action":"tool","tool":"capability.search","arguments":{"query":"productos","limit":5}}
{"action":"plan","plan":{...SemanticPlan...},"matches":[...],"clarifications":[]}
{"action":"clarify","questions":["¿Cuál fuente uso?"],"reason":"..."}
```

No puede invocar funciones Python. Un nombre fuera del catálogo se rechaza con
`tool_not_allowed`; argumentos inválidos con `tool_invalid_arguments`. El
servidor no ejecuta ninguna acción de escritura durante la planificación.

El system prompt incluye el **catálogo de herramientas del Planner**, no el
catálogo de capacidades del tenant. Los nombres de capacidades se descubren con
`capability.search` y se inspeccionan con `capability.inspect`. Esto evita
hardcodear las capacidades en el prompt.

## 4. Herramientas read-only

| Herramienta | Uso | Límite |
|---|---|---|
| `capability.search` | buscar por intención, sinónimos y aliases | `max_candidates` |
| `capability.inspect` | contrato completo, permisos, riesgo, errores | 1 ref |
| `capability.list_dependencies` | composición y dependencias | 1 ref |
| `capability.check_availability` | disponibilidad real por tenant | 1 ref |
| `capability.resolve_binding` | binding sin secretos; exige `workflows:*` | 1 ref |
| `resource.discover` | KB, DB y conectores del tenant | 50 |
| `resource.inspect_schema` | schema conocido del recurso | 1 ref |
| `event.inspect` | evento y campos | 1 evento |
| `workflow.template.search` | plantillas reutilizables | `max_candidates` |
| `workflow.template.inspect` | plantilla y dependencias | 1 slug |

Toda observación se serializa como:

```json
{
  "untrusted_data": true,
  "injection_suspected": false,
  "observation": {"tool":"capability.inspect","data":{...}}
}
```

Si se detectan instrucciones en descripciones/metadata se agrega
`security_notice` y `injection_suspected=true`. El servidor no ejecuta esas
instrucciones; las herramientas siguen siendo read-only y el plan pasa por
validación determinista.

## 5. Presupuesto y control

`PlannerBudget` (`planner_session.py`) limita por sesión:

- llamadas LLM (`WORKFLOW_PLANNER_MAX_LLM_CALLS`, default 8)
- llamadas a herramientas (`WORKFLOW_PLANNER_MAX_TOOL_CALLS`, 16)
- tokens (`WORKFLOW_PLANNER_MAX_TOKENS`, 20 000)
- costo estimado (`WORKFLOW_PLANNER_MAX_COST_USD`, 0.50 + tarifas opcionales)
- duración (`WORKFLOW_PLANNER_MAX_DURATION_SECONDS`, 90)
- reparaciones (`WORKFLOW_PLANNER_MAX_REPAIRS`, 2)
- candidatos por búsqueda (`WORKFLOW_PLANNER_MAX_CANDIDATES`, 5)
- pasos del loop (`WORKFLOW_PLANNER_MAX_STEPS`, 8)

La duración usa `asyncio.timeout`; la cancelación usa `asyncio.Event` y se
propaga desde el cierre de conexión del endpoint. Los tokens se contabilizan
desde la respuesta del Gateway. El costo es una **estimación** basada en tarifas
configurables; no reemplaza el billing real. La sesión registra una fila agregada
en `usage_events` (`event_type="workflow_planner"`) reutilizando `UsageEngine`,
sin crear otro sistema de billing. El registro es best-effort: un fallo de
contabilidad no convierte un plan inválido en válido.

## 6. Verificación y reparación

`validate_semantic_plan` sigue siendo la primera barrera (forma,
dependencias, ramas, permisos, disponibilidad, inputs requeridos). Luego
`planner_verify.verify_plan` agrega:

- cada capacidad/agente usado tiene un `match` con necesidad y motivo;
- cada capacidad de negocio usada fue inspeccionada en la sesión
  (`capability.inspect`); sin contrato recuperado, el plan se rechaza con
  `planner.capability_not_inspected`;
- la capacidad existe y está ejecutable; si no, se devuelve requisito explícito;
- versión del match contra el catálogo;
- alternativas consideradas cuando el proveedor las declara o la búsqueda
  devolvió varias;
- campos de entrada/salida contra `input_schema`/`output_schema`;
- aprobación humana ancestro para acciones `critical`/`financial` o con
  `requires_approval`;
- WAIT con rama de timeout si `on_timeout="branch"`;
- LOOP con target existente y `1 ≤ max_iterations ≤ 100`;
- estado durable marcado como `requires_durable_instance`;
- salida terminal (`notify`/`business_result`/`stop`) como warning.

Los errores se entregan al Planner con: `issue_code`/`code`, paso, campo,
contrato esperado, contrato recibido, alternativas y acción requerida. El
Planner puede corregir como máximo `max_repair_attempts` veces. Si repite el
mismo `plan_hash`, se detiene con `planner.repeated_plan`; no se reintenta
indefinidamente. Los errores críticos nunca se degradan a warnings.

Ejemplo de issue de reparación:

```json
{
  "issue_code": "contract.output_unknown",
  "code": "contract.output_unknown",
  "severity": "error",
  "step_id": "stock",
  "field": "inputs.field",
  "message": "«Consultar stock» usa «items» de «Buscar productos», pero ese campo no está en su salida.",
  "expected": "products",
  "received": "items",
  "alternatives": ["products"],
  "action_required": "Elige un campo de salida del contrato."
}
```

## 7. Incertidumbre

El Planner debe usar `clarify` cuando falte información indispensable o cuando
elegir entre fuentes equivalentes cambie el resultado, los permisos o una
escritura. El endpoint devuelve `state="NEEDS_CLARIFICATION"`, preguntas y la
especificación parcial; no inventa una fuente ni crea un nodo genérico.

Si una capacidad no existe o no está ejecutable, el plan no la simula: devuelve
`missing.capability`/`capability.unavailable` y un `requirement`
(`capability:<ref>`), que el portal muestra como dependencia pendiente.

## 8. LOOP, WAIT y estado durable

- `loop`: `params.target` debe ser un paso existente, distinto de sí mismo, con
  `max_iterations` entre 1 y 100. El compilador emite el nodo `loop` y un edge
  explícito al target; el IR lo trata como re-entrada durable acotada, no como
  ciclo del grafo.
- `wait`: valida preset, `on_timeout` y evento; si la política es `branch`,
  exige un paso con `when {step, outcome:false}`.
- `state`: exige `params.path`.
- Todo plan con WAIT/LOOP/estado se presenta con
  `requires_durable_instance=true` y la advertencia `runtime.requires_instance`.
  El usuario debe iniciarlo como `WorkflowInstance`; no se afirma que un run
  simple sobreviva a la espera.

## 9. API

```http
POST /api/v1/workflows/architect/agentic-plan
Content-Type: application/json

{
  "prompt": "Cuando el stock sea menor a 10 avisa a compras",
  "model": null,
  "session_id": "ds_...",
  "clarification_history": ["..."]
}
```

- `200`: propuesta con `state`, `specification`, `plan`, `matches`, `issues`,
  `graph`, `readiness`, `trace`, `usage`, `requires_durable_instance`.
- `429`: `PLANNER_BUDGET_EXCEEDED` con `reason` y `usage`.
- `409`: `PLANNER_CANCELLED` (cliente desconectado o cancelación explícita).

La respuesta mantiene los campos del contrato canónico (`phases`, `fallback`,
`intent`, `preview`, etc.) para que el portal no necesite un segundo parser.
`fallback` es siempre `null` en el camino agéntico: un fallo del LLM devuelve
`BLOCKED`, no un plan heurístico que simule haber investigado.

## 10. Trazabilidad

Cada respuesta incluye:

```json
{
  "trace": {
    "path": ["NECESIDAD","BÚSQUEDA","INSPECCIÓN","SELECCIÓN","PLAN","VALIDACIÓN","REPARACIÓN"],
    "stages": [{"name":"UNDERSTAND","duration_ms":12}],
    "tool_calls": [
      {"tool":"capability.search","arguments":{"query":"productos","limit":5},"ok":true,"duration_ms":3}
    ],
    "repair_attempts": 0
  },
  "usage": {
    "llm_calls": 3,
    "tool_calls": 1,
    "prompt_tokens": 900,
    "completion_tokens": 500,
    "total_tokens": 1400,
    "estimated_cost_usd": 0.0,
    "duration_ms": 1800,
    "repairs": 0
  }
}
```

También se emite `planner.agentic.completed` por logging estructurado con
`session_id`, organización, workspace, estado, tool names, códigos de issue,
tokens y duración. No se registran secretos: los argumentos de tools se
resumen y los bindings se resuelven sin devolver credenciales.

## 11. Matriz de pruebas

Archivo: `tests/test_workflow_planner_agentic.py` (23 pruebas, snapshot sintético
y endpoint real con provider falso; no ejecuta acciones externas).

| # | Escenario obligatorio | Prueba | Evidencia |
|---|---|---|---|
| 1 | Capacidad exacta conocida | `test_01_...` | búsqueda + inspección + plan + grafo |
| 2 | Sinónimos | `test_02_...` | `consultar existencias` encuentra `inventory.stock.get` |
| 3 | Dos equivalentes | `test_03_...` | CSV/XLSX en resultados y `alternatives` en el match |
| 4 | Capacidad ausente | `test_04_...` | `missing.capability` + requirement, sin nodo falso |
| 5 | Parámetro obligatorio desconocido | `test_05_...` | `missing.capability_input` con contrato |
| 6 | Salida incompatible | `test_06_...` | `contract.output_unknown` |
| 7 | JSON inválido | `test_07_...` | `BLOCKED`, sin plan heurístico |
| 8 | Tool no autorizada | `test_08_...` | `tool_not_allowed` en la traza |
| 9 | Error reparable | `test_09_...` | `REPARACIÓN` + `repairs=1` + grafo |
| 10 | Aclaración humana | `test_10_...` | `NEEDS_CLARIFICATION` con preguntas |
| 11 | Presupuesto agotado | `test_11_...` | `PlannerBudgetExceeded(tool_calls)` |
| 12 | Cancelación | `test_12_...` | `PlanningCancelled` |
| 13 | Inyección en metadata | `test_13_...` | `injection_suspected=true`; tool maliciosa rechazada |
| 14 | Reintento sin duplicar | `test_14_...` | `planner.repeated_plan`; 3 llamadas, sin efectos |
| 15 | LOOP acotado | `test_15_...` | nodo `loop`, edge de re-entrada, durable |
| 16 | Aprobación crítica | `test_16_...` | `approval.critical_action` |
| 17 | UNDERSTAND conserva pedido | `test_17_...` | especificación y modo agéntico |
| 18 | Endpoint | `test_18_...` | 200, header, traza y grafo |
| 19 | Tokens/costo | `test_19_...` | `tokens` y `cost` agotan |
| 20 | Candidatos | `test_20_...` | límite aplicado por el servidor |
| 21 | LOOP inválido | `test_21_...` | target trigger rechazado |
| 22 | WAIT sin rama | `test_22_...` | `wait.timeout_branch_missing` |
| 23 | Plan sin inspección | `test_23_...` | `planner.capability_not_inspected`; exige contrato antes de planear |

Resultados locales:

- `tests/test_workflow_planner_agentic.py`: **23 passed**.
- Regresión Architect/Registry/Studio/Readiness: **54 passed**.
- Suite de workflows (CRUD, patches, Architect, registry): **73 passed**.
- Runtime/grafo/durabilidad/readiness/marketplace: **99 passed**.
- Certificación de workflows (`tests/certification/workflows`): **37 passed**.
- Frontend `ArchitectAskZent.test.tsx`: **8 passed**; `tsc --noEmit`,
  `eslint` y `vite build` sin errores.

## 12. Límites declarados

- El Gateway actual no expone tool calling nativo. El adaptador JSON es
  determinista y validado, pero no es el protocolo nativo del proveedor.
- La calidad de un LLM real no se certifica con providers falsos; las pruebas
  verifican contratos, seguridad, presupuesto y reparación, no la calidad
  semántica de un modelo específico.
- El historial de snapshots y el costo real dependen de la infraestructura
  existente (historial en proceso; tarifas opcionales). No se agregó una tabla
  de billing.
- `for_each` sigue bloqueado por el validator; LOOP es la re-entrada soportada.
- Los planes con WAIT/LOOP requieren iniciarse como proceso durable; el planner
  lo declara, no lo simula.
- No se declara producción lista: faltan pruebas con proveedores reales,
  evaluación de calidad por modelo, y la migración de los 9 schemas de negocio
  pendientes identificados en la auditoría.
