# Runbooks — operación de ZENT

Índice de incidentes. Cada runbook declara: **señales** (métricas reales),
**diagnóstico** (comandos ejecutables), **acción**, **rollback/fallback** y
**owner**. Las métricas citadas se exponen en `/metrics`
(`Authorization: Bearer $METRICS_TOKEN`); las alertas de plataforma viven en
`config/prometheus/alert-rules.yml` y las de tenant en
`src/platform/observability/alerts.py`.

Convenciones de los comandos:

```bash
API=${API:-http://127.0.0.1:8000}          # endpoint de la API
M=$METRICS_TOKEN                            # token de /metrics
PSQL=${DATABASE_URL:-postgresql://rag_user@127.0.0.1:5432/rag_platform}
REDIS=${REDIS_URL:-redis://127.0.0.1:6379/0}
```

---

## 1. LLM outage (proveedor caído o inaccesible)

- **Señales**: `zent_provider_attempts_total{status=~"provider_error|timeout"}`
  sube; `zent_model_circuit_openings_total` con scope global; errores 5xx del
  gateway; runs con `PROVIDER_FAILURE` como stop reason.
- **Diagnóstico**:
  ```bash
  curl -s $API/health | jq .checks
  curl -s -H "Authorization: Bearer $M" $API/metrics | grep -E 'zent_provider_attempts_total|zent_model_circuit'
  curl -s -o /dev/null -w '%{http_code} %{time_total}\n' -H "Authorization: Bearer $RAG_LITELLM_API_KEY" \
    "$RAG_LITELLM_API_BASE/models"
  ```
- **Acción**: verificar credenciales/base URL; si el primario está caído,
  confirmar que el fallback configurado responde
  (`RAG_GATEWAY_FALLBACK_MODEL`); si no hay fallback sano, degradar a respuesta
  determinista/abstención operativa (nunca «no hay información») y avisar.
- **Rollback**: al recuperar el proveedor, `reset_circuit(model)` (admin) y
  confirmar cierre de circuitos.
- **Owner**: Platform.

## 2. Qdrant outage (retrieval no ejecuta)

- **Señales**: `rag_agent_retrieval_unavailable_total`,
  `zent_run_evidence_total{status="failed"}`, errores de vector search,
  `rag_errors_total` de conexión.
- **Diagnóstico**:
  ```bash
  curl -sf http://qdrant:6333/healthz && curl -sf http://qdrant:6333/collections | jq '.result.collections[].name'
  curl -s -H "Authorization: Bearer $M" $API/metrics | grep -E 'rag_agent_retrieval_unavailable_total|rag_vector_search_latency'
  ```
- **Acción**: el runtime marca `RETRIEVAL_UNAVAILABLE` (jamás «no hay
  evidencia»); revisar el servicio y su volumen; reintentar la ronda si el
  usuario puede.
- **Rollback**: ninguna acción en ZENT; el estado del run ya es honesto.
- **Owner**: Knowledge.

## 3. Redis outage (caché/historial)

- **Señales**: warnings `Redis GET/SET failed`; latencias de conversación.
- **Diagnóstico**:
  ```bash
  redis-cli -u "$REDIS" ping && redis-cli -u "$REDIS" info memory | grep -E 'used_memory_human|evicted_keys'
  curl -s -H "Authorization: Bearer $M" $API/metrics | grep -E 'rag_cache_hits_total|rag_cache_misses_total'
  ```
- **Acción**: la caché es fail-soft (sin Redis el run sigue) y `incr` (rate
  limit) es fail-closed: confirmar que no se sirven respuestas cruzadas y que el
  rate limit no queda desactivado silenciosamente.
- **Rollback**: al volver Redis, las claves se repueblan solas (TTL corto).
- **Owner**: Platform.

## 4. DB saturation (Postgres lento o pool agotado)

- **Señales**: pool con `waiting > 0` sostenido, timeouts de sesión, p95 de
  endpoints de lectura, queries lentas.
- **Diagnóstico**:
  ```bash
  psql "$PSQL" -c "select state, wait_event_type, count(*) from pg_stat_activity where datname=current_database() group by 1,2 order by 3 desc"
  psql "$PSQL" -c "select pid, now()-query_start as age, left(query,120) from pg_stat_activity where state<>'idle' order by age desc limit 10"
  psql "$PSQL" -c "select count(*) from pg_locks where not granted"
  ```
