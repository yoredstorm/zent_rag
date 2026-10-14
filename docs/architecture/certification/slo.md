# SLI / SLO / error budget (Parte D)

Método: **primero se mide, después se fija**. Los targets de latencia y costo se
derivan del baseline medido (`perf-baseline.md`, misma fase, mismo SHA) y se
re-fijan en staging antes de producción. Los invariantes duros no se negocian.

## 1. Qué cuenta como error y qué no

| Situación | ¿Error de disponibilidad? | Tratamiento |
|---|---|---|
| Run cierra `FAILED` (provider/infra/exception) | **sí** | error budget de disponibilidad |
| Respuesta `ABSTAINED` por evidencia insuficiente | **no** | outcome legítimo; se mide como calidad (abstention rate) |
| `RETRIEVAL_UNAVAILABLE` | **sí** (es fallo de infraestructura) | cuenta como fallo; jamás se reporta como "no hay datos" |
| Provider 429 manejado con fallback y respuesta OK | **no** (pero es evento degradado) | `provider_dependency`: se mide `rate_limited` y amplificación |
| `UNDETERMINED` (fail-closed del runtime) | no es error de infra, **sí señal de calidad** | SLO de calidad separado (≤10% 1h) |
| Timeout de tool con respuesta parcial honesta | no es error de disponibilidad | SLO de tools: ≤1% de runs con tool fallida |

## 2. SLI/SLO

| SLI | Definición (fuente) | SLO | Tipo |
|---|---|---|---|
| availability | `1 - (runs FAILED + errors HTTP 5xx) / total` (`zent_runs_total`, `http_requests_total`) | ≥ 99.9% mensual | objetivo |
| successful_run_completion | runs que cierran FINALIZED/ABSTAINED/BLOCKED legítimos sobre el total | ≥ 99% | objetivo |
| latency (API) | p99 `http_request_duration_seconds` | < 10 s | objetivo |
| latency (run, por workload) | p95 `zent_run_latency_seconds` | ver §3 (derivado del baseline) | objetivo |
| provider_dependency | ratio de intentos fallidos + 429 sobre intentos totales | < 1% de runs afectados; amplificación ≤ 3 intentos/run | objetivo |
| tool_success | runs con tool call fallida / runs con tools | < 1% | objetivo |
| retrieval_availability | runs con retrieval no disponible / runs | < 0.5% | objetivo |
| budget_accounting_integrity | unknown cost ratio; divergencia ledger/usage/billing | unknown < 5%; divergencia = 0 | objetivo + invariante |
| tenant_isolation | `zent_run_state_violations_total` | **0** | **invariante dura** |
| authority_integrity | `zent_finalization_divergence_total` | **0** | **invariante dura** |
| conversation_isolation | hits cruzados en caché | **0** | **invariante dura** |
| security_incidents | violaciones de tool/SQL/scope/SSRF detectadas | **0** | **invariante dura** |

## 3. Error budget

- Presupuesto de disponibilidad: **0.1% mensual** (≈ 43 min/mes).
- Fast burn: > 2% del presupuesto mensual en 1 h ⇒ `ZENTErrorBudgetFastBurn` (page).
- Slow burn: > 0.2% en 6 h sostenido ⇒ `ZENTErrorBudgetSlowBurn` (ticket).
- Presupuesto de latencia: se define con el p95 medido por workload (§4); la
  alerta de regresión usa 2× el baseline (hoy: umbral absoluto PROVISIONAL).
- Presupuesto de costo: `cost/run` por encima del baseline medido ⇒
  `ZENTCostPerRunSpike` (umbral PROVISIONAL hasta staging).
- Los invariantes duros **no tienen presupuesto**: cualquier ocurrencia es
  incidente (0 tolerancia).

## 4. Targets derivados del baseline medido

Los valores concretos y su derivación están en `perf-baseline.md` §4 (tabla
"p95 medido → target"). Regla aplicada: el target de un workload es
`min(2 × p95_medido, techo de producto)` con el techo de producto = 60 s para
simple/RAG y 180 s para agentic/deep, y se re-fija en staging con 30 iteraciones.

## 5. Qué se alerta (vinculado a runbooks)

`config/prometheus/alert-rules.yml` implementa los SLI de esta tabla: burn,
latencia, provider (429/circuito/amplificación), retrieval, evidencia,
abstención/undetermined, autoridad, aislamiento y costo. Cada alerta declara
`owner` y `runbook` (índice en `observability.md`).

## 6. Revisión

Este SLO se revisa cuando: (a) cambia el baseline (nuevo modelo/provider o
workload), (b) el error budget se agota dos meses seguidos, (c) entra una etapa
de canary nueva. Toda revisión queda fechada con el SHA de la evidencia usada.
