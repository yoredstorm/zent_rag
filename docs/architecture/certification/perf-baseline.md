# Baseline de performance (Parte C)

Evidencia: `artifacts/certification/edeeb61a9e37fff1e39f1a751f5e97470f9ce3d8/perf/`
(`cert-*.json` por workload, `http-probe.json`, `matrix.json`, logs por corrida).

| Dato | Valor |
|---|---|
| SHA | `edeeb61` (sobre `17acf3d`) |
| Fecha | 2026-10-14 (UTC 20:30–20:45) |
| Host | workstation local (Windows 11, Docker Desktop 29.7.2) |
| Dependencias | Postgres 16 + pgvector local, Redis 7, Qdrant v1.13.4, providers reales (Novita primario / DeepInfra fallback) |
| Corpus | `tests/golden/corpus_simple.json`, `corpus_rag.json`, `corpus_agentic.json` (los mismos del programa F9) + corpus de no-evidencia |
| Harness | `src/scripts/perf_traffic.py` (in-process, `use_cache=False`) y `scripts/cert/http_probe.py` (HTTP real) |

## 1. Perfil de configuración `ci-parity`

Valores default de `config.py` (los que usa CI): `ADAPTIVE_RAG_MODE=off`,
`DECISION_ROUTING_MODE=legacy`, `COGNITIVE_OS_ENABLED=off`,
`LAZY_INGESTION_ENABLED=false`, `LONG_CONTEXT_MODE=off`,
`EVIDENCE_REASONING_MODE=off`. Organización: la de demo
(`00000000-…-0001`), que **no tiene documentos en la base vectorial**: los runs
ejercitan retrieval + política + abstención determinista (sin generación LLM).

| Workload | Runs | Errores | p50 (s) | p95 (s) | p99 (s) | tokens/run | LLM/run | Fases | Answer states |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| simple (cold) | 3 | 0 | 3,13 | 6,05 | 6,05 | 0 | 1 | FINALIZED ×3 | INSUFFICIENT_EVIDENCE ×3 |
| simple (warm) | 3 | 0 | 2,44 | 7,60 | 7,60 | 0 | 1 | FINALIZED ×3 | INSUFFICIENT_EVIDENCE ×3 |
| rag multi-doc | 3 | 0 | 2,21 | 6,26 | 6,26 | 0 | 1 | FINALIZED ×3 | UNDETERMINED_RULE ×3 |
| agentic (tools) | 3 | 0 | 17,85 | 55,36 | 55,36 | 0 | 1 | FINALIZED ×3 | UNDETERMINED_RULE ×2, INSUFFICIENT_EVIDENCE ×1 |
| no-evidence | 3 | 0 | 7,42 | 8,06 | 8,06 | 0 | 1 | FINALIZED ×3 | INSUFFICIENT_EVIDENCE ×2, EXECUTION_FAILED ×1 |
| provider primario roto → fallback real | 3 | 0 | 10,09 | 15,18 | 15,18 | 0 | 1 | FINALIZED ×3 | INSUFFICIENT_EVIDENCE ×3 |

Lectura:
- **0 errores** en todos los workloads; ninguna corrida terminó en `FAILED`.
- El fallback real funciona end-to-end (primario en `127.0.0.1:9`): el run
  completa, con ~2× la latencia del caso sano (el intento fallido se paga).
- La varianza del workload agentic (p50 17,9 s vs p95 55,4 s) es de política
  (rondas de retrieval/undetermined), no de provider.
- **EXECUTION_FAILED** apareció 1 vez en el corpus de no-evidencia: es un estado
  legítimo (no hay ejecución posible) y no un error de infraestructura; queda
  registrado para no confundirlo con un fallo de disponibilidad.

## 2. Cache y TTFT (HTTP real, `http-probe.json`)

Contra el API local (`/api/v1/rag/query` y `/api/v1/rag/query/stream`), org demo:

| Métrica | Valor |
|---|---|
| Primera query (miss) | 7.003 ms |
| Misma query repetida (hit esperado) | 6.373 ms |
| `rag_cache_misses_total` (delta) | **+2** |
| `rag_cache_hits_total` (delta) | **0** (sin muestras) |
| Primer evento SSE | 24 ms |
| **TTFT (primer payload con texto)** | **7.456 ms** |
| Stream completo | 7.458 ms |

Hallazgo: **la caché de respuestas no sirve hits en este deployment**. La
repetición de la misma query vuelve a computar (2 misses, 0 hits). Es
consistente con la política fail-closed (sin fingerprint de conocimiento el
caller no debe cachear), pero la señal es pobre: el counter de bypass
(`zent_cache_bypass_total`) **no se incrementa** en ese camino, así que no hay
métrica accionable que distinga "caché deshabilitada por política" de "caché
rota". Se registra como riesgo P2 (ver `remaining-risks.md`) con la alerta
`ZENTCacheBypassIsolationGuard` ya existente para el caso que sí emite métrica.

## 3. Perfil `dev` (configuración local completa)

Con el `.env` local (adaptive `active`, lazy ingestion `on`, long-context on),
el mismo corpus mostró una varianza enorme: una corrida de 5 queries dio
latencias de **50,2 s / 211,3 s / 433,2 s / 173,0 s / 24,8 s** (p50 ≈ 50 s,
p95 ≈ 433 s) y una de ellas consumió **33.537 tokens** de contexto, mientras el
log del provider reporta `llm_latency_ms=941` — es decir, **la latencia está
dominada por ingesta perezosa y ensamblado de contexto, no por el LLM**.

Consecuencia: los números del perfil `dev` **no sirven como SLO** (dependen del
estado de ingesta de la org). Los del perfil `ci-parity` sí son reproducibles,
pero miden el camino determinista. El baseline de generación con corpus cargado
es una **condición de staging** (P2-1/P2-2).

## 4. Targets derivados (provisionales, a re-fijar en staging)

| SLI | Medido (local, ci-parity) | Target provisional | Techo de producto |
|---|---|---|---|
| p95 simple/RAG (determinista) | 6,1–7,6 s | **≤ 20 s** | 60 s |
| p95 agentic | 55,4 s (n=3, outlier) | **≤ 120 s** | 180 s |
| p95 con fallback de provider | 15,2 s | **≤ 30 s** | 90 s |
| TTFT (stream) | 7,5 s | **≤ 15 s** | 30 s |
| error rate | 0/18 runs | **< 1%** | 1% |
| costo/run (generación) | no medido en ci-parity | fijar con staging | — |

## 5. Límites de esta evidencia (explícitos)

1. Workstation compartida con la batería de tests: los valores absolutos son
   cotas superiores locales.
2. `n=3` por workload: sin valor estadístico para p99; el baseline de decisión
   (30 iteraciones) es staging.
3. No hay corpus de documentos cargado en la org de demo: el camino de
   generación con evidencia real no está medido acá.
4. El escenario "retrieval no disponible" **no se inyectó de verdad**: la org sin
   documentos corta antes de tocar Qdrant y abstiene correctamente
   (`INSUFFICIENT_EVIDENCE`, no un falso "no hay datos"). La distinción
   `RETRIEVAL_UNAVAILABLE` ≠ "no hay información" está probada en la batería
   hermética (chaos F09, 4 tests) y requiere corpus cargado para su ensayo real.
5. `use_cache=False` en los harness in-process (por diseño); la evidencia de
   caché es la del probe HTTP.
