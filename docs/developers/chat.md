# Chat

`client.chat()` envuelve `POST /api/v1/rag/query`.

## Python

```python
from zent import Zent

client = Zent(api_key="zent_sk_live_...")
response = client.chat("What is our refund policy?")
print(response.answer)
print(response.sources)

for event in client.chat.stream("Summarize Q4"):
    print(event.event, event.data)
```

Async:

```python
from zent import AsyncZent

async with AsyncZent(api_key="...") as client:
    print((await client.chat("hola")).answer)
```

## Node

```ts
import { Zent } from "zent-node";

const client = new Zent({ apiKey: process.env.ZENT_API_KEY! });
const res = await client.chat("What is our refund policy?");
console.log(res.answer);

for await (const event of client.chat.stream("Summarize Q4")) {
  console.log(event.event, event.data);
}
```

## HTTP

`POST /api/v1/rag/query` body `{ "query": "..." }` (campos opcionales: `conversation_id`, `temperature`, `top_k`, `role`).

Stream: `POST /api/v1/rag/query/stream` (SSE: `status`, `sources`, `delta`, `done`, `error`).

Scope requerido: `rag:read`.

## Public API (PROMPT 06)

- `POST /api/v1/deployments/{slug}/query` — consume un deployment healthy desde
  ERP/CRM/WMS. Body `{"input", "user": {"id"}, "context"}` → respuesta con
  `request_id, answer, data, sources, confidence, latency_ms`. Requiere API key
  con scope `agents:execute`.
- **Structured output**: si el agente tiene `config.output_schema`, la respuesta
  se valida (mini JSON Schema) antes de devolverse; si no cumple → 422.
- **API logs**: `GET /api/v1/deployments/logs` (endpoint, status, latency,
  tokens, cost, request_id, key).
- **Hardening de API keys**: `PUT /api/v1/organizations/api-keys/{id}` configura
  `ip_allowlist` (IPs/CIDRs) y `rate_limit_per_minute` (ventana 1 min). El
  middleware los aplica a cada request (403 ip_not_allowed / 429 key_rate_limited).
