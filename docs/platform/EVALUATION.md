# Evaluación RAG (Customer Portal)

UI sobre el eval engine existente. No hay motor nuevo ni métricas inventadas.

## Rutas

- `/evaluation/datasets` — importar golden set (JSON schema v2)
- `/evaluation/runs` — listar y lanzar runs
- `/evaluation/runs/:id` — tabla Pregunta / Esperado / Retrieved / Actual / Score / Latencia / Coste
- `/evaluation/compare` (alias `/evaluation/playground-compare`) — `POST /eval/runs/{id}/compare`

Nav **Evaluación** solo si el entitlement `eval_ui` es true (Pro/Enterprise por defecto).

## API

Contrato existente: feedback, stats, datasets, runs, compare. `GET /eval/runs/{id}` es additive: cada caso incluye `expected_sources`, `expected_answer`, `retrieved`, `actual`, `latency_ms`, `cost`.

Thumbs del chat (`POST /eval/feedback`) no cambian.

## Control Center

`GET /api/v1/platform/eval/summary` — `run_count` y conteos por org. **Sin** preguntas, respuestas ni chunks.

## Costes

El juez LLM (si está activo) genera `usage_events`. Aparecen en FinOps como coste estimado interno.

## Schema v2 (import)

```json
[
  {
    "id": "caso-001",
    "question": "pregunta",
    "expected_answer": "opcional",
    "expected_sources": ["etiqueta o fragmento"],
    "metadata": { "role": "admin", "top_k": 20 }
  }
]
```

También se acepta `{ "cases": [ ... ] }`.