- **Acción**: identificar la query (N+1 conocidos en ingestion), matar
  long-runs de mantenimiento (`select pg_cancel_backend(<pid>)`), subir pool con
  cuidado (max_connections); degradar endpoints de analytics.
- **Rollback**: si coincide con una migration con lock, ver runbook 16.
- **Owner**: Platform.

## 5. Provider 429 (rate limit)

- **Señales**: `zent_provider_attempts_total{status="rate_limited"}`,
  `PROVIDER_RATE_LIMIT` como stop reason.
- **Diagnóstico**:
  ```bash
  curl -s -H "Authorization: Bearer $M" $API/metrics | grep 'zent_provider_attempts_total{status="rate_limited"'
  curl -s -H "Authorization: Bearer $M" $API/metrics | grep -E 'zent_provider_attempts_total|zent_runs_total'   # amplificación
  echo "RPM configurado: $RAG_LITELLM_MAX_RPM"
  ```
- **Acción**: el router reintenta una vez y pasa al fallback; si el 429 es
  cuota, el failover directo es lo esperado. Subir cuota o bajar concurrencia
  (backpressure: cola/limit antes que colapsar).
- **Rollback**: n/a (no hay cambio de configuración).
- **Owner**: Platform.

## 6. Circuit open (modelo marcado como caído)

- **Señales**: `zent_model_circuit_openings_total{scope}`; la alerta
  multi-tenant indica problema de provider, no de un tenant.
- **Diagnóstico**:
  ```bash
  curl -s -H "Authorization: Bearer $M" $API/metrics | grep zent_model_circuit
  psql "$PSQL" -c "select * from model_circuit_state order by updated_at desc limit 20" 2>/dev/null || true
  ```
- **Acción**: si es global, tratar como LLM outage (runbook 1); si es un tenant,
  revisar su clave/cuota (no tocar el circuito global).
- **Rollback**: `reset_circuit(model)` / `reset_circuit(model, scope)`.
- **Owner**: Platform.

## 7. Cost spike (costo por run o costo desconocido)

- **Señales**: `zent_run_cost_usd_total` / runs por encima del baseline;
  `zent_run_cost_unknown_total` si el pricing no está configurado.
- **Diagnóstico**:
  ```bash
  curl -s -H "Authorization: Bearer $M" $API/metrics | grep -E 'zent_run_cost_usd_total|zent_run_cost_unknown_total|zent_llm_tokens_total'
  psql "$PSQL" -c "select model, sum(total_tokens) tok, sum(coalesce(actual_cost, estimated_cost)) usd, count(*) from usage_events where created_at > now() - interval '1 hour' group by 1 order by 3 desc"
  ```
- **Acción**: activar degradación de presupuesto (reranker/top_k/polish), revisar
  `RUNTIME_JEV_SKIP_*`; si el costo es desconocido, cargar tarifas (nunca
  inventar 0).
- **Rollback**: n/a. **Owner**: FinOps.

## 8. High abstention rate

- **Señales**: `zent_runs_total{phase="ABSTAINED"}` alto;
  `zent_run_evidence_total{status="insufficient"}`.
- **Diagnóstico**:
  ```bash
  curl -s -H "Authorization: Bearer $M" $API/metrics | grep -E 'zent_runs_total|zent_run_evidence_total|zent_finalization_actions_total'
  ```
- **Acción**: distinguir `INSUFFICIENT_EVIDENCE` (faltan datos/cobertura) de
  `RETRIEVAL_UNAVAILABLE` (fallo operativo: runbook 2). Revisar cobertura del
  corpus, reglas canónicas, queries ambiguas; **no** bajar el umbral de
  evidencia para «mejorar» el número.
- **Rollback**: n/a. **Owner**: Knowledge.

## 9. High undetermined rate

- **Señales**: `zent_runs_total{phase="UNDETERMINED"}` alto.
- **Diagnóstico**:
  ```bash
  curl -s -H "Authorization: Bearer $M" $API/metrics | grep -E 'zent_runs_total\{phase="UNDETERMINED"|zent_finalization_actions_total'
  ```
- **Acción**: cargar/revisar la regla o política que falta; el estado es
  fail-closed por diseño (no se completa la semántica por defecto).
- **Rollback**: n/a. **Owner**: AI Runtime.

## 10. High latency (latencia alta sostenida)

- **Señales**: `ZENTHighLatencyP99`, `ZENTRunP95Regression`,
  `ZENTRetrievalStageSlow`, `ZENTLlmLatencyHigh`.
