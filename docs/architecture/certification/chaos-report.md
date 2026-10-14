# Chaos (Parte F)

Evidencia: `artifacts/certification/edeeb61a9e37fff1e39f1a751f5e97470f9ce3d8/battery/chaos.json`
(+ `chaos.md`, `junit-chaos.xml`, `pytest-chaos.log`).

| Dato | Valor |
|---|---|
| SHA | `edeeb61` |
| Fecha | 2026-10-14 |
| Entorno | hermético (dobles de dependencia) + ensayos reales acotados marcados aparte |
| Comando | `python -m src.scripts.certification_battery --suite chaos` |
| Resultado | **17/17 escenarios PASS · 115 tests · 0 fail** (293,0 s) |

## 1. Matriz escenario → política observada

| # | Fallo inyectado | Política esperada y observada | Tests |
|---|---|---|---|
| F01 | LLM primario falla duro | el run cierra `error` honesto; sin línea `llm` facturada | 3 |
| F02 | LLM primario 429 | 1 llamada (el router reintenta/fallback, el runtime no multiplica) | 2 |
| F03 | LLM timeout | failover antes del primer token | 2 |
| F04 | fallback también falla | propaga el error sin loop infinito | 1 |
| F05 | embeddings no disponibles | retry acotado + fallback de embeddings | 16 |
| F06 | reranker caído | orden crudo, sin excepción | 1 |
| F07 | engine JEV roto | el run sigue con reglas | 1 |
| F08 | Redis caído | caché fail-soft (`get`→None), `incr` fail-closed | 1 |
| F09 | retrieval no disponible | `RETRIEVAL_UNAVAILABLE` ≠ "no hay información" | 4 |
| F10 | Postgres desconexión transitoria | write de usage fail-silent; el run responde | 2 |
| F11 | tool timeout | observación `timed out`, sin retry ciego | 1 |
| F12 | tool fallo permanente | guard de tool fallida: no se reintenta la misma pregunta | 1 |
| F13 | salida de tool malformada/gigante | dato marcado, nunca autoridad | 1 |
| F14 | circuit breaker abierto | `PROVIDER_FAILURE` como stop reason; fallback sirve | 1 |
| F15 | stream cortado tras emitir | no cambia de modelo a mitad de respuesta | 1 |
| F16 | recuperación de dependencia | el circuito se cierra (`reset_circuit`) y el modelo vuelve a usarse | 2 |
| F17 | amplificación de retry | factor documentado: ≤4 intentos con 2 candidatos | 2 |

## 2. Ensayos reales (no herméticos) acotados

| Ensayo | Cómo | Resultado |
|---|---|---|
| Provider primario caído → fallback real | `perf_traffic` con `RAG_LITELLM_API_BASE=http://127.0.0.1:9/v1` | ver `perf-baseline.md` (§rutas degradadas) |
| Qdrant caído → retrieval unavailable real | `perf_traffic` con `RAG_QDRANT_PORT=6399` | ver `perf-baseline.md` |
| Bad release → rollback | contenedor con Qdrant roto + rollback al bueno | `rollback/rehearsal.json`: `/health` `degraded` detectado y rollback sano en **16,9 s** |
| Postgres transitorio | monkeypatch de la sesión de `usage_engine` (fail-silent) | incluido en la batería (F10) |

## 3. Hallazgo de esta fase

En el pase hermético previo (F11 del programa de hardening) se había corregido
la caché Redis fail-soft. En esta fase el ensayo **real** de provider caído
mostró que el fallback funciona end-to-end con los providers configurados
(evidencia en `perf-baseline.md`), y el ensayo de rollback validó que `/health`
detecta la dependencia rota (`qdrant: error` → `status: degraded`).

## 4. Límites

- El chaos de infraestructura "matar el contenedor de Redis/Qdrant en staging y
  medir reconexión" sigue pendiente como parte del gate de staging (P2-2): el
  hermético cubre la política, no los timeouts de reconexión reales.
- La latencia de red inyectada (tc/netem) no se probó; el timeout de provider y
  tool cubre el comportamiento de la política.
