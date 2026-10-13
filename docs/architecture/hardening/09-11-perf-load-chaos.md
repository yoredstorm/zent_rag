# F9–F11 — Performance, load y chaos

Estado: **F11 implementado (chaos hermético); F9/F10 con harness + corridas
locales acotadas; la corrida completa (30 iteraciones, concurrencia 25/50)
requiere staging** (ver `perf-baseline.md` §Cómo medir producción).

---

## F9 — Corpus y baseline de performance

Tres corpus versionados (`tests/golden/`), formato compatible con
`perf_traffic`/`finalization_audit`/`load_test`:

| Corpus | Archivo | Preguntas | Clases |
|---|---|---:|---|
| A simple | `corpus_simple.json` | 30 | definición, catálogo, conversacional, capacidad, factual |
| B RAG | `corpus_rag.json` | 50 | comparación, multi-doc, procedimiento, conflicto, temporal, escenario, grounding, seguridad, malicioso, ambiguo |
| C agentic | `corpus_agentic.json` | 30 | análisis, agregación, planificación, tool SQL, razonamiento, tutorial, ejecutable, meta, follow-up |

Comandos (mismo entorno, corpus congelado, `use_cache=False`):

```bash
python -m src.scripts.perf_traffic --label after --queries tests/golden/corpus_simple.json --iterations 30 --limit 30
python -m src.scripts.perf_traffic --label after-rag --queries tests/golden/corpus_rag.json --iterations 30 --limit 50
python -m src.scripts.perf_traffic --label after-agentic --queries tests/golden/corpus_agentic.json --iterations 30 --limit 30
python -m src.scripts.perf_traffic --label after-cache --queries tests/golden/corpus_simple.json --limit 10   # cache ON (use_cache=True en el harness de la app)
```

Cold vs warm: la primera pasada de cada corpus es `cold` (carga de reranker,
embeddings y lazy init); las siguientes son `warm`. Comparar solo cold vs cold y
warm vs warm.

**Corrida local acotada (F9, `artifacts/perf/f9-local-simple.json`)**: 3 queries
del corpus A, 0 errores, p50 31,8 s, p95 100,2 s (cold de reranker: 74,5 s en un
caso), media 52,3 s, 1 llamada LLM/run. El audit de cierre
(`artifacts/finalization-audit/f9-local-simple.json`) dio 3/3 `FINALIZED`
`FINALIZE`, **0 divergencias**. Sin valor estadístico: proveedor LLM local y
lazy ingestion; el baseline de decisión es staging.

## F10 — Load test

`src/scripts/load_test.py`:

```bash
python -m src.scripts.load_test --label local --concurrency 1,2 --requests 2
python -m src.scripts.load_test --label staging --concurrency 1,5,10,25,50 --requests 50
```

Mide por nivel: throughput (rps), p50/p95/p99, error rate, intentos de provider
y `rate_limited`, amplificación de retry, y latencia de Postgres/Redis antes y
después de la carga (`infra_before`/`infra_after`).

**Backpressure (política)**: ante saturación del proveedor, la respuesta
esperada es cola/rate-limit/degradación (el router reintenta una vez y pasa al
fallback; el run degrada con lo que tiene), nunca colapso. Señales a vigilar en
el JSON: `provider_rate_limited`, `retry_amplification`, `error_rate` y
`infra_after.*_ms`.

**Corrida local acotada (F10, `artifacts/load/f10-local.json`)**, corpus A:

| Nivel | Requests | Errores | p50 | p95 | p99 | rps | Postgres | Redis |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 2 | 0 | 23,5 s | 40,4 s | 40,4 s | 0,05 | 15,6–20,8 ms | 1,6–19,4 ms |
| 2 | 2 | 0 | 27,7 s | 39,7 s | 39,7 s | 0,05 | 13,8–25,4 ms | 2,8–3,8 ms |

Lectura: el cuello de botella local es el LLM de proveedor (2 llamadas/query +
rerank de cold start), no las dependencias. Sin `rate_limited` ni amplificación
de retry. La corrida de decisión (25/50 concurrentes) requiere staging.

## F11 — Chaos

Matriz componente × fallo × política y su test:

| Componente | Fallo inyectado | Política | Test |
|---|---|---|---|
| LLM provider | siempre revienta | run cierra `error` con historial; sin línea `llm` ni tokens | `test_provider_down_no_propaga_y_cierra_honesto` |
| LLM provider | 429 en todos los intentos | el runtime no reintenta (el router lo hace); 1 llamada | `test_429_no_multiplica_llamadas` |
| Router de gateway | error transitorio en 2 candidatos | 1 reintento por candidato (≤4 intentos) | `test_retry_acotado_por_candidato` |
| Tool | timeout | observación `timed out`, sin retry ciego, el run responde | `test_timeout_no_se_reintenta_y_el_run_define` |
| Tool | fallo permanente | no se reintenta para la pregunta (guard de tools fallidas) | `test_fallo_permanente_no_se_reintenta` |
| Engine JEV | revienta | el run sigue con reglas | `test_engine_jev_roto_el_run_sigue_con_reglas` |
| Redis | inaccesible | caché fail-SOFT (get None, listas [], escrituras no-op) y `incr` fail-CLOSED | `test_redis_caido_la_cache_es_fail_soft` |
| Reranker | proveedor caído | orden crudo (sin excepción) | `test_reranker_caido_devuelve_orden_crudo` |
| Circuit breaker | abierto al arrancar | `PROVIDER_FAILURE` (stop reason) | `test_budget_stop_reasons` / `test_agent_budget_closure` |
| Qdrant | inaccesible | `RETRIEVAL_UNAVAILABLE` (jamás «no hay información») | `test_evidence_first_gate` (caso D) + taxonomía |

**Hallazgo real del pase**: `RedisCache.get/set/delete/exists/get_list/append_to_list/
trim_list` llamaban a `_get_redis()` FUERA del `try`: con Redis inaccesible la
excepción de conexión propagaba (el run podía fallar por la caché). Se movió la
conexión dentro del manejo fail-soft; `incr` (rate limit) sigue fail-closed.

### Amplificación de retry

```
intentos_externos = candidatos × (1 + reintento_transitorio)
máximo con 2 candidatos = 4
```

`load_test` reporta `retry_amplification = intentos / requests`; la alerta de
retry storm se define sobre ese factor (ver `13-slo-alerts.md`).

## Deuda

- Corrida completa de F9/F10 en staging (30 iteraciones y concurrencia 25/50).
- Chaos de infraestructura real (matar Redis/Qdrant en staging) — la matriz
  hermética cubre la política; el ensayo real valida timeouts y reconexión.
- Ratchet de `except Exception` en CI (`tests/test_exception_certification.py`):
  los 20 sin comentario que quedan en `agent_runtime`/`orchestrator`/`llm`
  (4 + 11 + 5) se certifican a medida que se tocan esos bloques; el número no
  puede crecer.
