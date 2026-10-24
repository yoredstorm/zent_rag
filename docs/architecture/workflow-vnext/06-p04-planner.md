# 06 — P04: Workflow Architect 2.0

Fecha: `2026-10-23`.
Base: `0cbb494ce4` + P00–P03.

## 1. Cambios implementados

| Área | Cambio | Evidencia |
|---|---|---|
| Preflight budget | `planner_budget.py` estima prompt+completion, reservas de UNDERSTAND/PLAN+VERIFY/REPAIR y shortfall de tokens/coste/llamadas antes de la primera llamada | `planner_budget.py`; `planner_session.py` guarda `budget_estimate` |
| Fases | `DISCOVERY`, `UNDERSTAND`, `COMPILE`, `READINESS`, `COST` se instrumentan además de las etapas existentes; cada una tiene duración | `planner_session.py:_stage` |
| Discovery | caché por `snapshot_hash + tool + argumentos` dentro de la sesión; repetir búsqueda/inspector no vuelve a ejecutar el handler y marca `cached` | `planner_tools.py`; `tests/test_planner_tool_cache.py` |
| Clarificaciones | payload estable con `question_id`, `severity`, `field`, `expected`, `received`, `alternatives`, `action_required`, `resolved`; códigos `contract.*` convertidos en preguntas; orden determinista | `architect_clarifications.py`; `tests/test_planner_clarifications.py` |
| Estado fail-closed | `plan.agent_needs_selection` deja de ser DRAFT_READY: un LLM sin agente exige configuración | `architect_observability.py`; `tests/test_architect_design_state.py` |
| Diagnóstico | `planner_diagnostics.py` traduce códigos/presupuesto a mensaje + CTA; los 429 de planner ya no devuelven solo `presupuesto agotado: reason` | `planner_diagnostics.py`; rutas `/architect/agentic-plan` y sesiones |
| Reparación | las reparaciones semánticas deterministas se exponen en `deterministic_repairs`, no solo en notas internas | `planner_session.py` |
| Evaluación | harness con `--per-domain`, `--domains`, `--seed`, `--model`, `--max-cost`, provenance (SHA/dataset/model/seed), métricas por dominio/estado/error, p50/p95/p99 y gate de umbrales | `scripts/certification/eval_universal_cases.py` |

## 2. Comportamiento de presupuesto

`preflight_budget` es **advisory** en el resultado: no sustituye el corte duro
de `PlannerBudget`. Si el presupuesto es insuficiente, el planner expone
`budget_estimate.feasible=false` y el runtime sigue fallando con
`PlannerBudgetExceeded` cuando corresponde. Un budget agotado nunca se
presenta como `DRAFT_READY` ni como plan publicable.

## 3. Clarificaciones y reparación

`build_clarifications` ahora entrega preguntas accionables con contrato estable.
Los errores de tipo/contrato (`contract.output_unknown`, `input_unknown`,
`type_mismatch`, `params_invalid`, etc.) ya no terminan en un BLOCKED sin
pregunta. Las respuestas siguen reanudando la misma sesión; la UI puede usar
`question_id` para marcar resueltas.

La reparación determinista sigue limitada a las transformaciones existentes
(aprobar pasos críticos, cerrar ramas de timeout y sintetizar matches de
agente). No se permite eliminar controles de seguridad ni cambiar la autoridad
del grafo.

## 4. Evaluación

Dataset actual: `tests/certification/ai/universal_cases.json`, **100 casos,
10 por dominio**. El harness ya soporta muestra por dominio, pero el dataset
todavía no tiene 100 casos por dominio. Los campos `capability_refs` mezclaban
node types con capabilities; el harness ahora separa `expected_capabilities`
(real refs con punto) y `step_types`, y calcula recall de capacidades y
cobertura de tipos por separado.

Métricas añadidas: `by_domain`, `states`, `errors_by_reason`,
`capability_recall_rate` (solo casos con capabilities reales),
`step_type_coverage_rate`, `safety_rate`, p50/p95/p99, tokens/coste y
`graph_valid_rate_resolved`. El script falla con exit code si se pasan
`--fail-under-*` y no se alcanzan.

## 5. Pruebas ejecutadas

| Comando | Resultado |
|---|---|
| `pytest tests/test_planner_budget.py tests/test_planner_tool_cache.py tests/test_planner_clarifications.py tests/test_architect_design_state.py tests/test_workflow_planner_agentic.py tests/test_workflow_planner_output.py -q` | **45 passed** (29.72 s) con `junit-p04.xml` |
| `pytest tests/test_workflow_architect.py tests/test_workflow_architect_canonical.py tests/test_workflow_architect_eval.py tests/test_workflow_architect_patch.py -q` | **39 passed** (123.82 s) |
| `python scripts/certification/eval_universal_cases.py --help` | CLI válida con nuevos flags |
| `ruff check` de los archivos P04 | OK |

## 6. Límites

- **No se ejecutó un proveedor LLM real** en P04. Los resultados de calidad
  (≥95% grafos válidos) siguen `NOT_VERIFIED`; los artefactos históricos
  continúan en NO-GO.
- El dataset tiene 100 casos totales, no 100 por dominio. El harness está
  preparado para `--per-domain 100`, pero faltan casos reales por dominio.
- La estimación de tokens usa caracteres/3, no el tokenizer del proveedor;
  se marca como estimación.
- No se pasó `seed` al proveedor (su interfaz no lo expone); el seed se usa
  para el muestreo reproducible y queda en la cabecera del artefacto.
- La caché es de sesión, no distribuida; no persiste entre reintentos.
- La reparación determinista no cubre todos los códigos de contrato; el resto
  sigue siendo una corrección propuesta por el LLM y validada por backend.

## 7. Rollback

1. Revertir `planner_budget.py`, `planner_diagnostics.py` y sus integraciones.
2. Quitar la caché de `PlannerToolContext` y `deterministic_repairs`.
3. Revertir el harness de evaluación y los flags nuevos.
4. No hay migración de datos en P04. Las sesiones existentes siguen siendo
   válidas; no se reescribió ningún plan persistido.

## 8. Dictamen

**GO P04 para staging controlado** en instrumentación, presupuesto, caché,
clarificaciones y diagnóstico. **NO-GO de calidad/GO general:** falta ejecutar
un proveedor real con el dataset ampliado (≥100 por dominio) y demostrar ≥95%
de grafos válidos bajo presupuesto productivo. P05 (PEP/workspace) fue cerrado
en `07-p05-policy-enforcement.md`; la calidad real del planner sigue pendiente.
