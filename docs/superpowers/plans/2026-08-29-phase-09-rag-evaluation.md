# Fase 09 — RAG Evaluation UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> Índice: [`docs/platform/ZENT_PLATFORM_ROADMAP.md`](../../platform/ZENT_PLATFORM_ROADMAP.md)

**Goal:** Productizar el eval engine que ya existe: “Zent doesn’t only generate answers. Zent measures whether those answers are actually good.” UI en Customer Portal (org) y opcionalmente vista en Control Center (agregado, sin filtrar respuestas de otro tenant en claro si es PII).

**Architecture:** Cero motor nuevo. Pantallas sobre [`src/api/routes/evaluation.py`](../../../src/api/routes/evaluation.py): feedback, stats, datasets, runs, compare. Entitlement `eval_ui` (Fase 03) puede ocultar nav.

**Tech Stack:** React, APIs eval existentes, pytest (regresión de API).

## Global Constraints

- No reescribir `src/rag/evaluation/` ni golden-set runner.
- Identidad de tenant solo del Bearer; datasets y runs **siempre** org-scoped (verificar).
- API `1.0.0` additive only (UI-only preferible).
- Copy del portal en español.
- Tests: `pytest tests/test_evaluation.py tests/test_eval_engine.py`. Lint: ruff.
- No gateway, no K8s.

## Protocolo del agente (obligatorio)

1. Inspect existing architecture
2. Do not rewrite working functionality
3. Identify existing components
4. Design changes
5. Implement
6. Add migrations — solo si falta un campo de UI
7. Add tests
8. Update API (si un listado no expone retrieved docs)
9. Update frontend
10. Update documentation
11. Run tests
12. Run lint
13. Check backwards compatibility
14. Report files changed
15. Report remaining risks

---

## Exists / Reuse

```
POST /api/v1/eval/feedback
GET  /api/v1/eval/stats
GET  /api/v1/eval/recent
POST /api/v1/eval/run
POST /api/v1/eval/datasets/import
GET  /api/v1/eval/datasets
POST /api/v1/eval/runs
GET  /api/v1/eval/runs
GET  /api/v1/eval/runs/{run_id}
POST /api/v1/eval/runs/{run_id}/compare
```

Chat ya envía thumbs (`eval/feedback`). Scripts: `src/scripts/eval_rag.py`, `eval_engine.py`.

## Gaps

- Cero páginas portal para datasets/runs/metrics (faithfulness, hallucination_rate, latency, cost).
- La presentación no se puede demo sin UI.

---

### Task 1: Inspeccionar payloads reales

- [ ] **Step 1: Leer** `evaluation.py` + `tests/test_evaluation.py` y anotar JSON de `runs/{id}` (question, expected, retrieved, actual, scores).
- [ ] **Step 2: Si falta un campo** para la tabla de la visión (Question, Expected, Retrieved, Actual, Score, Latency, Cost), **extender GET run** additive + test.

---

### Task 2: Customer UI

Rutas (IA):

```
/evaluation
  /datasets
  /runs
  /runs/:id
  /playground-compare
```

- [ ] **Step 1:** Tabla de casos del run (columnas de la visión).
- [ ] **Step 2:** Cards de métricas: Retrieval Precision/Recall si el engine las tiene; si no, mostrar solo las que existan (faithfulness, hallucination_rate, latency, cost) — **no fake precision**.
- [ ] **Step 3:** Import dataset (archivo JSON según schema v2 ya documentado).
- [ ] **Step 4:** Compare contra baseline (usar `compare` existente).
- [ ] **Step 5:** Nav + entitlement hide.

---

### Task 3: Control Center (opcional ligero)

- [ ] **Step 1:** `GET /api/v1/platform/eval/summary` — counts de runs/org, **sin** texto de preguntas de clientes. Si no se puede agregar sin leak, **omitir** esta task y documentarlo.

```bash
ruff check src/ tests/ sdk/python
pytest tests/test_evaluation.py tests/test_eval_engine.py tests/test_tenant_isolation.py -q
```

Expected: PASS

## Criterios de aceptación

- Un org admin importa un golden set, lanza un run, ve scores y un compare.
- Thumbs del chat siguen funcionando.
- No hay métricas inventadas.

## Riesgos residuales

- LLM-judge es no determinista: tests de UI no afirman scores exactos.
- Costos del judge aparecen en usage: documentar.
