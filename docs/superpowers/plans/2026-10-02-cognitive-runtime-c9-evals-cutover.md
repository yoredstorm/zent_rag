# Cognitive Runtime C9 — Evals + Gates + Cutover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cerrar el programa con (a) un harness determinístico de escenarios del brief sobre el runtime, (b) el costeo del deep path en usage, (c) el cutover: retirar `src/rag/query_intelligence/**`, `POST /api/v1/cognitive/runs/{id}/execute` y `knowledge.changed`, y (d) documentar los gates de promoción `shadow → limited → active`.

**Architecture:** Harness en `tests/test_cognitive_eval.py` (fakes existentes, sin DB) con tabla de escenarios y asserts sobre `flow["cognitive"]`/respuesta; costeo: `RAGQueryResult.cognitive_cost_usd` + suma en `_record_usage_event`; cutover: borrado de paquete/route/registro + actualización de tests y docs. Sin migraciones ni dependencias.

**Tech Stack:** Python del repo, pytest, portal vitest (solo verificación), ruff.

**Spec:** `docs/architecture/cognitive-runtime.md` §11 (W6), §15/§16, fase C9.

## Global Constraints

- Sin dependencias ni migraciones. Sin cambios de contrato más allá del retiro explícito de `/execute` (interno; portal/SDK/workflows no lo usan).
- Harness determinístico, sin LLM real ni DB; escenarios fallan con mensaje claro.
- Default `off` intacto; nada del harness cambia comportamiento productivo.
- Código/comentarios español; commit por tarea. Branch `feat/cognitive-runtime-c9` (worktree `.worktrees/cognitive-c8` reutilizado).

---

### Task 1: Harness de escenarios (14)

**Files:**
- Create: `tests/test_cognitive_eval.py`
- Test: el mismo archivo

**Escenarios (ids y asserts):**
1. `simple_factual`: shadow + retrieval con 1 chunk → `flow["cognitive"]["plan"]["needs"]` incluye `semantic_search`; respuesta legacy; 1 llamada LLM.
2. `exact_literal`: "¿Qué significa el Byte 105 de Category 31?" → needs `exact_lookup` + `graph_traversal`; strategy incluye `exact`.
3. `structured_excel`: "¿Cuál es el total de la columna 7?" → needs `structured_query` + `aggregation`.
4. `graph_relationship`: FakeKnowledgeModel con edges + "¿Qué relación tiene Category 31?" → runner `graph` status ok; `evidence.counts.relation >= 1`.
5. `temporal`: assertions con `valid_to` pasado → runner `temporal`; `refs.validity == "historical"`.
6. `conflicting_sources`: dos assertions mismo predicate valores distintos → `evidence.conflicts` con 2 values; units `conflict=True`.
7. `insufficient_evidence`: FakeVectorStore con chunks vacíos → respuesta "No tengo suficiente información"; `verification.action in {"revise","abstain"}` (o sin claims → approve y `evidence.count == 0`; assertar el camino real).
8. `multi_document`: dos chunks de documentos distintos → `evidence.counts.excerpt == 2`.
9. `greeting_no_knowledge`: "Hola, buenos días" → `plan.needs == ["no_retrieval"]`; 1 llamada LLM.
10. `tool_required`: "Envía un correo al proveedor" → needs incluye `external_tool`.
11. `knowledge_and_tool`: "¿Aplica la regla 12? Envía el resultado por correo" → needs incluye `rule_lookup` + `external_tool`.
12. `jev_no_intervention`: preflight off (default) → `"jev_preflight" not in flow` y `flow["cognitive"]["signals"]` presente.
13. `verification_failure`: respuesta legacy sin respaldo ("El sistema usa blockchain cuántico") → `verification.action == "revise"` y `unsupported >= 1`.
14. `deep_l3_active`: active + FakeCognitiveService/Executor + query L3 → `result.method == "cognitive_os"`, `run_id` presente, 0 llamadas al LLM legacy.

**Implementación:** reusar el patrón de fakes de `tests/test_cognitive_runtime_shadow.py` y `tests/test_cognitive_deep_path.py` (duplicar los mínimos: Cache/OrgRepo/LLM/Embed/VectorStore/KnowledgeModel/CognitiveService/CognitiveExecutor). Tabla `SCENARIOS = [(id, query, mode, extra_fakes, asserts_fn)]` + un test parametrizado que corre cada escenario y un assert por escenario (funciones `_assert_*`). Sin DB, sin red.

- [ ] Steps TDD: escribir el harness, correr (rojo donde falte), ajustar asserts a la conducta real (nunca inventar), verde, lint, commit `test(cognitive): harness de escenarios C9`.

---

### Task 2: Costeo del deep path en usage

