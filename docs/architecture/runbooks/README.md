# Runbooks — operación de ZENT

Índice de incidentes. Cada runbook: señales, diagnóstico, acción, rollback y
owner. Las métricas citadas se exponen en `/metrics`; las alertas de incidentes
también viven en `src/platform/observability/alerts.py` (webhook del tenant).

---

## 1. LLM outage (proveedor caído o inaccesible)

- **Señales**: `zent_provider_attempts_total{status=~"provider_error|timeout"}`
  sube; `zent_model_circuit_openings_total` con scope global; errores 5xx del
  gateway; runs con `PROVIDER_FAILURE` como stop reason.
- **Diagnóstico**: `/health` (bloque LLM), `resolve_route` + candidatos
  configurados (`GATEWAY_FALLBACK_MODEL`), estado del breaker por modelo.
- **Acción**: verificar credenciales/base URL; si el primario está caído,
  confirmar que el fallback configurado responde; si no hay fallback sano,
  degradar a modo sin generación (respuesta determinista/abstención operativa,
  nunca «no hay información») y avisar por el canal de ops.
- **Rollback**: al recuperar el proveedor, `reset_circuit(model)` (admin) y
  confirmar cierre de circuitos.
- **Owner**: Platform.

## 2. Qdrant outage (retrieval no ejecuta)

- **Señales**: `rag_agent_retrieval_unavailable_total`,
  `zent_run_evidence_total{status="failed"}`, latencias de vector search con
  error, `rag_errors_total` de conexión.
- **Diagnóstico**: `/health` (Qdrant), latencia de `search`, colecciones
  esperadas por tenant.
- **Acción**: el runtime marca `RETRIEVAL_UNAVAILABLE` (jamás «no hay
  evidencia»); reintentar la ronda si el usuario puede; revisar el servicio y
  su volumen.
- **Rollback**: ninguna acción en ZENT; el estado del run ya es honesto.
- **Owner**: Knowledge.

## 3. Redis outage (caché/historial)

- **Señales**: warnings `Redis GET/SET failed`; `zent_cache_bypass_total`
  puede no aplicar (es política, no fallo); latencias de conversación.
- **Diagnóstico**: ping del servicio, memoria, evictions.
- **Acción**: la caché es fail-soft (sin Redis el run sigue): confirmar que las
  respuestas no se sirven cruzadas (no hay caché), y que el historial no se
  pierde de forma silenciosa para el usuario (se recalcula desde DB si aplica).
- **Rollback**: al volver Redis, las claves se repueblan solas (TTL corto).
- **Owner**: Platform.

## 4. DB saturation (Postgres lento o pool agotado)

- **Señales**: pool con `waiting > 0` sostenido, timeouts de sesión, p95 de
  endpoints de lectura, queries lentas en logs.
- **Diagnóstico**: `pg_stat_activity` (activas/esperando), locks, tamaño de
  pool vs concurrencia.
- **Acción**: identificar la query (N+1 conocidos en ingestion), matar
  long-runs de mantenimiento, subir pool con cuidado (max_connections);
  degradar endpoints de analytics.
- **Rollback**: revertir migration con lock (ver checklist de migraciones en
  `docs/architecture/hardening/00-audit.md` §6).
- **Owner**: Platform.

## 5. Provider 429 (rate limit)

- **Señales**: `zent_provider_attempts_total{status="rate_limited"}`,
  `PROVIDER_RATE_LIMIT` como stop reason.
- **Diagnóstico**: RPM configurado (`LITELLM_MAX_RPM`), cuota del proveedor,
  tráfico concurrente.
- **Acción**: el router reintenta una vez y pasa al fallback; si el 429 es
  cuota, el failover directo es lo esperado. Subir cuota o bajar concurrencia
  (backpressure: queue/limit antes que colapsar).
- **Rollback**: n/a (no hay cambio de configuración).
- **Owner**: Platform.

## 6. Circuit open (modelo marcado como caído)

- **Señales**: `zent_model_circuit_openings_total{scope}`; la alerta multi-tenant
  (`ModelCircuitMultiTenantOpen`) indica problema de provider, no de un tenant.
- **Diagnóstico**: revisar fallos por modelo y scope; distinguir tenant vs
  global.
- **Acción**: si es global, tratar como LLM outage; si es un tenant, revisar su
  clave/cuota (no tocar el circuito global).
- **Rollback**: `reset_circuit(model)` / `reset_circuit(model, scope)`.
- **Owner**: Platform.

## 7. Cost spike (costo o costo desconocido)

- **Señales**: `zent_run_cost_usd_total` por encima del baseline;
  `zent_run_cost_unknown_total` si el pricing no está configurado.
- **Diagnóstico**: por path (agent/rag), propósito de las llamadas del run
  (`steps[type=llm].purpose`), tarifas de la tabla de pricing, JEV.
- **Acción**: activar degradación de presupuesto (reranker/top_k/polish),
  revisar `RUNTIME_JEV_SKIP_*`; si el costo es desconocido, cargar tarifas
  (nunca inventar 0).
- **Rollback**: n/a.
- **Owner**: FinOps.

## 8. High abstention rate

- **Señales**: `zent_runs_total{phase="ABSTAINED"}` alto;
  `zent_run_evidence_total{status="insufficient"}`.
- **Diagnóstico**: distinguir `INSUFFICIENT_EVIDENCE` (faltan datos/cobertura)
  de `RETRIEVAL_UNAVAILABLE` (fallo operativo: runbook 2).
- **Acción**: revisar cobertura del corpus (knowledge gaps), reglas canónicas,
  queries ambiguas; no bajar el umbral de evidencia para «mejorar» el número.
- **Rollback**: n/a.
- **Owner**: Knowledge.

## 9. High undetermined rate

- **Señales**: `zent_runs_total{phase="UNDETERMINED"}` alto.
- **Diagnóstico**: consultas ejecutables sin autoridad determinista, premisas
  faltantes, conflictos de reglas.
- **Acción**: cargar/revisar la regla o política que falta; el estado es
  fail-closed por diseño (no se completa la semántica por defecto).
- **Rollback**: n/a.
- **Owner**: AI Runtime.