- **Diagnóstico**:
  ```bash
  curl -s -H "Authorization: Bearer $M" $API/metrics | grep -E 'zent_run_latency_seconds_bucket|rag_llm_latency_seconds_bucket|rag_vector_search_latency_seconds_bucket|rag_rerank_latency_seconds_bucket'
  # cold start vs sostenido: comparar la primera pasada con el baseline de perf
  python -m src.scripts.load_test --label diag --concurrency 1 --requests 3
  ```
- **Acción**: separar cold start (modelos/reranker la primera vez) de
  degradación sostenida. Si es sostenido: revisar dependencias (runbooks 1/2/4),
  tamaño de contexto, y `RAG_RAG_RERANK_ENABLED`/top_k antes de escalar.
- **Rollback**: si coincide con un deploy, runbook 12. **Owner**: Platform.

## 11. Retry amplification

- **Señales**: `ZENTProviderAttemptAmplification`
  (`intentos/runs > 3`), picos de `zent_provider_attempts_total` sin subida de
  runs.
- **Diagnóstico**:
  ```bash
  curl -s -H "Authorization: Bearer $M" $API/metrics | grep zent_provider_attempts_total
  docker compose -f docker-compose.prod.yml logs --tail=300 api | grep -c provider_attempt
  ```
- **Acción**: el diseño permite ≤4 intentos con 2 candidatos (1 retry por
  candidato + fallback). Si la amplificación supera eso, hay un bucle:
  verificar circuit breaker abierto (runbook 6), timeouts y que el fallback no
  esté en el mismo proveedor caído.
- **Rollback**: reducir concurrencia (`RAG_RATE_LIMIT_*`) mientras se corrige.
  **Owner**: Platform.

## 12. Bad release (release roto)

- **Señales**: `ZENTApiDown`, `ZENTHighErrorRate` o
  `ZENTErrorBudgetFastBurn` inmediatamente después de un deploy; health con
  `checks` en error.
- **Diagnóstico**:
  ```bash
  kubectl -n zent rollout history deploy/zent-api
  kubectl -n zent get pods -l app=zent-api
  curl -s $API/health | jq .
  curl -s -H "Authorization: Bearer $M" $API/metrics | grep -E 'http_requests_total\{status="5'
  ```
- **Acción**: rollback primero, diagnóstico después (preservar el pod fallido:
  `kubectl -n zent logs deploy/zent-api --previous`).
- **Rollback**:
  ```bash
  kubectl -n zent rollout undo deploy/zent-api
  # compose (sin k8s):
  docker compose -f docker-compose.prod.yml up -d --no-deps api   # con el SHA previo en .env
  ```
  Rollback probado: `scripts/cert/rehearse_rollback.ps1` (evidencia en
  `artifacts/certification/<sha>/rollback/`).
- **Owner**: Platform.

## 13. Tenant isolation incident

- **Señales**: `ZENTTenantIsolationViolation`
  (`zent_run_state_violations_total`), `ZENTCacheBypassIsolationGuard`
  inesperado, reporte de un tenant viendo datos de otro.
- **Diagnóstico**:
  ```bash
  curl -s -H "Authorization: Bearer $M" $API/metrics | grep -E 'zent_run_state_violations_total|zent_cache_bypass_total'
  psql "$PSQL" -c "select id, organization_id, created_at from usage_events where request_id='<request>'"
  # traza del run: tabla traces/trace_spans y logs por trace_id
  psql "$PSQL" -c "select trace_id, stage, name, status, duration_ms from trace_spans where trace_id='<trace>' order by started_ms"
  ```
- **Acción**: tratar como incidente de seguridad: **contener** (bloquear la
  org/ruta afectada), **preservar evidencia** (no borrar logs ni filas), y
  **no** parchear en caliente sin test de regresión. Un invariante rojo se
  reproduce con `pytest tests/test_certification_tenant_stress.py -x`.
- **Rollback**: si el origen es un deploy, rollback (runbook 12) y luego
  corregir con test. **Owner**: Security.

## 14. Cost unknown (unknown != 0)

- **Señales**: `ZENTUnknownCostSpike`; runs con `cost_status="unknown"`.
- **Diagnóstico**:
  ```bash
  curl -s -H "Authorization: Bearer $M" $API/metrics | grep zent_run_cost_unknown_total
  psql "$PSQL" -c "select provider, model, cost_kind, updated_at from pricing_models order by updated_at desc limit 20"
  psql "$PSQL" -c "select model, count(*) from usage_events where created_at > now() - interval '1 day' and coalesce(actual_cost, estimated_cost)=0 group by 1 order by 2 desc limit 10"
  ```