**Files:**
- Modify: `src/core/domain/entities.py` (`RAGQueryResult.cognitive_cost_usd: float = 0.0`)
- Modify: `src/agents/runtime/orchestrator.py` (`_run_deep_reasoning` setea el costo; `_record_usage_event` lo suma)
- Test: `tests/test_cognitive_deep_path.py` (o `tests/test_usage_engine.py` si aplica)

**Reglas:**
- `_run_deep_reasoning`: al construir la respuesta deep, `result.cognitive_cost_usd` se setea con `metrics.get("cost_usd")` (fail-soft float).
- `_record_usage_event`: `cost = await estimate_cost(...) + float(result.cognitive_cost_usd or 0.0)`; `estimated_cost=actual_cost=cost`; agregar `cost_tags` con `{"cognitive_deep": True}` cuando > 0 (el campo `cost_tags` ya existe).
- Test: deep path → usage event con costo > 0 incluyendo el DAG (fake/monkeypatch del recorder de usage, sin DB); legacy → comportamiento actual.

- [ ] Steps TDD + lint + commit `fix(cognitive): costo del deep path entra al usage (C9)`.

---

### Task 3: Cutover

**Files:**
- Delete: `src/rag/query_intelligence/**`, `tests/test_query_intelligence.py`
- Modify: `src/api/routes/cognitive.py` (quitar `POST /runs/{id}/execute`; quedan GET run/tasks/messages/inspector, POST /runs, /curate, /suggestions, /decide, /shadow)
- Modify: `src/platform/workflows/event_registry.py` (quitar `knowledge.changed`)
- Modify: `tests/test_living_workflows.py` (quitar el assert de `knowledge.changed`; si el catálogo lo sintetiza, ajustar)
- Modify: docs que lo listan como vigente (`README.md:118`, `docs/architecture/cognitive-runtime.md` §12/§15; históricos no se tocan)

**Reglas:**
- Sin callers productivos: `query_intelligence` solo se importa a sí mismo y a su test (verificado); `/execute` no lo usa portal/SDK/workflows/tests; `knowledge.changed` solo registry + un assert de test.
- Retiro limpio: borrar archivos, quitar ruta y registro, actualizar tests/docs; `grep` final sin referencias vivas.
- Los endpoints de inspección y el servicio/executor internos quedan intactos.

- [ ] Steps: borrar + ajustar + `grep` + correr suites afectadas (`tests/test_architecture.py`, `tests/test_cognitive_api.py`, `tests/test_living_workflows.py`, `tests/test_workflow_graph.py`) + lint + commit `refactor(cognitive): cutover C9 — query_intelligence, execute y knowledge.changed`.

---

### Task 4: Gates + docs + verificación final

**Files:**
- Modify: `docs/architecture/cognitive-runtime.md` (§15 fila C9 `**shipped**` + link del plan; §11 gates con criterios explícitos; §12 retiros hechos; nota: promoción `active` sujeta a evals verdes)

**Gates (texto):**
- `off → shadow`: harness verde (14 escenarios) + `ruff` + sin regresión (`test_cognitive_runtime_shadow.py`, `test_jev_preflight_flow.py`).
- `shadow → limited`: harness verde + portal typecheck/vitest verdes + grounding no peor que baseline (comparación shadow existente `compare_shadow`).
- `limited → active L0–L2`: harness verde + evals de `src/rag/evaluation/**` sobre golden set sin regresión.
- `active L3+`: escenarios deep verdes (Task 1) + costo dentro de `CognitiveBudget` (el executor ya enforce) + costo del DAG visible en usage (Task 2).
- Promoción siempre manual (admin), nunca automática.

- [ ] Steps: docs + verificación final:

```bash
pytest tests/test_cognitive_eval.py tests/test_cognitive_runtime_shadow.py tests/test_cognitive_deep_path.py tests/test_cognitive_api.py tests/test_living_workflows.py tests/test_workflow_graph.py tests/test_architecture.py tests/test_answer_verification.py tests/test_knowledge_events.py tests/test_workflow_knowledge_modes.py -q
ruff check src tests
cd portal; npm run typecheck; npx vitest run
grep -rn "query_intelligence" src tests; grep -rn "runs/{run_id}/execute\|/execute" src/api/routes/cognitive.py; grep -rn "knowledge.changed" src tests
```

Expected: suites verdes; ruff limpio; portal verde; greps sin referencias vivas.

- [ ] Commit `docs(cognitive): C9 evals, gates y cutover shipped`.

---

## Criterios de salida C9 (programa completo)

- [ ] Harness de 14 escenarios verde y en CI (pytest tests/).
- [ ] Costo del deep path visible en usage (`cognitive_cost_usd`).
- [ ] `query_intelligence`, `POST /execute` y `knowledge.changed` retirados; sin referencias vivas.
- [ ] Gates de promoción documentados y manuales.
- [ ] `ruff check src tests` limpio; portal typecheck/vitest verdes.
