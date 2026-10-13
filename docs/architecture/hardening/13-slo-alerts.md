# SLOs, alertas y runbooks — propuesta operativa (F13)

Estado: **propuesta con umbrales provisionales**. Los targets de latencia se
fijan con el baseline de producción (F9); acá quedan el método, las invariantes
duras y la matriz de alertas con su runbook.

---

## 1. SLOs

| SLO | Target | Fuente | Estado |
|---|---|---|---|
| Disponibilidad (API RAG/agent) | ≥ 99.9% mensual | `rag_queries_total` vs `rag_errors_total` + `/health` | target final |
| Cross-tenant leakage | **0** | tests de aislamiento + `zent_run_state_violations_total{kind}` | invariante dura |
| Cross-conversation leakage | **0** | `test_conversation_isolation` (×100) + `zent_cache_bypass_total` | invariante dura |
| Inversión de autoridad determinista | **0** | `zent_finalization_divergence_total`, `test_finalization_golden` | invariante dura |
| Tool ejecutada sin autorización | **0** | `test_run_guards_shadow`, `test_agent_security` | invariante dura |
| Fallo inducido por provider | < 1% de runs | `zent_provider_attempts_total` + runs fallidos | provisional |
| Costo desconocido | < 5% de runs | `zent_run_cost_unknown_total` / `zent_runs_total` | provisional |
| p95 simple/narrative | fijar en F9 | `zent_run_latency_seconds{path}` + harness | pendiente baseline |
| p95 RAG | fijar en F9 | idem | pendiente baseline |
| p95 agentic (tools+reasoning) | fijar en F9 | idem | pendiente baseline |
| Evidence coverage (RAG) | fijar en F9 | recall@k/MRR del harness | pendiente baseline |

**Error budget**: 0.1% de disponibilidad mensual; el presupuesto de latencia se
define junto con los p95 de F9 (burn-rate: 2% en 1 h → alerta).

## 2. Alertas (matriz con runbook y owner)

| Alerta | Severidad | Métrica | Umbral / ventana | Runbook | Owner |
|---|---|---|---|---|---|
| Provider 429 | high | `zent_provider_attempts_total{status="rate_limited"}` | > 20 en 5 min | provider-429 | Platform |
| Circuit breaker abierto | critical | `zent_model_circuit_openings_total` | > 0 con scope global, o ≥ 2 tenants distintos en 10 min | circuit-open | Platform |
| p95 de run | high | `zent_run_latency_seconds` | p95 > 2× baseline, 15 min | latency-spike | Platform |
| Retrieval failure | high | `zent_run_evidence_total{status="failed"}` / `rag_agent_retrieval_unavailable_total` | > 5% de runs, 15 min | retrieval-outage | Knowledge |
| Divergencia de autoridad | critical | `zent_finalization_divergence_total` | > 0 con etapa armada, 1 h | authority-divergence | AI Runtime |
| Invariante cross-tenant | critical | `zent_run_state_violations_total{kind=~"authoritative.*"}` | > 0 | tenant-isolation | Security |
| Costo desconocido | medium | `zent_run_cost_unknown_total` | > 10% de runs, 1 h | cost-unknown | FinOps |
| Abstenciones | medium | `zent_runs_total{phase="ABSTAINED"}` | > 30% de runs, 1 h | abstention-spike | Knowledge |
| Undetermined | medium | `zent_runs_total{phase="UNDETERMINED"}` | > 10% de runs, 1 h | undetermined-spike | AI Runtime |
| DB saturada | high | pool activo/espera (F7) | wait > 0 sostenido, 5 min | db-saturation | Platform |

Reglas de higiene: toda alerta declara severidad, umbral, ventana, runbook y
owner; sin runbook no se despliega. Sin `run_id`/`user_id`/`conversation_id` en
labels.

## 3. Runbooks

Ver `docs/architecture/runbooks/README.md` (índice + 9 incidentes).

## 4. Dashboards (F13, propuesta)

- **Platform**: runs por fase, p50/p95/p99, errores, costo (known/unknown),
  intentos de provider, circuitos.
- **AI quality**: evidencia (status), abstenciones/undetermined, JEV
  (calls/skip/shadow), divergencia de autoridad, autoridad faltante.
- **Infra**: Postgres (pool, queries lentas), Redis (latencia/errores), Qdrant
  (latencia, vacíos), workers.

Los dashboards se versionan como JSON cuando el stack Prometheus/Grafana exista
(hoy no está en `deploy/`); mientras tanto las métricas se exponen en
`/metrics` y las alertas de incidentes viven en `src/platform/observability`.