- **Acción**: cargar la tarifa del modelo (`PUT /api/v1/billing/pricing`) o
  cambiar a un modelo tarifado. Unknown **nunca** se imputa como 0: la
  facturación queda marcada como incompleta hasta cargar el precio.
- **Rollback**: n/a. **Owner**: FinOps.

## 15. All providers degraded (fallback también falla)

- **Señales**: `zent_model_circuit_openings_total{scope="global"}` para el
  primario **y** errores del fallback
  (`zent_provider_attempts_total{status=~"provider_error|timeout"}` con
  `retry="true"`); runs `PROVIDER_FAILURE`.
- **Diagnóstico**:
  ```bash
  curl -s -H "Authorization: Bearer $M" $API/metrics | grep -E 'zent_provider_attempts_total|zent_model_circuit_openings_total'
  for base in "$RAG_LITELLM_API_BASE" "$RAG_GATEWAY_FALLBACK_API_BASE"; do
    curl -s -o /dev/null -w "%{http_code} $base\n" "$base/models"; done
  ```
- **Acción**: modo degradado explícito: responder con lo determinista
  disponible y abstención operativa honesta; **nunca** presentar
  `RETRIEVAL_UNAVAILABLE` como «no hay información». Avisar por el canal de ops
  y congelar releases hasta que al menos un provider responda.
- **Rollback**: al recuperar el primario, `reset_circuit(model)` global.
  **Owner**: Platform.

## 16. Migration problem (deploy bloqueado por migration)

- **Señales**: `alembic upgrade head` falla o tarda; pods en `CrashLoopBackOff`
  tras un deploy con migration; locks en `pg_locks`.
- **Diagnóstico**:
  ```bash
  uv run --frozen --no-sync alembic current
  uv run --frozen --no-sync alembic history -r -5:current
  psql "$PSQL" -c "select pid, state, query from pg_stat_activity where query ilike '%alter table%' or query ilike '%create index%'"
  ```
- **Acción**: si la migration no aplicó, el deploy no promociona. Si aplicó
  pero rompió la app: rollback de la app (runbook 12) y evaluar `downgrade` de
  la revisión (ver `docs/architecture/certification/migrations.md`: qué
  revisiones tienen downgrade probado y cuáles son forward-only).
- **Rollback**: `uv run --frozen --no-sync alembic downgrade -1` **solo** para
  revisiones con downgrade probado; si no, restaurar snapshot de DB.
- **Owner**: Platform.

## 17. Tool/API incident (tool caída, 5xx, timeout, salida inválida)

- **Señales**: steps `tool_call` con `error` en los runs; timeouts de tool
  (`RAG_AGENT_TOOL_TIMEOUT_SECONDS`); 5xx del endpoint externo; runs que cierran
  con evidencia parcial.
- **Diagnóstico**:
  ```bash
  docker compose -f docker-compose.prod.yml logs --tail=300 api | grep -E "tool_call|ToolError|timed out"
  psql "$PSQL" -c "select id, status, created_at from agent_runs where created_at > now() - interval '1 hour' and status<>'completed' limit 20"
  ```
- **Acción**: el guard de tools fallidas evita reintentos ciegos del mismo tool
  para la misma pregunta; un tool caído **no** debe convertir la respuesta en
  «no hay datos» (la evidencia parcial se declara). Deshabilitar el tool
  (`RAG_RAG_AGENT_TOOL_MODULES`) si está rompiendo runs en serie.
- **Rollback**: re-habilitar el tool al recuperarse el endpoint externo.
  **Owner**: AI Runtime.

## 18. Authority divergence (política vs camino legacy)

- **Señales**: `ZENTFinalizationDivergence`
  (`zent_finalization_divergence_total{stage,policy_action,legacy_action}`),
  `zent_finalization_shadow_divergence_total`.
- **Diagnóstico**:
  ```bash
  curl -s -H "Authorization: Bearer $M" $API/metrics | grep -E 'zent_finalization_(divergence|shadow_divergence)_total|zent_guard_divergence_total'
  pytest tests/test_finalization_golden.py tests/test_closure_authority.py -q
  ```
- **Acción**: **no** apagar la política para silenciar la divergencia: capturar
  el `reason_code`/`stage` del label, reproducir con el caso golden y corregir
  la regla. La autoridad determinista no puede divergir (invariante dura).
- **Rollback**: si la divergencia aparece tras un deploy, rollback (runbook 12).
  **Owner**: AI Runtime.
