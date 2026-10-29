# P18.3-02 — Harness de evaluación RAG

Estado: **implementado y probado; corrida de 40 casos: NOT_RUN**.

## Entregable

`src/scripts/evaluate_knowledge_goldset.py` ejecuta el gold set contra el
endpoint real:

```text
POST /api/v1/knowledge/workspaces/{corpus_id}/chat
```

con `Authorization`, `X-Organization-Id`, `X-Workspace-Id`, corpus y fuentes
explícitos. No crea un segundo pipeline de respuesta.

## Datos capturados por caso

- respuesta final y abstención observada;
- claims y su estado;
- citas con documento, página, sección, localizador y extracto;
- `evidence_ids` del ledger;
- candidatos de retrieval cuando el endpoint entrega
  `retrieval_debug` a un administrador;
- `prompt_version`, modelo, tokens, latencia y coste;
- scope del corpus y fuente.

## Métricas

- `answer_accuracy` y `behavior_accuracy`;
- `citation_precision` (heurística página/extracto);
- `grounded_claim_precision`;
- `retrieval_recall_at_k` solo si hay candidatos de retrieval;
- `abstention_correctness` por familia;
- invariantes de scope, citas sin localizador y respuestas sin cita.

Salidas: `per_case.jsonl`, `metrics.json`, `failure_catalog.md`,
`run_manifest.json` y comparación baseline/candidate con regresión de más de
2 puntos porcentuales.

## Pruebas

`tests/test_p18_3_eval_harness.py`: 6 pruebas.

- normalización y número exacto;
- abstención;
- página/extracto de cita;
- HTTP 503 se clasifica `BLOCKED_PROVIDER`, nunca PASS;
- respuesta exitosa conserva citas y candidatos;
- comparador detecta regresión.

## Por qué no se ejecutó la corrida de 40

El gold set está en `draft_not_approved` y no existe un corpus de staging con
las cuatro familias y sus fuentes mapeadas a `source_ref`. Ejecutar ahora
produciría números sin verdad de referencia humana. Se declara `NOT_RUN`, no
PASS. El desbloqueo es P18.3-01 (revisión humana) más un corpus de staging con
`--source-map`.
