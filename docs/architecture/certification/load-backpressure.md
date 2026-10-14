# Carga y backpressure (Parte E)

## 1. Política (qué debe pasar bajo saturación)

El diseño de ZENT ante saturación es **degradación controlada, nunca colapso**:

| Recurso saturado | Respuesta esperada | Señal |
|---|---|---|
| Provider LLM (RPM/TPM) | 1 retry por candidato + fallback; el run degrada con lo que tiene | `zent_provider_attempts_total{status="rate_limited"}`, `PROVIDER_RATE_LIMIT` |
| Circuit breaker | apertura por (modelo, tenant); el fallback sirve | `zent_model_circuit_openings_total` |
| Postgres (pool) | timeouts de sesión, no deadlock del event loop | pool `waiting`, latencia de infra |
| Redis | caché fail-soft (get/set no rompen), `incr` fail-closed (rate limit) | warnings + `rag_cache_*` |
| Qdrant | `RETRIEVAL_UNAVAILABLE` honesto (jamás "no hay datos") | `rag_agent_retrieval_unavailable_total` |
| Tools | timeout duro, guard de tool fallida (no reintenta la misma pregunta) | steps `tool_call.error` |
| Rate limit de tenant | 429 antes de gastar provider | `RAG_RATE_LIMIT_*` |

Retries acotados por diseño: `intentos = candidatos × (1 + retry_transitorio)` y con
2 candidatos el máximo es 4 (documentado y testeado en
`tests/test_chaos_resilience.py::test_factor_de_amplificacion_documentado` y
`::test_retry_acotado_por_candidato`). Los intentos **no** son billable
completion: solo el éxito se factura (`provider_attempt` tiene costo `unknown`,
sin tokens).

## 2. Método

```bash
# Harness real (in-process, use_cache=False), mismo entorno:
python -m src.scripts.load_test --label cert-load \
  --queries tests/golden/corpus_simple.json --concurrency 1,2,4 --requests 3 \
  --out-dir artifacts/certification/<sha>/perf
```

`load_test` mide por nivel: throughput (rps), p50/p95/p99, error rate, intentos
de provider, `rate_limited`, amplificación de retry y latencia de Postgres/Redis
antes y después de la carga (`infra_before`/`infra_after`).

## 3. Resultados (local, `edeeb61`, perfil `ci-parity`)

`artifacts/certification/edeeb61a9e37fff1e39f1a751f5e97470f9ce3d8/perf/cert-load.json`
(org demo, `corpus_simple.json`, 3 requests por nivel):

| Nivel (concurrencia) | Requests | Errores | p50 (ms) | p95 (ms) | p99 (ms) | rps | 429 | Amplificación | Postgres antes/después | Redis antes/después |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| 1 | 3 | 0 | 5.258 | 12.037 | 12.037 | 0,136 | 0 | 0,0 | 356 / 125 ms | 17,0 / 1,2 ms |
| 2 | 3 | 0 | 7.036 | 9.134 | 9.134 | 0,232 | 0 | 0,0 | 116 / 141 ms | 3,5 / 4,8 ms |
| 4 | 3 | 0 | 12.284 | 12.581 | 12.581 | 0,238 | 0 | 0,0 | 143 / 112 ms | 1,5 / 1,3 ms |

Lectura:
- **0 errores y 0 `rate_limited`** en los tres niveles; sin amplificación de
  retry (factor 0: no hubo reintentos porque no hubo fallos de provider).
- La latencia p50 crece con la concurrencia (5,3 s → 12,3 s a 4): es contención
  de embeddings + rondas de retrieval en el mismo proceso, no saturación de
  Postgres/Redis (cuyas latencias se mantienen planas y bajas).
- El throughput está limitado por la latencia del run (no hay paralelismo
  interno de la org), no por las dependencias.

## 4. Límites de esta evidencia

- Workstation compartida con la batería de tests corriendo en paralelo: los
  valores absolutos son **cotas superiores** locales.
- El techo real depende del provider (RPM/TPM del plan) y del pool de DB del
  deployment, no de la app.
- **Niveles cercanos a capacidad (25/50 concurrentes) no medidos**: requieren
  staging con pool dimensionado y provider real (P2-2). El ensayo de
  backpressure real (cola, pool agotado, provider limitando de verdad) es parte
  del gate de staging (`final-report.md` §faltantes).
- La carga se midió con el perfil determinista (abstención): el consumo de
  provider bajo carga con generación real es una condición de staging.