- Developer Center en `/developers`: Endpoints con snippets (cURL, Python,
  JavaScript, C#, Java, PHP), Logs y Sandbox.

## FinOps + Business Control (PROMPT 07)

- **Desglose de costos**: `GET /api/v1/platform/finops/breakdown?organization_id=&days=` —
  agregación 30d por workspace, agente, deployment, provider y modelo (requests,
  tokens, costo, %). `GET /api/v1/platform/finops/economics` — cost/request y
  cost/1K requests por tenant.
- **Atribución por deployment**: `usage_events.deployment_id` (migración 029);
  el endpoint público `/deployments/{slug}/query` lo registra automáticamente.
- **Alertas FinOps** (`POST /api/v1/platform/finops/check`): budget excedido
  (por org vía `PUT /finops/organizations/{id}/budget`), margen negativo
  (revenue paid < costo), usage spike (30d > 2x previo) y provider spike.
  Dedupe 24h; `GET /finops/alerts` + `POST /finops/alerts/{id}/ack`.
- **UI**: AI Costs (FinOps) en Control Center — cards de revenue/MRR/margen,
  cost/request, alertas accionables y tablas de desglose.

## Observability & Incident Management (PROMPT 08)

- **SLIs/SLOs por deployment** (`GET /api/v1/platform/organizations/{id}/slos`,
  `GET /api/v1/deployments/{id}/slos` tenant): ventanas 1h/24h/7d con requests,
  error rate, disponibilidad, p50 y p95 (percentile_cont sobre usage_events).
  Thresholds configurables: OBS_ERROR_RATE_THRESHOLD_PCT (5%),
  OBS_P95_LATENCY_MS (15s), OBS_AVAILABILITY_THRESHOLD_PCT (99%).
- **System health** (`GET /api/v1/platform/health`): probes a PostgreSQL,
  Redis, Qdrant, worker de ingestion (heartbeat) y configuración del LLM.
  El worker escribe `worker_heartbeats` en cada iteración del loop.
- **Incident alerts** (`POST /api/v1/platform/obs/check`): high_error_rate,
  high_latency_p95, low_availability, worker_stalled, deployment_unhealthy.
  Ciclo open → acknowledged → resolved (dedupe 24h).
- **Webhook al canal**: `PUT /api/v1/platform/organizations/{id}/ops-webhook`
  (URL + enabled). Delivery fail-soft con estado delivered/failed por alerta.
- **UI**: Control Center → System Status: grid de servicios, alertas accionables
  y tabla de SLOs por deployment (1h/24h/7d). Tenants ven SLOs e incidentes de
  sus deployments en la API.

## Enterprise — API Keys v2, SCIM 2.0, SSO OIDC (PROMPT 09)

- **API keys v2**: `POST /api-keys/{id}/rotate` (revoca y emite nueva conservando
  name/scopes/allowlist/rate-limit; auditoría `apikey.rotated`); expiración
  **forzada por política** `PUT /auth/sso/key-policy` (`max_age_days` por org,
  rechaza claves viejas en auth); `GET /api-keys/{id}/usage` (30d: requests,
  errores, tokens, costo, p95 desde api_logs).
- **SCIM 2.0** (`/api/v1/scim/v2/*`, Bearer token SCIM + X-Organization-Id):
  Users CRUD (userName/active/filter eq), Groups con **mapping grupo → rol de
  tenant** (`scim_groups.role_name`), PATCH members sincroniza roles, DELETE
  desprovisiona (quita membresías). Token: `POST /auth/sso/scim-token`.
- **SSO OIDC**: `GET /auth/sso/{org}/start` (redirect con state HMAC + nonce),
  `/auth/sso/callback` (discovery, code exchange, verificación JWT RS256/ES256
  contra JWKS, JIT provisioning con roles claim mapeados por scim_groups).
  Config en `GET/PUT /auth/sso/config`; client secret cifrado AES-256-GCM.
  `POST /auth/sso/test` = prueba de conectividad con el IdP.
- **Self-serve billing**: `POST /billing/subscription/upgrade` (X-New-Plan)
  + botón Upgrade en Facturación cuando `self_service_upgrade_enabled`.
- **UI**: rotación en Claves, callback SSO (`/sso/callback`), upgrade en Billing.

## Disaster Recovery (PROMPT 10)

- **Backups** (`POST /api/v1/platform/dr/organizations/{id}/backup`): pg_dump
  custom format vía docker + snapshot de Qdrant, con checksum sha256, tamaño y
  duración registrados en `dr_backups`. Listado `GET /dr/backups` y prune por
  retención `POST /dr/prune`.
- **DR drill** (`POST /dr/backups/{id}/drill`): restaura el dump en una DB
  standby (`rag_dr_*`) — validación NO destructiva de que el backup es
  restaurable (cuenta tablas y elimina la standby).
- **Readiness** (`GET /dr/readiness`): score 0-100 por tenant — backups
  habilitados, frescura vs RPO, snapshot Qdrant, regiones configuradas y
  heartbeat del worker.
- **Perfil DR por org** (`GET/PUT /dr/organizations/{id}`): regiones
  (catálogo `dr_regions`), RPO en minutos y backup_enabled.
- **Scheduler automático**: loop en el lifespan del API que crea backups cada
  `DR_SCHEDULER_INTERVAL_SECONDS` para orgs con backup_enabled y RPO vencido.
- **UI**: Control Center → Disaster Recovery: readiness por tenant, grid de
  backups con checksum y botones Backup now / Drill.

## Governance & Data Residency (PROMPT 11)

- **Perfil por tenant** (`GET/PUT /governance/organizations/{id}`): retención
  (días), región de residencia de datos (catálogo dr_regions) y contacto DSR.
- **Retención** (`POST /governance/purge`, dry_run/run): purga usage_events,
  api_logs y audit_logs más viejos que retention_days por org + evento
  `retention.purge` en compliance_events.
- **DSR (GDPR)** (`POST /governance/organizations/{id}/dsr-export|erasure`):
  export cifrado con **KMS envelope** + receipt sha256; erasure anonimiza
  usuarios (email → *@erased.invalid, password_hash NULL), borra membresías,
  actividad, auditoría, invites y secretos. Eventos `dsr.export`/`dsr.erasure`.
- **KMS envelope**: KEK = sha256(CONNECTOR_SECRETS_KEY), DEK por versión cifrado
  en reposo; una sola clave activa (create/rotate retira la previa; las viejas
  siguen descifrando). `GET /governance/kms/status|keys`, `POST
  /governance/kms/keys`, `POST /governance/kms/keys/{id}/rotate`,
  `POST /governance/kms/roundtrip` (probe).
- **UI**: Control Center → Governance: perfiles editables (retención/residencia/
  DSR), dry-run/aplicar purge, export/erase por tenant, panel KMS y log de
  cumplimiento.

## Enterprise Portal & Customer Success (PROMPT 12)

- **Invites con email real**: `POST /organizations/invites` envía la invitación
  por SMTP (fail-soft: sin SMTP → token entregado igual + `email_sent=false`,
  `delivery_status=skipped_no_smtp`). Settings `SMTP_*` en config.
- **Onboarding checklist derivado** (`GET /organizations/onboarding` tenant,
  `GET /platform/customer-success/onboarding` plataforma): workspace, KB,
  agente, deployment healthy, API key, primera consulta — computado de datos
  reales; `onboarding_completed_at` se marca solo.
- **Reportes de uso por email** (`report_subscriptions`): suscripciones
  tenant/platform, contenido real (economics + top agentes/providers + margen),
  `send-now` y scheduler cada 5 min en el lifespan (SMTP fail-soft).
- **Conversion analytics** (`GET /platform/customer-success/conversion`):
  funnel trial → paid (conversión %, activas por plan) vía join a plans.
- **Branding por tenant** (`GET/PUT /organizations/branding`): logo, color
  primario, workspace name (JSONB).
- **UI**: CC → Customers (funnel, onboarding por tenant, reportes con
  enviar-ahora) y tenant Settings (checklist, branding, suscripción a reportes).

## Audit Intelligence & AI Governance (PROMPT 13)

- **Audit intelligence** (`GET /platform/audit-intelligence/summary`): total de
  eventos, top acciones, top usuarios y timeline 30d (por org o global).
- **Detección de anomalías** (`POST /platform/audit-intelligence/check`):
  failed_login_burst (Redis auth:fail:*), api_error_spike (≥50% errores 5xx en
  1h con ≥20 reqs), night_activity (02-05h, ≥25 en 7d) y forbidden_spike
  (≥10 denied en 1h). Dedupe 24h; `GET /anomalies` + resolve.
- **PII masking** (`POST /platform/ai-governance/pii/mask|scan`): emails,
  teléfonos (con separador), DNI, RUC, tarjetas e IPs. Las políticas por org
  (`GET/PUT /platform/ai-governance/organizations/{id}`: pii_masking_enabled,
  guardrails JSONB) se aplican **en el endpoint público de query**: la respuesta
  se enmascara si la org lo habilita (`guardrails` en la respuesta).
- **Prompt revisions**: cada actualización de prompt guarda versión con
  contenido y autor (`GET /platform/ai-governance/prompts/{key}/revisions`).
- **UI**: CC → Audit Intelligence: cards, timeline, top acciones, anomalías
  accionables y test de PII masking.

## Performance & Cost Optimization Advisor (PROMPT 14)

- **Perfiles** (`GET /platform/optimizer/profiles`): por agente (30d) —
  requests, error %, p50/p95, tokens/req, cost/req, share de embeddings y
  fuentes/req; también por deployment (`deployment_id`).
- **Recomendaciones** (`POST /platform/optimizer/scan`): motor de reglas —
  cheaper_model (p95 alto o cost/req > $0.002 → alias zent-cheap, ~30%),
  reduce_top_k (>1500 tokens/req → top_k 3, ~15%), reduce_temperature
  (error > 10% → 0.3), prune_sources (>6 fuentes/req) y embedding_cache
  (>30% embeddings). Dedupe 7d por key+agente.
- **Aplicar/Ignorar** (`POST /recommendations/{id}/apply|ignore`): apply
  actualiza el agente (model=zent-cheap, config_json.retrieval.top_k=3,
  temperature=0.3) con `update_agent`; nota: los deployments requieren nueva
  versión + redeploy. `GET /recommendations` lista con estado.
- **UI**: CC → Optimizer: perfiles por agente y feed de recomendaciones con
  ahorro estimado y acciones Aplicar/Ignorar.
- ⚠️ Fix Dockerfile.api: `sqlalchemy[asyncio]~=2.0.30` (el resolver instaló una
  versión que rompió alembic: `cannot import name Column from
  sqlalchemy.sql.schema`; `>=2.0.30,<2.1` no sirve en RUN shell por la
  redirección `<`).

## Federated Search & Multi-Tenant Analytics (PROMPT 15)

- **Búsqueda federada** (`POST /api/v1/rag/federated`): consulta cross-KB (por
  `knowledge_base_ids` o `workspace_ids`, o todas las KBs del tenant) con
  embedding compartido y `search_hybrid` por KB (scoping estricto por org),
  **ranking unificado** (scores normalizados por KB) y **dedupe por contenido**.
  Respuesta con kb_name/workspace_name por fuente.
- **Multi-tenant analytics** (`GET /platform/analytics/federated`): totales
  (requests/tokens/costo/error rate 30d) + tabla por org (agentes, KBs,
  deployments, última actividad) con LIMIT 50 por costo. Drill-down por tenant
  (`GET /platform/analytics/organizations/{id}`): economics + breakdown + SLO
  agregado 24h.
- **Export CSV/JSON**: `?format=csv|json` en ambos endpoints (org rows con
  métricas; por tenant: metric/value + desglose por dimensión).
- **UI**: CC → Analytics: cards de totales, tabla por org con barras de
  requests, botón Export CSV.

## AI Agent Marketplace & Sharing (PROMPT 16)

- **Marketplace** (`/platform/marketplace/listings`): publicar agente (snapshot
  de name/prompt/tools/model/config, upsert por agent_id), listar (búsqueda q,
  categoría), detalle con snapshot, unpublish. Reviews/rating por listing
  (UNIQUE por org, promedio recomputado) e **install**: clona el snapshot en
  una org destino e incrementa installs.
- **Clone in-org**: `POST /api/v1/agents/{id}/clone`.
- **Share links públicos**: `POST /api/v1/agents/{id}/share` (expiry +
  max_uses) → `GET /api/v1/share/agents/{token}` **sin auth** (path público en
  el middleware) valida token/expiry/usos e incrementa el contador; listar y
  revocar. Landing `/share/agent/:token` en el portal.
- **Prompt templates** (`/platform/marketplace/templates`): repositorio con 4
  builtins sembrados (support/sales/finance/research) + CRUD (builtins no se
  borran).
- **UI**: CC → Marketplace (listings con rating/installs + instalar por org,
  templates con preview) y página pública de agente compartido.

## Advanced Workflows & Automation (PROMPT 17)

- **Definiciones** (`POST /api/v1/workflows` tenant, `/platform/workflows` CC):
  name, trigger manual|schedule|event, cron_expr y **pasos** JSON:
  ingest (encola ingestion_jobs), evaluate (SLO 24h con threshold),
  deploy (versión ready → entorno, crea entornos default), notify (email),
  webhook (POST), approval (pausa el run).
- **Runs**: status running → waiting_approval → completed | failed | canceled;
  pasos con detalles; **aprobación/rechazo** (`POST /runs/{id}/approve|reject`)
  reanuda desde el paso siguiente (start_index) o cancela.
- **Scheduler cron** en el lifespan: matcher `* */n valor,valor` (5 campos) con
  dedupe por minuto (`last_run_at`).
- **UI**: CC → Workflows: definiciones con pasos, disparar, tabla de runs
  (estado/paso/error).

## Model Gateway & Cost Routing v2 (PROMPT 18)

- **Rutas** (`/platform/model-gateway/routes`): por org con condición
  (default/cost/latency/quality + valor), modelo (o alias zent-cheap), peso
  de tráfico (**A/B**), prioridad y activación.
- **Resolución `zent-routed`**: si el agente usa el alias, el runtime resuelve
  la cadena de modelos (primario por pesos + fallbacks + default). Si el
  primario falla → **fallback automático** por modelo (registrado en steps como
  router_fallback). Modelos con presupuesto agotado se **excluyen** del router.
- **Presupuestos** (`/platform/model-gateway/budgets`): límite mensual por
  modelo (USD) con gasto computado de usage_events (mes actual), % de uso y
  flag `blocked`.
- **Analytics** (`/platform/model-gateway/analytics`): por modelo — requests,
  error %, p50/p95, tokens, costo y **fallbacks** (routing con >1 intento;
  columna `usage_events.routing`).
- **UI**: CC → Model Gateway: rutas con toggle, presupuestos con bloqueo y
  tabla de analytics.

## Real-Time Analytics & Streaming (PROMPT 19)

- **Streaming SSE** (`GET /platform/realtime/stream`): canal Redis `rag:events`
  (pub/sub) → eventos `agent_run` (runtime) y `api_query` (endpoint público)
  con heartbeat cada 15s; filtro opcional por org.
- **Summary en vivo** (`GET /platform/realtime/summary?minutes=`): requests,
  error rate, tokens, costo, orgs activas y top modelos de la ventana.
- **Series temporales** (`GET /platform/realtime/timeseries?hours=&format=`):
  buckets por hora con requests/errors/costo, export CSV.
- **Detección en vivo + corrección automática**: el consumidor (lifespan)
  detecta spikes de error por deployment (≥5 en 2 min, cooldown 2 min) →
  crea incident alert `realtime_error_spike`; con `POST
  /platform/realtime/auto-correction` activado (OFF por defecto) ejecuta
  **rollback automático** del deployment.
- **UI**: CC → Real-Time: feed de eventos en vivo (fetch-stream con auth),
  cards de la ventana y toggle de auto-corrección.

## Security Center (PROMPT 20)

- **Posture score por tenant** (`GET /platform/security/posture`): 0-100 con 10
  componentes ponderados — SSO, SCIM, política de rotación de keys, contacto
  DSR, residencia de datos, PII masking, webhook de alertas, expiración/rate
  limit/edad/allowlist de API keys.
- **Detección de secretos** (`POST /platform/security/scan-secrets` y scan
  global): api keys (zent_sk_/sk-), claves privadas, bearer tokens, passwords y
  SMTP_PASSWORD — escanea system_prompts de agentes, prompt_templates y
  snapshots del marketplace → `security_findings` (dedupe 7d).
- **Key leakage**: api_logs con `zent_sk_` en error → finding `api_key_leak` +
  **revoke one-click** (`POST /platform/security/keys/{key_id}/revoke`).
- **UI**: CC → Security Center: posture por tenant, findings con resolver y
  test de detección.

## Onboarding & Tenancy Self-Serve (PROMPT 21)

- **Provisioning 1-clic** (`POST /platform/onboarding/provision`): crea org +
  owner (JIT) + suscripción (trial o plan elegido con upgrade automático) +
  API key + demo content (KB + agente) + SSO opcional. Devuelve resumen con
  token.
- **Migración entre tenants** (`POST /platform/onboarding/migrate`): copia KBs
  (metadatos; re-ingest en destino) y agentes (clone con "(migrado)") con
  dedupe de nombres.
- **Trial extendido** (`POST /platform/onboarding/extend-trial`): auto-aprobado,
  solo orgs en status trialing (evento compliance `trial.extended`).
- **Catálogo de planes** (`GET /platform/onboarding/plans`) para el wizard.
- **UI**: CC → Onboarding: formulario de provisioning, migración y extensión.

## Capacity Planning & Auto-Scaling (PROMPT 22)

- **Capacity por tenant** (`GET /platform/capacity/organizations/{id}`): uso del
  mes (requests/tokens/costo) vs límites del plan, utilización %, **soft limit
  (80%)** y **hard limit (100%)**, **forecast 30d** (tasa diaria de 7d) con
  días hasta el límite y fecha proyectada.
- **Resumen global** (`GET /platform/capacity/summary`): orgs cerca del límite
  (soft/forecast ≥80% o ≤15 días) + profundidad de colas (knowledge Redis +
  ingestion_jobs SQL) + eventos de escalado.
- **Auto-scaling**: controller en el lifespan (umbral 50 → scale_up, ≤5 →
  scale_down, cooldown 10 min, 1-8 workers) registra `scaling_events`; toggle
  `POST /platform/capacity/workers/auto-scale` (OFF por defecto) + escalado
  manual.
- **Simulación** (`POST /platform/capacity/simulate`): crecimiento % →
  requests/costo proyectados, cost/request y excedencia de límites.
- **UI**: CC → Capacity: orgs near-limit con barras, colas, simulación y
  toggle de auto-scaling.

## Developer Experience Portal (PROMPT 23)

- **SDK reference auto-generada** (`GET /api/v1/dev/sdk-reference` tenant y
  `/platform/dev/sdk-reference`): endpoints principales (federated, deployment
  query, agents, KBs) con auth, ejemplo de body y **snippets en Python, JS,
  C#, Java y PHP**.
- **Webhooks salientes** (`/api/v1/webhooks` tenant): suscripción por evento
  (agent_run/api_query/deployment_event/incident/workflow_run) con **secret
  cifrado AES-GCM** y entrega con firma **X-Zent-Signature (HMAC-SHA256)**;
  dispatcher en el lifespan consume el canal rag:events; contadores de
  entregas/fallos + ping de prueba.
- **Changelog + status público** (`GET /api/v1/dev/status` y
  `/api/v1/dev/changelog`, sin auth): salud del sistema, versión de API y
  releases (tabla `platform_changelog` con 3 builtins sembrados; la plataforma
  agrega entradas).
- **UI**: `/developers/tools` (tabs SDK Reference / Webhooks / Estado) y
  `/developers/playground` (ejecutar APIs en vivo con deployments y body
  editable).

## Partner Ecosystem (PROMPT 24)

- **Partners con rev-share** (`/platform/partners`): crear partner (emite key
  dedicada `zent_sk_partner_*` con scope `partner:*` + acceso, vinculada por
  `api_keys.partner_id` y nombre único por partner), listar, actualizar,
  activar/suspender.
- **Metering**: el middleware propaga `ctx.partner_id` (TenantContext frozen →
  object.__setattr__) y el **public query registra consumo del partner**
  (tokens/costo). Uso 30d por día + **comisión por período** (revenue ×
  rev_share_pct en cents) con upsert en `partner_commissions`.
- **White-label**: subtenants por partner (share %) + branding (logo/color).
- **Catálogo de integraciones**: 6 builtins con OAuth URL template
  (Google Drive, Slack, Salesforce, HubSpot, Shopify, Notion) + add/toggle.
- **UI**: CC → Partners: crear con token, uso/comisión por partner, subtenants
  y grid de integraciones.

## AI Quality & Evals v2 (PROMPT 25)

- **Datasets versionados** (`eval_v2_datasets`/`eval_v2_items`): CRUD con
  items relacionales (pregunta/esperada/contexto/peso) y **bump de versión**
  automático al añadir items (v1 → v2 → …). Nota: `eval_datasets`/`eval_runs`
  de PROMPT 04 se conservan intactos.
- **Runs** (`eval_v2_runs`): por dataset × agente, ejecutando el runtime por
  item con **scoring heurístico sin LLM extra** (jaccard de tokens:
  score/faithfulness/hallucination) + p95 y costo.
- **Gate de promo**: `passed_gate` según EVAL_PROMOTION_MIN_SCORE (default 0)
  y EVAL_PROMOTION_MAX_HALLUCINATION; `auto_promote` promueve la versión a
  ready si pasa.
- **Regresión**: vs el mejor run previo del mismo agente+dataset (score,
  faithfulness, hallucination con deltas de EVAL_REGRESSION_*) → flag
  `regression`; `auto_rollback` revierte el deployment healthy.
- **UI**: CC → Evals Lab: crear dataset + items, ejecutar runs con toggles de
  auto-promote/auto-rollback, tabla con gate y regresión, detalle por item.

## Usage Metering & Rate Limits v2 (PROMPT 26)

- **Contadores en tiempo real (Redis)**: `record()` incrementa hashes
  `rag:meter:{org}:{day}` (requests/tokens/cost/errors), `rag:meter:model:*`
  por modelo y buckets por minuto para **burst 5 min**. Se alimentan desde
  `publish_agent_run` y `publish_api_query` (fail-soft, sin tocar la BD).
- **Rate limits por plan con burst** (`rate_limit_rules`): seed trial
  30/10, starter 60/15, pro 100/25, enterprise 500/100 + overrides globales
  por endpoint (`/api/v1/rag/query` 60/15, `/api/v1/deployments` 200/50).
  Regla aplicable = prefijo más largo (plan específico gana en empate).
  Enforcement en tenant_middleware (api_token/portal_session) con contador
  Redis por minuto + burst → 429 `rate_limit_plan_exceeded`.
- **Fair-use / throttling dinámico**: `throttle_factor` = uso del día vs
  budget diario (requests_per_month/30); >80% → factor reduce el burst
  (floor 0.2) aplicado en `effective_limits`.
- **UI**: CC → Metering: tarjetas en vivo (poll 10s), tabla por org con
  modelos y throttle, editor de reglas (plan/prefijo/límite/burst + toggle).
- Nota: tests mutan `plans.requests_per_month` (trial 30) y lo restauran
  a 500 en finally (seed original en 03-billing.sql).

## Multitenant LLM Proxy (PROMPT 27)

- **Catálogo de inferencia** (`inference_models`): backend (openai/vllm/tgi),
  capacidad de concurrencia, estado; seed gpt-4o-mini 50, gpt-4o 10,
  zent-cheap 100 (vllm), zent-fast 200 (tgi).
- **Cola por plan**: `rag:llm:queue:{plan}:{model}` con prioridad
  (enterprise 4 … trial 1); `admit()` → slot Redis de concurrencia
  (`rag:llm:inflight:{model}` con capacity) o enqueue + `estimate_wait_ms`
  (cola+inflight × latencia / concurrencia); el runtime espera ≤2 s y
  reintenta un slot (fail-open si Redis falla).
- **Rate limit por deployment**: `rate_limit_rules.deployment_id` + contador
  Redis `rag:rl:dep:*` → guard en `AgentRuntime.run()` → run con
  `deployment_rate_exceeded` (sin romper el 200 del caller).
- **Inference logs**: `inference_logs` por run (tokens, latencia, cola,
  costo, backend) desde el runtime; agregados `performance()` por modelo
  (requests, avg/p95 percentile_cont, throughput/min, errores) y filtros
  por org/deployment/modelo.
- **UI**: CC → Inference Proxy: cards de performance por modelo (p95, cola,
  throughput), catálogo con upsert de capacidad/backend, cola viva por plan
  y últimos logs (poll 8s).

## Multi-Region & Edge Caching (PROMPT 28)

- **Regiones + réplicas** (`regions`/`region_replicas`): 4 regiones
  (us-east-1, eu-west-1, ap-southeast-1, sa-east-1) con prioridad;
  healthcheck periódico (scheduler 60s en lifespan + forzable) con latencia
  de réplica; `organizations.primary_region_id` default us-east-1 (asignado
  también en el INSERT de organización).
- **Failover regional**: `resolve_region(org)` = primaria si su réplica está
  healthy, si no → siguiente healthy por prioridad (`failed_over`), cacheado
  60s en Redis; endpoint de simulación `POST /regions/{code}/failover`.
- **Edge cache**: en `POST /deployments/{slug}/query` — key por
  (org, deployment, version, sha256(input)); TTL por plan (trial 60,
  starter 300, pro 900, enterprise 1800); headers `X-Zent-Cache: HIT|MISS|BYPASS`
  + `Cache-Control: public, max-age=TTL` + `Age`; bypass con `?cache=false`
  o `Cache-Control: no-cache`; stats `rag:edge:hits/misses` (hit ratio).
  Nota: el hit no ejecuta el runtime (sin metering ni partner usage).
- **Latencia por región**: `inference_logs.region` (resuelta por run vía
  resolve_region) → agregados avg/p95 por región.
- **UI**: CC → Regions: tarjetas de región con health/latencia/probe,
  selector de org + resolución + simular failover, healthcheck manual,
  stats del edge cache y latencia por región (poll 15s).
- Fix: `response: Response` inyectado en la ruta (los headers no se pueden
  poner en el Pydantic model); variables shadowing corregidas.

## Cost Governance & FinOps v2 (PROMPT 29)

- **Costos por unidad de negocio**: `cost_tags` (org, key, value) + columna
  `usage_events.cost_tags JSONB` (GIN index); el runtime propaga
  `agent.config_json.cost_tags` al UsageEvent; `costs_by_tag(key)` agrupa
  por valor del tag (requests/cost/tokens).
- **Showback/chargeback**: `showback()` agrupa por
  `organizations.cost_team` o tag `team` (fallback `sin-equipo`) con share %;
  `cost_team`/`cost_business_unit` editables por org.
- **Alertas adaptativas**: `cost_alert_rules` con baseline = costo diario
  medio de la semana (excluye hoy); umbral = baseline × (1 + pct%);
  `cost_alerts` con **dedupe 24h por regla** (SELECT previo, no UNIQUE de
  timestamp); scheduler en lifespan (5 min) + evaluación manual.
- **Forecast**: regresión lineal simple sobre la serie diaria → trend/día y
  proyección 30d + desglose por plan (JOIN subscriptions con prefijo
  `u.organization_id` para evitar columnas ambiguas) y por modelo.
- **UI**: CC → Cost Governance: costos por equipo (barras), tags (crear/ver),
  showback por equipo, forecast (por plan/modelo), reglas adaptativas y
  alertas disparadas (selector de org + evaluar ahora).
- Fix asyncpg: JSONB se inserta con `json.dumps` (asyncpg no acepta dicts).

## AI Ops Runbook & Incident Management v2 (PROMPT 30)

- **Runbooks** (`runbooks`): trigger por tipo (cost_alert/slo/manual/
  deployment) con pasos JSONB (annotate, send_webhook, send_email, sleep);
  seed de 3 runbooks. Los pasos se registran como `runbook_step` en el
  timeline y se ejecutan al abrir el incidente (auto-run).
- **Incidentes** (`incidents` + `incident_events`): severidad
  (severe/major/minor), estados open/acknowledged/resolved, MTTD
  (occurred→detected) y **MTTR** (detected→resolved); timeline con
  created/runbook_step/acknowledged/escalation/resolved.
- **Integración**: `run_cost_alerts` abre incidente `cost_alert` (major)
  con auto-runbook al disparar una alerta de costo.
- **Escalamiento automático** (`escalation_policies` por severidad con
  pasos after_minutes + notify webhook/email): `check_escalations()` con
  **retry 3×5s** y dedupe por marker `step=N` (el UNIQUE por timestamp no
  servía); scheduler 60s en lifespan + endpoint manual.
- **Métricas**: MTTR/MTTD promedio por severidad.
- **UI**: CC → Ops Center: cards de métricas, tabla de incidentes con
  filtros + ack/resolver, detalle con timeline, apertura manual con
  auto-runbook y runbooks CRUD.
- Fixes: `ctx.user_email` no existe (→ `ctx.user_id`); ruta `/metrics`
  debe registrarse ANTES de `/{incident_id}` (orden de match); FK del
  evento "created" (commit del incidente antes de _append_event).

## AI Model Budgets & Guardrails v2 (PROMPT 31)

- **Budgets por modelo con throttling adaptativo**: `model_budgets` (gateway)
  → `model_budget_status(org, model)`: uso mensual vs budget; >100% →
  bloqueado (run con guardrail `model_budget_exceeded`); 80-100% → factor
  reduce `max_tokens` en el runtime (floor 0.2).
- **Guardrails de salida** (`output_guardrails`): kinds toxicity /
  banned_topics / custom_pattern / length_limit / pii (reutiliza
  `mask_pii` de AI Governance); acciones mask / block / warn;
  `protect_answer()` se aplica en public_query (block → 422). CRUD + toggle.
- **Circuit breakers** (`model_circuit_breakers`): umbral de fallos en
  ventana → estado open con cooldown; el runtime cuenta fallos/timeouts
  (record_failure) y éxitos (record_success → half_open); con
  `zent-routed` salta al siguiente candidato (auto-fallback), sin
  candidato → run bloqueado con `model_circuit_open`; trip/reset manuales.
- **Dashboard de salud** por modelo: requests/tokens/cost/error_rate/
  avg/p95 latencia (inference_logs) + estado del circuito.
- **UI**: CC → Model Health: cards por modelo, ventana 1/6/24h, budgets
  (throttle/bloqueo), guardrails CRUD con toggle, circuit breakers con
  Trip/Reset (poll 10s).

## Revenue Intelligence & ARR (PROMPT 32)

- **Ledger** (`subscription_events`, extendida de PROMPT 12): se añaden
  `plan_name` + `mrr_cents` y se amplía el CHECK (upgraded/downgraded/
  renewed/expired). Backfill de 'created' para subs vigentes (3116).
  Hooks en billing: trial → created (mrr 0), upgrade_plan →
  upgraded/downgraded (mrr del plan), cancel → canceled.
- **ARR/MRR**: `revenue_summary` — MRR por plan (trial→0), ARR = MRR×12,
  trials creados, churn rate (cancelados/expired vs iniciados en ventana),
  expansión (Σ upgraded), contracción (Σ downgraded) y MRR churned + delta
  neto.
- **Cohortes trial→paid**: funnels por mes — trials, convertidos (active +
  plan no-trial), tasa, retenidos y MRR actual de la cohorte.
- **Forecast**: conversión media (6 meses) × crecimiento de trials → MRR
  nuevo proyectado por mes (6 meses).
- **Export CSV**: por org/plan/status/mrr/arr con `Content-Disposition`.
- **UI**: CC → Revenue: cards (MRR/ARR, expansión, contracción, churn),
  MRR por plan (barras), forecast, cohortes con tasas y ledger + botón CSV.
- Fixes: `price_monthly_cents` es DECIMAL (float() en forecast); el CHECK
  de event_type de PROMPT 12 rechazaba 'upgraded'/'downgraded'.

## Data Export & Compliance v2 (PROMPT 33)

- **Export ZIP del tenant** (`data_exports`): scopes all/kb/agents/usage/
  config → `data/exports/{org}/{uuid}.zip` con manifest.json + secciones
  JSON; `row_counts` por sección; descarga con Content-Disposition.
- **Auditoría**: cada export registra requested_by (user id del admin),
  requested_at, completed_at, scope, anonimizado y tamaño (lista
  consultable en CC).
- **Anonimización**: emails → sha256[:12] (pseudonimizado), ids de usuarios
  → hash, y granularidad de fechas a día en usage (k-anonimity básico:
  cohortes (org, modelo, día) indistinguibles). Aplica sobre config.owner
  y usage.created_at.
- **Retención granular** (`retention_policies`): global o por org, con
  whitelist de tablas (usage_events 365d, inference_logs 90d, api_logs
  180d, conversations 180d, agent_versions 730d, audit_logs 730d);
  `run_retention_purges` borra por created_at < cutoff y registra en
  `retention_purges`; scheduler diario en lifespan + purga manual.
- **UI**: CC → Data Export: crear export (scope + anonimizar), tabla de
  auditoría con descarga, políticas de retención (upsert/toggle/delete) y
  historial de purgas + "purgar ahora".
- Fixes: `config.organization.owner` anidado (la anonimización esperaba
  top-level); owner user tiene email NULL en tests (email real requerido);
  tabla `subscription_events`/retention whitelist → S608 per-file.

## AI Trust & Safety Center (PROMPT 34)

- **AUP versionada** (`aup_terms` v1 seed + `aup_consents` UNIQUE por org):
  accept/upsert con versionado; `consent_status` detecta versiones
  desactualizadas.
- **Moderación de contenido con puntuación** (`content_moderation_rules`
  globales u org): score = matches/patrones (regex o palabras); ≥ min_score
  → acción block/warn + **safety_incident** (org, dirección input/output,
  snippet, score). Seeds: malware (block, 0.5), asesoría financiera (warn,
  0.6), temas prohibidos (block, 0.5), toxicidad (warn, 0.6).
- **Integración en public API**: moderación del INPUT antes del run y del
  OUTPUT tras los guardrails (block → 422). Fix clave: el `_respond(422)`
  lanzaba HTTPException DENTRO del try/except que la envolvía → se tragaba
  el error y devolvía 200; ahora el raise queda fuera del try.
- **Panel de incidentes**: listado con filtros (org/status/direction),
  resolver (con nota y resolved_by) y desestimar (falsos positivos).
- **Dashboard de confianza**: por regla/dirección/acción — totales,
  resueltos, resolution rate, score promedio; bloqueos vs consultas
  (usage_events) → block_rate.
- **UI**: CC → Trust & Safety: AUP con aceptación por org, reglas CRUD con
  toggle, tasas por regla y tabla de incidentes con resolver/desestimar.

## Tenant Self-Service Billing & Invoices v2 (PROMPT 35)

- **Facturas mensuales** (`invoices` + `invoice_items`): generate_invoice
  del mes anterior (idempotente por UNIQUE org+period) con items de
  suscripción prorrateada (días/30) + usage por modelo (usage_events);
  IVA 19%; número INV-YYYYMM-XXXXXX.
- **Portal tenant**: listar/detalle (items), descargar CSV y PDF (PDF
  mínimo sin dependencias), pagar (webhook interno) y perfil de facturación
  (razón social, tax_id, dirección, método de pago card/sepa/wire/manual,
  últimos 4) — extendida la página Billing.tsx existente.
- **Webhook de pago público** (`POST /api/v1/payments/webhook`, stripe-like,
  path público en tenant_middleware): payment_intent.succeeded / invoice.paid
  marcan la factura como paid (payment_intent_id, paid_at) y registran el
  evento con **dedupe por provider_event_id UNIQUE** (replay → duplicate).
- **Compat con el módulo invoices previo** (billing/webhooks.py + scripts +
  tests): ensure_billing_tables no-op, record_payment (inserta en
  payment_events Y payments legacy + notificación payment.manual_review
  para pagos manuales), upsert_invoice (con invoice_number generado) y
  mark_invoice_paid.
- Fix: la tabla `invoices` preexistía con otro schema → migración extendida
  con ALTERs; upsert_billing_profile solo actualiza campos presentes
  (NOT NULL en default_payment_method); token dev admin/sql restaurado en
  tenant_middleware (rag_test_dev_token_* en development/test).

## AI Observability Traces & Spans v2 (PROMPT 36)

- **Traces + spans** (`traces` + `trace_spans`): el runtime registra una
  traza por run (input/output/status/latencia/tokens/costo) con spans por
  etapa con **timings reales**: `llm` (latencia del generate + tokens),
  `retrieval`/`rerank`/`tool` (mapeo por nombre de tool, latency del
  execute_tool_guarded), `total`. `trace_id` = header X-Trace-Id o run_id.
- **Correlación**: `usage_events.trace_id` + `api_logs.trace_id` — los
  endpoints public_query y agent_runs propagan el X-Trace-Id al request;
  `trace_usage(trace_id)` cruza el run con sus eventos de billing/logs.
- **Búsqueda/exploración**: filtros org/agente/deployment/status/modelo +
  búsqueda por texto en input/output (ILIKE); detalle con spans ordenados.
- **Comparación side-by-side**: mismo input detectado, deltas de
  latencia/tokens/costo/spans y diff por etapa (A vs B).
- **Dashboard por etapa**: spans, avg/p95 duración, tokens, error rate.
- **UI**: CC → Traces: filtros + tabla, detalle con spans (barras por
  etapa), selector A/B para comparar, correlación de usage.
- Fix: `:lat / 1000.0` en SQL → AmbiguousParameterError (started_at
  calculado en Python); ruta `/traces/compare` antes de `/{trace_id}`.

## Multi-Tenant Notifications & Webhooks v2 (PROMPT 37)

- **Centro in-app** (`tenant_notifications`): listado con filtros
  (unread/event_type), marcar leída, marcar todo leído, archivar, contador
  de no leídas; ruta /api/v1/notifications (tenant).
- **Preferencias por canal** (`notification_preferences`): channels
  in_app/email/webhook + overrides por evento (events JSONB); notify()
  respeta cada canal (email fail-soft al owner).
- **Webhook deliveries** (`webhook_deliveries`): notify() encola entregas
  para las suscripciones activas (firma HMAC X-Zent-Signature al encolar);
  `process_deliveries` (worker 30s en lifespan) POSTea con backoff
  exponencial (1m/5m/30m/2h/6h, máx 5 intentos) y actualiza counts de la
  suscripción. Fix: payload JSONB vuelve como dict → json.dumps para httpx;
  CASTs explícitos para binds (AmbiguousParameterError).
- **Hooks**: quota.exceeded (runtime), invoice.paid (webhook de pago) +
  trigger manual desde CC.
- **Dashboard**: entregas recientes (estado/intentos/HTTP/latencia/error) y
  por suscripción (success rate, avg latency) en CC.
- **UI**: tenant → /notifications (centro + preferencias); CC → Webhooks &
  Notifications (trigger, entregas, cola de reintentos).

## Tenant Audit & Compliance Reports v2 (PROMPT 38)

- **Reportes de auditoría** (`audit_reports`): por tipo (activity via
  audit_logs, config_changes via agent_versions+agents, exports via
  data_exports, incidents via safety_incidents+incidents, full) y formato
  CSV/PDF (PDF mínimo reutilizado de invoices) con período configurable.
- **Integridad con hash encadenado**: sha256 del contenido +
  `prev_hash` = hash del reporte anterior de la org (cadena); `verify`
  re-hashea el archivo y comprueba la cadena (detección de manipulación).
- **Compliance por framework**: 24 controles seed (SOC2 ×8, GDPR ×8,
  ISO27001 ×8) con categoría y evidencia requerida; `compliance_status`
  auto-inicializa en 'review'; update por control (pass/fail/na/review +
  evidence); score = pass/total.
- **UI**: tenant → /audit (generar/descargar/verificar reportes + tabla de
  controles con cambio de estado); CC → Compliance (dashboard por framework
  con score + reportes globales con cadena).
- Fixes: `_render_csv` era async (llamada sin await); permisos del owner
  (billing:* en vez de audit:*); pattern de status valida antes → 422.

## Tenant Onboarding Experience v2 (PROMPT 39)

- **Checklist interactivo** (`onboarding_progress`): 5 pasos
  (create_kb → add_documents → create_agent → deploy_agent → first_query)
  con estado JSONB, current_step y **TTFV** al completar (completed_at -
  started_at).
- **Sync automático desde acciones reales**: `sync_progress` reconcilia el
  checklist consultando KBs/documents/agents/deployments (env production)/
  usage_events; hooks fail-soft en create KB, create agent, create
  deployment y run de agente — el checklist se llena solo al usar la
  plataforma. `complete_step` manual también disponible.
- **Guías contextuales** por siguiente paso (título/cuerpo/href) + estado de
  la org (pct, pasos done/pendientes).
- **Métricas de activación** (platform): total orgs, completadas, tasa,
  TTFV promedio y **funnel por paso** (onboarding_events).
- **UI**: tenant → /onboarding (checklist con progreso, siguiente paso y
  botón "Ir"); CC → Onboarding (cards de métricas, funnel y progreso por
  org con badges por paso).
- Fix: `_default_steps` async llamada sync (coroutine no serializable);
  AdminOnboardingPage ya existía (PROMPT 21) → renombrado a
  AdminOnboardingMetricsPage.

## Sentiment & Feedback Analytics (PROMPT 40)

- **Recolección** (`feedback`): thumbs up/down por run (upsert por run_id
  UNIQUE) con motivo opcional (wrong_answer/too_long/too_slow/confusing/
  other) y comentario; endpoints tenant POST /api/v1/feedback + analytics
  y trends por org. El Chat ahora pide el **motivo** al marcar "no útil"
  (select de causas → /api/v1/feedback con trace_id).
- **Analytics por agente**: total/ups/downs, **CSAT** (up/total) y **NPS
  proxy** ((up-down)/total×100); global y por agente; window 24h/7d/30d.
- **Causas del negativo + correlación**: desglose por motivo con pct y
  correlación con traces del mismo trace_id (latencia avg/max, tokens,
  longitud de output) → insights ("respuestas down son 1.3s y 400 tokens").
- **Tendencias**: serie diaria up/down/CSAT (14 días).
- **UI**: CC → Feedback: cards CSAT/NPS/negativo/causa principal, tabla por
  agente, tendencia diaria y correlación de causas.
- Fixes: concatenación de WHERE sin espacio ("feedback fWHERE");
  avg_latency 1300ms (media de 900/1300/1700).

## Tenant Data Migration Tools (PROMPT 41)

- **Import CSV/JSON** (`data_migrations` + `migration_staged`): parse de
  filas, validación por kind (KB: name; agents: name + model del catálogo),
  **dry-run** con conteos válidas/inválidas, preview de las primeras 10 y
  errores por fila (sin aplicar) → luego **apply** crea KBs/agentes reales
  con detección de duplicados (fallan).
- **Export con manifest**: KBs/agentes → JSON con manifest (org, kind,
  timestamp, schema_version, counts) descargable.
- **Re-versión de agentes**: `reversion_agent` crea una nueva
  agent_version desde el config actual (para rollback post-migración).
- **UI**: tenant → /migrations (textarea CSV/JSON + preview + aplicar +
  exportar/descargar + historial); CC → Migrations (dashboard por
  estado/kind, filas aplicadas/fallidas y tabla global).
- Fixes: `migration_staged` agregada (apply necesita el contenido original);
  apply cuenta inválidas+duplicadas en rows_failed; duplicados → re-apply
  devuelve 404 (ya applied); nombres de KBs únicos por run en tests;
  Dockerfile api con --no-cache (la nueva migración no entraba al COPY).

## AI Agent Versioning & Rollout v2 (PROMPT 42)

- **Historial + diff** (`agent_releases`, `release_events`): versiones por
  agente; `diff_versions` compara config_snapshot (config_diff: añadido/
  eliminado/cambiado por campo), prompt (chars + changed) y flags de
  model/tools.
- **Rollout canary/stable**: `start_release` (canal + % tráfico), health-gate
  (`health_check` → score 0-100 ponderado: p95 vs 500ms 40% + error rate 40%
  + promedio evals 7d 20%; sin tráfico ni evals → 100; gate ≥70),
  `promote` (actualiza deployments healthy del agente a la versión +
  registra promoted_by), `rollback` (reversión a la versión anterior),
  pause/resume. Eventos por release para auditoría.
- **UI**: tenant → /releases (start canary con % tráfico, health/promote/
  rollback/pausar/reanudar, detalle con timeline de eventos, diff A/B con
  colores por tipo de cambio); CC → Releases (dashboard por agente con
  canary/stable + health, historial completo).
- Fixes: `eval_v2_runs` no tiene created_at → completed_at en health_check;
  snap JSON en tests con json.dumps (repr generaba JSON inválido).
