# Perf Baseline — tráfico real (V2 F1)

Estado: **harness creado y corrida local ejecutada (2026-10-12)**. La medición
de producción queda pendiente de un entorno con tráfico real; el método y los
números locales quedan registrados acá.

## Harness

`src/scripts/perf_traffic.py` corre un corpus contra el pipeline REAL
(Postgres/Redis/Qdrant/LLM del `.env`) y emite JSON comparable:

```bash
python -m src.scripts.perf_traffic --label after --limit 5
python -m src.scripts.perf_traffic --label before --queries tests/golden/rag_retail.json
```

- Sin `--org-id` toma la primera organización de la DB; sin `--user-id`, el
  primer usuario de esa organización.
- Salida: `artifacts/perf/<label>.json` con casos y summary
  (p50/p95, tokens/run, costo/run, llamadas LLM/run, tools/run, rondas de
  retrieval/run, errores).
- `use_cache=False` para medir el pipeline, no la caché.

## Corrida local (mismo entorno, mismo corpus, 3 queries, top_k 20)

| Métrica | before (`856392d`) | after (HEAD) |
|---|---|---|
| runs / errores | 3 / 0 | 3 / 0 |
| latencia p50 | 282.3 s | 154.0 s |
| latencia p95 | 293.6 s | 431.9 s |
| latencia media | 206.8 s | 211.5 s |
| llamadas LLM/run | 1.0 | 1.0 |
| tools/run | 0.0 | 0.0 |
| tokens/run | 0.0* | 0.0* |

\* Los tres casos abstuvieron con respuesta de 0 tokens; los logs muestran
generaciones reales del proveedor. `llm_calls` en el camino RAG pasó a contar
desde el ledger (after); con resultados abstinentes el valor es 1 en ambos.

Caveats de la corrida local (ruido, no regresión):

- Rerank local con arranque en frío: 140 s en un caso (domina p95).
- Lazy ingestion con timeout de 4 s en el corpus retail (KB local distinta).
- Varianza del proveedor LLM local.

## Cómo medir producción

1. Elegir una org con KB activa y tráfico representativo.
2. `--iterations N` (≥ 30) con el corpus de preguntas reales (exportar de
   analytics) y `--out-dir` a un volumen persistente.
3. Congelar el JSON de "before" antes del deploy y repetir "after" con el mismo
   corpus/org/iteraciones; comparar los summary.

Criterio de cierre: tabla before/after con el mismo corpus en un entorno con
tráfico; mientras tanto, la corrida local queda como smoke test del harness.
