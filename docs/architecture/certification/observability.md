# Observabilidad, alertas y runbooks (Partes J–L)

Estado: **assets versionados y validados por contrato en CI**. La conexión real
del stack en el entorno de producción es una **condición pendiente** (ver
`final-report.md`): hoy Prometheus/Grafana solo están declarados en
`docker-compose.yml` (dev/demo), no en `docker-compose.prod.yml` ni en k8s.

## 1. Dashboards-as-code

| Asset | Ruta | Generado por |
|---|---|---|
| Dashboard de producción (canary) | `config/grafana/dashboards/zent-production.json` | `python -m src.scripts.observability_assets` |
| Dashboard previo (dev) | `config/grafana/dashboards/rag-observability.json` | manual (histórico) |
| Datasources | `config/grafana/datasources/datasources.yml` | manual |
| Provider de dashboards | `config/grafana/dashboards/dashboard-provider.yml` | manual |

El dashboard de producción tiene 35 paneles agrupados en 7 preguntas
operativas:

1. **¿Está sano ZENT?** — `up{job="rag-api"}`, runs/min, ratio de runs FAILED,
   5xx HTTP, distribución de fases terminales, burn del error budget.
2. **¿Qué dependencia está fallando?** — intentos de provider por status,
   aperturas de circuit breaker, retrieval no disponible, suficiencia de
   evidencia.
3. **¿Está aumentando la latencia?** — p50/p95/p99 del run, vector search p95,
   LLM p95.
4. **¿Hay retry amplification o backpressure?** — intentos/run, 429.
5. **¿Aumentó la abstención? ¿Anomalías de evidencia/autoridad?** — ratio de
   abstained, acciones de finalización, divergencia de autoridad, violaciones de
   aislamiento, cache bypass, tool calls.
6. **¿El costo por run cambió abruptamente?** — USD/run, ratio de costo
   desconocido, tokens/run, llamadas LLM/run.
7. **¿Algún tenant está saturando recursos?** — top-5 tenants por queries
   (`organization_id` es el único label por-tenant, acotado por diseño),
   cache hits.

Reglas de cardinalidad aplicadas (contrato en
`tests/test_observability_assets.py`): ninguna query usa `query`, `user_id`,
`conversation_id`, `run_id`, `trace_id`, `document_id` ni `request_id`. Los
datos por run viven en logs/trazas (`traces`/`trace_spans`, `api_logs.trace_id`).

## 2. Alertas

`config/prometheus/alert-rules.yml` (grupos `zent-availability`,
`zent-latency`, `zent-provider`, `zent-knowledge`, `zent-authority-security`,
`zent-cost`). Cada regla declara `severity`, `owner`, `sli`, `runbook` y
annotations con `summary`, `description`, `diagnosis` (comandos reales) y
`mitigation` (rollback/fallback).

Correcciones aplicadas en esta fase (hallazgos de la auditoría):

| Hallazgo | Antes | Ahora |
|---|---|---|
| `QuotaNearlyExceeded` usaba `rag_active_requests{usage="current"}` | serie inexistente: alerta muerta | eliminada (la cuota se mide en `/billing/usage` y `finops_alerts`) |
| `OllamaDown` usaba `up{job="ollama"}` | no hay job `ollama` en el scrape config | eliminada |
| `ModelCircuitMultiTenantOpen` contaba `zent_model_circuit_openings_total` sin `increase()` | un counter monotónico: la alerta queda encendida para siempre | `count by (model) (increase(...[10m]) > 0) > 1` |
| Faltaban reglas para los SLI duros | — | 15 reglas nuevas (429, amplificación, circuito global, retrieval, evidencia, abstención, undetermined, divergencia de autoridad, aislamiento, unknown cost, costo/run, burn) |

`tests/test_observability_assets.py` verifica en CI que **toda métrica citada
existe en el registry real** (evita el modo de fallo "alerta muerta"), que los
runbooks citados existen y que las reglas no usan labels no acotados.

Gap declarado: no existe todavía una métrica de **divergencia contable**
(ledger vs usage vs billing). Se valida con `src/scripts/billing_reconcile.py`
(job diario) y el test de cadena `tests/test_certification_accounting_chain.py`.
Alerta pendiente de métrica (riesgo P2).

## 3. Runbooks

`docs/architecture/runbooks/README.md` — 18 incidentes con señales, diagnóstico
ejecutable (`psql`, `redis-cli`, `curl`, `kubectl`), acción, rollback y owner:

| # | Incidente | # | Incidente |
|---|---|---|---|
| 1 | LLM outage | 10 | High latency sostenida |
| 2 | Qdrant outage | 11 | Retry amplification |
| 3 | Redis outage | 12 | Bad release |
| 4 | DB saturation | 13 | Tenant isolation incident |
| 5 | Provider 429 | 14 | Cost unknown |
| 6 | Circuit open | 15 | All providers degraded |
| 7 | Cost spike | 16 | Migration problem |
| 8 | High abstention rate | 17 | Tool/API incident |
| 9 | High undetermined rate | 18 | Authority divergence |

`tests/test_observability_assets.py::test_runbooks_cover_required_incidents`
falla si alguno desaparece; `::test_runbooks_have_executable_diagnosis` exige
comandos reales (no solo "investigate logs").

## 4. Health y SLOs de plataforma (código existente)

- `/health` (checks de Postgres/Qdrant/Redis/decision engine) —
  `src/platform/observability/health.py`.
- SLOs de plataforma por deployment (1h/24h/7d) — `src/platform/observability/slos.py`.
- Alertas de incidentes con webhook del tenant — `src/platform/observability/alerts.py`
  (se evalúan por `POST /api/v1/platform/obs/check`; **no hay scheduler**: la
  evaluación periódica es una condición operativa pendiente, riesgo P2).
- FinOps: `finops_alerts` (budget_exceeded, negative_margin, usage_spike,
  provider_spike) y `usage_alerts` (50/80/90/100%).

## 5. Qué falta para producción (explícito)

1. **Desplegar** el stack: `docker compose -f docker-compose.prod.yml --profile observability up -d`
   (Prometheus + Grafana ya están declarados en el compose de producción y
   verificados por `tests/test_observability_assets.py::test_prod_compose_declares_observability_profile`).
   Falta ejecutarlo en el entorno real y confirmar el scrape de `/metrics`.
2. Alertmanager (hoy `targets: []`) o receptor equivalente para las reglas de
   `alert-rules.yml`.
3. Scheduler que dispare `POST /platform/obs/check` (cron/k8s CronJob) si se
   quiere el webhook del tenant sin depender de una llamada manual.
4. Postgres/Redis exporters: los jobs `postgres-exporter`/`redis-exporter` están
   deshabilitados en `prometheus.yml` (no hay servicios detrás, generaban targets
   `down` permanentes). Las reglas de saturación usan métricas de la app; al
   desplegar los exporters, descomentar los jobs.
