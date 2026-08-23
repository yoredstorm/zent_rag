# RAG-as-a-Service Platform

AI Agent Orchestration con Retrieval-Augmented Generation (RAG) multi-organization, full observability y facturación integrada.

## Quickstart (developer)

```python
from zent import Zent

client = Zent(api_key="zent_sk_live_...")
print(client.chat("What is our refund policy?").answer)
```

Docs: [docs/developers/quickstart.md](docs/developers/quickstart.md). API versionada en `/api/v1`.

## Stack Tecnológico

| Capa | Tecnología | Rol |
|---|---|---|
| **API Gateway** | FastAPI (Python 3.11) | REST API, validación Pydantic, Swagger/ReDoc autodocumentado |
| **BD Relacional** | PostgreSQL 16 + pgvector | Organizations, usuarios, billing, schemas de datos de dominio |
| **BD Vectorial** | Qdrant v1.13 | Embeddings y búsqueda semántica (HNSW) |
| **Caché** | Redis 7 | Rate limiting, caché de embeddings, colas de tareas |
| **LLM Proxy** | LiteLLM | Proxy unificado: OpenAI, Anthropic, Ollama, Azure, etc. |
| **Embeddings** | LiteLLM → Novita/Ollama (bge-m3) | 1024-d; cloud rápido / Ollama CPU lento |
| **Observabilidad** | Prometheus + Loki + Promtail + Grafana | Métricas + Logs centralizados + Dashboards |
| **DB Migrations** | Alembic | Migraciones versionadas para PostgreSQL |
| **Tests** | PyTest + httpx | Tests asíncronos con ASGITransport |

## Arquitectura

```
┌─────────────────────────────────────────────────────────────────┐
│                    RAG-as-a-Service Platform                    │
├─────────────────────────────────────────────────────────────────┤
│  API Layer (FastAPI) — composition root                        │
│  ├── /health          Health check                              │
│  ├── /metrics         Prometheus metrics (scrape token)         │
│  ├── /api/v1/rag/*    RAG Query endpoint                        │
│  ├── /api/v1/ingestion/*  Data ingestion (SQL → Vector DB)     │
│  ├── /api/v1/admin/*  Dynamic table management (dev only)       │
│  ├── /api/v1/billing/*  Subscription & API key management       │
│  ├── /mcp               MCP Server (Streamable HTTP, stateless) │
│  └── /docs            Swagger UI auto-generated                 │
├─────────────────────────────────────────────────────────────────┤
│  agents/runtime — Orquestador (SQL-first vs RAG) + policies     │
├─────────────────────────────────────────────────────────────────┤
│  core/ — isla agnóstica de negocio                             │
│  ├── domain/   entidades puras (Organization, RetrievalChunk, ...)    │
│  ├── ports/    ABCs: repos, LLMProvider, VectorStore, Cache...  │
│  └── config.py  settings validados (fail-fast en producción)    │
├─────────────────────────────────────────────────────────────────┤
│  platform/  auth · organizations · users · billing · usage            │
│  rag/       retrieval · chunking · reranking · evaluation       │
│  connectors/sql  schema discovery · ingestion · queue · worker  │
├─────────────────────────────────────────────────────────────────┤
│  infrastructure/ — adaptadores concretos (implementan ports)    │
│  ├── postgres/  session factory + repos                         │
│  ├── redis/     cache                                            │
│  ├── qdrant/    vector store                                     │
│  ├── llm/       LiteLLM provider + circuit breaker (resilience)  │
│  ├── observability/  logging · tracing · metrics                 │
│  └── secrets/   Vault                                            │
├─────────────────────────────────────────────────────────────────┤
│  verticals/ — lógica vertical como plugins (demo_farmacia)      │
│  ├── prompts.py      system prompts del dominio                  │
│  ├── heuristics.py   reescrituras SQL del dominio                │
│  └── golden/         golden sets de evaluación                   │
├─────────────────────────────────────────────────────────────────┤
│  Observability Stack (PLG)                                      │
│  ├── Prometheus   Metrics scraping from /metrics                │
│  ├── Loki         Centralized structured JSON logs              │
│  ├── Promtail     Log tailing agent for Docker containers       │
│  └── Grafana      Pre-configured dashboards (health, billing)   │
└─────────────────────────────────────────────────────────────────┘

Reglas de dependencia (enforced por tests/test_architecture.py):
- core/ es una isla: no importa nada fuera de src.core.
- infrastructure/ no importa capas superiores (api/rag/agents/platform/connectors/verticals).
- rag/ y agents/ no importan adaptadores (solo puertos + factory de sesión).
- Sin strings de negocio vertical (farmacia, order_status, ...) en core/rag/agents/platform.
- Toda lógica vertical vive en verticals/ (plugins) o en organizations.config_json.
```

## Flujo RAG (Query → Response)

```
1. POST /api/v1/rag/query  { query, organization_id, user_id, model? }
│
2. Resolver organization + validar API Key / rate limit
│
3. Generar embedding de la pregunta (LiteLLM → Novita/Ollama bge-m3)
│
4. Búsqueda semántica en Qdrant (top-k chunks relevantes)
│
5. Recuperar schema SQL y ejecutar SQL Expert si aplica
│
6. Ensamblar prompt con contexto recuperado:
│      [System Prompt + SQL Schema + Chunks + Conversation History + User Query]
│
7. Generar respuesta con LLM (LiteLLM → OpenAI/Anthropic/Novita AI)
│
8. Registrar tokens consumidos para facturación
│
9. Respuesta: { query_id, answer, sources[], usage{}, latency_ms }
```

## Estructura del Proyecto

```
zent_rag/
├── src/
│   ├── api/                    # FastAPI REST Layer (composition root)
│   │   ├── main.py             # App factory, middleware, routers, lifespan
│   │   ├── deps.py             # Dependency injection (Clean Architecture)
│   │   ├── schemas.py          # DTOs HTTP (request/response Pydantic)
│   │   ├── security.py         # Authz HTTP (organization/rol desde Bearer)
│   │   ├── middleware.py       # Trace ID injection, structured logging
│   │   ├── tenant_middleware.py # Auth + TenantContext (org/user/roles/perms)
│   │   ├── rate_limit_middleware.py / body_limit / idempotency
│   │   └── routes/             # query, ingestion, admin, billing, auth, eval,
│   │                           # prompt, health, organizations, projects,
│   │                           # knowledge_bases, agents, connectors, audit
│   │
│   ├── mcp_server/             # MCP Server (composition root, montado en /mcp)
│   │   ├── app.py              # MCPServer + transporte Streamable HTTP
│   │   ├── tools.py            # search_knowledge, query_database, get_document,
│   │   │                       # execute_agent, get_usage
│   │   ├── policy.py           # RBAC + config_json['mcp'] + rate limits por tool
│   │   ├── context.py          # identidad desde TenantContext (nunca arguments)
│   │   └── audit.py            # audit_logs + usage_events por tool call
│   │
│   ├── core/                   # Isla agnóstica de negocio (cero frameworks)
│   │   ├── domain/             # entities.py, services.py
│   │   ├── ports/              # ABCs: platform_repos, rag_ports, sql_expert
│   │   └── config.py           # Settings tipados (prefix RAG_)
│   │
│   ├── agents/                 # Runtime del agente
│   │   ├── runtime/            # orchestrator.py (SQL-first vs RAG)
│   │   ├── tools/              # sql_expert_postgres.py (NL → SQL validado)
│   │   └── policies/           # authorization.py (RBAC puro), prompt injection
│   │
│   ├── platform/               # Capacidades SaaS de plataforma
│   │   ├── auth/               # session.py, passwords.py, rate_limit.py
│   │   ├── billing/            # service.py (planes, suscripciones, tokens)
│   │   └── usage/              # lazy_rate_limit.py, lazy_activity.py
│   │
│   ├── rag/                    # Capacidad RAG genérica
│   │   ├── reranking/          # reranker.py
│   │   └── evaluation/         # store.py (feedback/stats) + eval engine
│   │                           # (datasets, metrics, judge, targets, runner,
│   │                           # snapshot, regression)
│   │
│   ├── connectors/sql/         # schema_discovery, ingestion, queue, worker
│   │
│   ├── infrastructure/         # Adaptadores concretos (implementan ports)
│   │   ├── postgres/           # session.py + relational_db.py (repos)
│   │   ├── redis/              # cache.py
│   │   ├── qdrant/             # vector_store.py
│   │   ├── llm/                # provider.py (LiteLLM)
│   │   ├── resilience/         # circuit_breaker.py
│   │   ├── observability/      # logging_config, tracing, metrics
│   │   ├── secrets/            # vault.py
│   │   └── db_init/            # SQL schemas + Alembic + seed-demo/ (gated)
│   │
│   ├── verticals/              # Lógica vertical como plugins (NO está en core)
│   │   └── demo_farmacia/      # prompts.py, heuristics.py, golden/
│   │
│   └── scripts/                # eval_rag.py (legacy) + eval_engine.py (CLI engine)
│
├── tests/
│   ├── conftest.py             # Async fixtures (mock DB, Qdrant, Redis, LLM)
│   ├── test_architecture.py    # Guardas de dependencias entre capas
│   ├── test_security_hardening.py  # Organization isolation, RBAC, rate limits
│   ├── test_rag_query.py       # RAG query integration tests
│   └── test_billing.py         # Billing endpoint tests
│
├── portal/                     # Portal B2B (Vite + React) — UI organization
│   ├── src/                    # Signup, dashboard, usage, keys, ingestion, prompts, chat
│   ├── Dockerfile              # Multi-stage nginx static
│   └── nginx.conf              # Proxy /api → api:8000 + security headers/CSP
│
├── config/                     # Observability configuration files
│   ├── prometheus/prometheus.yml
│   ├── prometheus/alert-rules.yml
│   ├── loki/loki-config.yml
│   ├── promtail/promtail-config.yml
│   └── grafana/
│       ├── dashboards/rag-observability.json
│       └── datasources/datasources.yml
│
├── bruno/                      # Bruno API client collection (Postman alternative)
│   ├── Admin/
│   ├── Billing/
│   ├── Health/
│   ├── Ingestion/
│   ├── Prompt/                  # Prompt management requests
│   └── RAG/
│
├── docker-compose.yml          # Full stack: API + Postgres + Qdrant + Redis + Ollama + PLG
├── Dockerfile.api              # Multi-stage Python 3.11-slim build
├── pyproject.toml              # Python project + deps (uv/pip)
├── alembic.ini                 # Alembic migration config
├── .env.example                # Environment variables template
└── .gitignore
```

## Requisitos Previos

- **Docker** + Docker Compose v2
- ~6 GB de RAM libre (Ollama con bge-m3 usa ~2 GB)
- ~8 GB de espacio en disco (modelos + imágenes Docker)

## Quick Start

### 1. Clonar y configurar

```bash
git clone https://github.com/yoredstorm/zent_rag.git
cd zent_rag
cp .env.example .env
# Edita .env con tus API keys (LiteLLM, etc.)
```

### 2. Levantar el stack completo

```bash
# Construir y arrancar todos los servicios en segundo plano
docker compose up -d --build

# Verificar que todo esté healthy
docker compose ps
```

### 3. Descargar el modelo de embeddings

```bash
# El modelo bge-m3 no se incluye en la imagen, hay que descargarlo
docker exec rag-ollama ollama pull bge-m3
```

### 4. Acceder a los servicios

| Servicio | URL | Credenciales |
|---|---|---|
| **Portal B2B** | http://localhost:8080 | Signup trial / Bearer token |
| **API Docs (Swagger)** | http://localhost:8000/docs o http://localhost:8080/docs | API Key en header |
| **API Docs (ReDoc)** | http://localhost:8000/redoc o http://localhost:8080/redoc | API Key en header |
| **Grafana Dashboards** | http://localhost:3000 | admin / admin |
| **Prometheus** | http://localhost:9090 | Sin auth |
| **Loki** | http://localhost:3100 | Sin auth |
| **PostgreSQL** | localhost:5432 | rag_user / changeme_in_production |

Tras el signup, `client.chat()` contra el stack Docker:

```bash
pip install -e sdk/python
# default: http://localhost:8000/api/v1
```

```python
from zent import Zent

client = Zent(api_key="zent_sk_live_...")
print(client.chat("What is our refund policy?").answer)
```

Docs: [docs/developers/quickstart.md](docs/developers/quickstart.md). Volúmenes Postgres ya existentes aplican `alembic upgrade head` (revisión `012`) al arrancar `api`.

### 5. Flujo de uso típico

1. **Crear trial** → http://localhost:8080/signup (empresa → organization + API token)
2. **Sincronizar datos** → Portal → Ingestión → Sync All  
   (por defecto omite `sales`; embeddings cloud vía Novita. Si usas Ollama CPU, espera tiempos largos en BD masiva.)
3. **Consultas RAG** → Portal → Chat demo
4. **Ver cuota / rotar key** → Dashboard y API Keys

## Endpoints Principales

### Health & Metrics

```bash
GET  /health        # Health check (DB, Qdrant, Redis)
GET  /metrics       # Prometheus metrics
```

### RAG Query

```bash
POST /api/v1/rag/query
Headers:
  X-Organization-Id: <uuid>
  X-User-Id: <uuid>
  X-User-Role: admin|customer
Body:
{
  "query": "¿Cuántas ventas hubo en enero 2024?",
  "model": "openai/deepseek/deepseek-v3.2",  # optional
  "max_tokens": 2048,                         # optional
  "temperature": 0.3,                         # optional
  "top_k": 5,                                 # optional: chunks a recuperar
  "conversation_id": "<uuid>",                # optional: continuar conversación
  "role": "admin"                             # optional: override del header
}
```

### RAG Query Streaming (SSE)

Igual que `/rag/query` pero con respuesta token a token vía Server-Sent Events.
El portal usa este endpoint para el chat en vivo.

```bash
POST /api/v1/rag/query/stream   # mismo body y headers que /rag/query
Content-Type: text/event-stream

Eventos:
  event: status   data: {"phase": "searching"}          # fase del pipeline
  event: delta    data: {"text": "..."}                 # tokens de respuesta
  event: sources  data: {"sources": [...], "method": "rag|sql", "sql_query": null, "lazy_ingested": false}
  event: done     data: {"conversation_id": "...", "query_id": "...", "usage": {...}, "latency_ms": 123}
  event: error    data: {"message": "..."}
```

### Ingestion (SQL → Vectores)

```bash
GET  /api/v1/ingestion/sources                    # Listar tablas y columnas
POST /api/v1/ingestion/sync                       # Sync todas las tablas
POST /api/v1/ingestion/sync/{schema}.{table}       # Sync una tabla específica
```

**Ingesta perezosa (lazy ingestion):** cuando SQL Expert y la búsqueda vectorial no encuentran contexto suficiente, el orquestador puede buscar candidatos por texto plano (`ILIKE`) en PostgreSQL, embeber solo esas filas y reintentar Qdrant antes de responder "no tengo información". Es un complemento del sync completo (catálogos pequeños/estáticos), no un reemplazo. Queda **apagada por defecto**.

| Variable | Default | Descripción |
|---|---|---|
| `RAG_RAG_LAZY_INGESTION_ENABLED` | `false` | Activa el fallback de ingesta perezosa |
| `RAG_RAG_LAZY_INGEST_MAX_ROWS_PER_TABLE` | `25` | Máximo de filas candidatas a embeber por tabla |
| `RAG_RAG_LAZY_INGEST_MAX_TABLES` | `5` | Máximo de tablas a escanear por fallback |
| `RAG_RAG_LAZY_INGEST_TIMEOUT_SECONDS` | `4` | Timeout global del fallback (no cuelga la request RAG) |
| `RAG_RAG_LAZY_INGEST_PROMOTE_THRESHOLD` | `10` | Reservado (fase 2): triggers antes de promover a `sync_table` |

Las tablas de `RAG_INGEST_SKIP_TABLES` nunca se lazy-ingestan (siguen siendo SQL-only). El rol `customer` no indexa vistas agregadas (admin-only).

### Admin (Dev only)

```bash
GET    /api/v1/admin/tables                              # Listar todas las tablas
GET    /api/v1/admin/tables/{schema}.{table}              # Ver rows de una tabla
GET    /api/v1/admin/tables/{schema}.{table}/columns       # Ver columnas
POST   /api/v1/admin/tables/{schema}.{table}/rows         # Insertar rows
DELETE /api/v1/admin/tables/{schema}.{table}              # Eliminar tabla
POST   /api/v1/admin/sql                                  # Ejecutar SQL raw
```

### Prompt Management

Gestiona el system prompt del asistente RAG por organization y por rol (admin vs customer) sin redeploy. El endpoint de test usa el pipeline RAG real (vectores + SQL expert) para pruebas con datos reales.

```bash
GET    /api/v1/admin/prompt               # Ver prompts por rol (admin + customer)
PUT    /api/v1/admin/prompt               # Guardar prompt para un rol específico
DELETE /api/v1/admin/prompt?role=admin    # Resetear prompt de un rol (sin param = todos)
POST   /api/v1/admin/prompt/test          # Test con RAG real (embedding + vectores + LLM)
```

**Roles de prompt:**
| Clave en config_json | Rol | Propósito |
|---|---|---|
| `system_prompt_admin` | Admin | BI, métricas, ventas, datos sensibles |
| `system_prompt_customer` | Customer | Catálogo, precios, recomendaciones |
| `system_prompt` | Genérico | Fallback si no hay específico |

**PUT acepta `"role"` para guardar por rol:**
```json
{
  "role": "admin",
  "system_prompt": "Eres el asistente administrativo...",
  "custom_instructions": "Incluye fechas exactas en cada respuesta."
}
```

**POST /test ejecuta el pipeline RAG completo** (embedding → Qdrant → SQL expert → LLM) con el prompt dado, sin guardar cambios ni afectar el caché de conversación:
```json
{
  "query": "cuando fue la ultima venta",
  "role": "admin",
  "system_prompt": "...",
  "custom_instructions": "...",
  "top_k": 200,
  "temperature": 0.3
}
```

**Flujo de iteración típico:**
1. `GET /prompt` — ver estado actual por rol
2. `POST /prompt/test` — probar prompt candidato con datos reales
3. Repetir paso 2 ajustando hasta obtener el tono/precisión deseado
4. `PUT /prompt` con `"role": "admin"` o `"customer"` para guardar
5. `DELETE /prompt?role=admin` para resetear un rol específico

**Variables disponibles** en los prompts: `{role}`, `{organization_name}`, `{date}`, `{top_k}`.

### Auth (portal)

```bash
POST   /api/v1/auth/signup                                # Trial: company_name + email + password → rag_sess_ (AES-256-GCM)
POST   /api/v1/auth/login                                 # email + password → rag_sess_
GET    /api/v1/auth/me                                    # Perfil (Bearer rag_sess_ o rag_live_)
```

### Billing

```bash
GET    /api/v1/billing/plans                              # Listar planes disponibles
POST   /api/v1/billing/subscription/create-trial          # Crear organization trial (API/legacy; body: company_name)
GET    /api/v1/billing/subscription                       # Ver suscripción actual (Bearer)
POST   /api/v1/billing/subscription/upgrade               # Cambiar de plan (Bearer + X-New-Plan)
GET    /api/v1/billing/usage                              # Uso del organization (Bearer)
GET    /api/v1/billing/token                              # Listar API keys (Bearer)
POST   /api/v1/billing/token/rotate                       # Rotar API key (Bearer)
```

### Organización, proyectos y recursos (RBAC)

```bash
# Organización (identidad = Bearer; nunca body/header)
GET    /api/v1/organizations                              # Perfil
PUT    /api/v1/organizations                              # Actualizar (permiso org:write)
GET    /api/v1/organizations/members                      # Miembros + roles (users:read)
POST   /api/v1/organizations/members/{user_id}/role       # Asignar rol (users:write)
DELETE /api/v1/organizations/members/{user_id}            # Remover miembro (users:write)
GET    /api/v1/organizations/roles                        # Roles de sistema
GET    /api/v1/organizations/api-keys                     # Listar API keys (apikeys:read)
POST   /api/v1/organizations/api-keys                     # Crear key (apikeys:write)
DELETE /api/v1/organizations/api-keys/{key_id}            # Revocar key (apikeys:write)

# Recursos (todos organization-scoped; project_id opcional)
GET/POST        /api/v1/projects          # projects:read / projects:write
GET/PUT/DELETE  /api/v1/projects/{id}
GET/POST        /api/v1/knowledge-bases   # kbs:read / kbs:write (delete purga vectores org+kb)
GET/PUT/DELETE  /api/v1/knowledge-bases/{id}
GET/POST        /api/v1/agents            # agents:read / agents:write
GET/PUT/DELETE  /api/v1/agents/{id}
GET/POST        /api/v1/connectors        # connectors:read / connectors:write
GET/PUT/DELETE  /api/v1/connectors/{id}

# Auditoría (solo entradas de la organización autenticada)
GET    /api/v1/audit-logs                 # audit:read
```

### Knowledge Platform (fuentes + jobs de ingestion)

```bash
# Knowledge Bases con configuración de chunking/retrieval
POST   /api/v1/knowledge-bases            # chunking_strategy: fixed|recursive|sentence,
                                          # chunk_size, chunk_overlap, retrieval_strategy,
                                          # reranker, metadata_schema

# Fuentes (type: sql|file|csv|excel|web|s3|api)
GET    /api/v1/sources                    # Listar (filtro ?knowledge_base_id=)
POST   /api/v1/sources                    # Crear (name, type, config)
GET    /api/v1/sources/{id}               # Detalle
PUT    /api/v1/sources/{id}               # Actualizar config/status
DELETE /api/v1/sources/{id}               # Eliminar + purga de vectores/registry
POST   /api/v1/sources/{id}/discover      # Validar conector + listar elementos
POST   /api/v1/sources/{id}/sync          # Encela job (background)
POST   /api/v1/sources/files/upload       # multipart -> fuente file/csv/excel (autodetect)
GET    /api/v1/knowledge-bases/{kb_id}/sources   # Fuentes de una KB

# Jobs durables (Postgres = source of truth; Redis = wakeup)
GET    /api/v1/jobs                       # ?status=&source_id=&knowledge_base_id=
GET    /api/v1/jobs/{id}                  # Estado (progress, records_processed/failed, attempts)
POST   /api/v1/jobs/{id}/retry            # Reintentar failed/dead
POST   /api/v1/jobs/{id}/cancel           # Cancelar
```

**Flujo de ingestion** (sin acoplar al dominio):
1. Cada fuente implementa `SourceConnector` (`connect/validate/discover/fetch/sync`).
2. Documentos (pdf/docx/html/txt/md) se normalizan a **Markdown** (markitdown, MIT) antes de chunkear.
3. El engine aplica la estrategia de chunking del KB (`fixed`, `recursive` markdown-aware — tablas atómicas, `sentence`), embebe en batch y escribe en Qdrant con payload `organization_id + knowledge_base_id + source_id`.
4. `source_documents` (registry) habilita **update detection** (diff de content_hash) y **delete detection** (vectores huérfanos se borran por ID).
5. **Retry** con backoff exponencial, **resume** vía `cursor_snapshot` y **dead letter** (`ingestion_jobs.status='dead'` + historial en `ingestion_job_errors`).
6. El conector `sql` reutiliza el motor SQL existente (self-contained); los endpoints legacy `/api/v1/ingestion/*` siguen operativos.

**Conectores:** `sql` (port del motor existente), `file`/`csv`/`excel` (uploads locales, volumen `uploads_data`), `web` (URL → HTML → MD), `s3` (boto3, extensión-config), `api` (config-driven con paginación page/offset/cursor). Credenciales en Vault (nunca en `config_json`).

## ZENT Evaluation Engine

Framework de evaluación de RAG y Agents con detección de regresión entre
versiones. Responde: **"¿La versión nueva de Zent realmente es mejor que la anterior?"**

### Dataset (schema v2)

Cada caso soporta `question`, `expected_answer`, `expected_sources` y `metadata`.
Los golden sets v1 (`query`, `expected_keywords`, `relevant_chunks`) se aceptan
como fallback y se normalizan automáticamente.

```json
[
  {
    "id": "farmacia-001",
    "question": "¿Cuáles son los analgésicos más vendidos y cuánto cuestan?",
    "expected_answer": "Paracetamol e ibuprofeno, con precios desde $4.990.",
    "expected_sources": ["paracetamol", "ibuprofeno"],
    "metadata": {"role": "admin", "top_k": 20, "category": "catalogo",
                 "difficulty": "easy", "target": "rag"}
  }
]
```

Golden sets: `src/verticals/demo_farmacia/golden/rag_farmacia.json` y
`tests/golden/rag_retail.json`.

### Métricas

- **Deterministas (sin costo de LLM):** `retrieval_precision`, `retrieval_recall`,
  `citation_accuracy` (citas `[Doc: N]` verificadas contra contexto).
- **LLM-judge (LiteLLM, modelo configurable `RAG_EVAL_JUDGE_MODEL`):**
  `context_relevance`, `answer_relevance`, `faithfulness`, `hallucination_rate`.
  Desactivable con `RAG_EVAL_JUDGE_ENABLED=false` o `--no-judge`.
- **Performance:** latencia (total/retrieval/LLM, avg/p50/p95), tokens, costo
  (vía `platform.billing.pricing`).
- **Score compuesto** ponderado (pesos configurables por dataset); se
  renormaliza si una componente no está disponible.

### Versiones

Cada run captura un `version_snapshot` (prompt + hash, model, embedding,
chunking, retriever, reranker, git commit) y deriva un `version_id` estable.
Dos runs con distinto `version_id` = versiones distintas.

### Flujo en Docker

```bash
# Importar el golden set (schema v2)
docker compose exec api python src/scripts/eval_engine.py \
  import-dataset --golden src/verticals/demo_farmacia/golden/rag_farmacia.json

# Ejecutar evaluación (RAG pipeline; judge on si hay API key LLM)
docker compose exec api python src/scripts/eval_engine.py \
  run --dataset-id <uuid> --target rag

# Ejecutar contra un agente configurado
docker compose exec api python src/scripts/eval_engine.py \
  run --dataset-id <uuid> --target agent --agent-id <uuid>

# Listar runs / ver detalle
docker compose exec api python src/scripts/eval_engine.py list
docker compose exec api python src/scripts/eval_engine.py show --run-id <uuid>

# Regresión: comparar versión nueva vs anterior (exit 1 si regresa)
docker compose exec api python src/scripts/eval_engine.py \
  compare --baseline <run-antiguo> --current <run-nuevo>
```

La comparación alerta (warn/fail) cuando la calidad baja (`composite_score`,
`faithfulness`, `hallucination_rate`), el costo sube o la latencia p95 sube.
Umbrales configurables vía `RAG_EVAL_REGRESSION_*` (ver `.env.example`).

### API REST (admin de organización)

```bash
POST /api/v1/eval/datasets/import        # {name, cases, weights?, metadata?}
GET  /api/v1/eval/datasets
POST /api/v1/eval/runs                   # {dataset_id, target_type: rag|agent, target_id?, judge_enabled}
GET  /api/v1/eval/runs
GET  /api/v1/eval/runs/{run_id}          # detalle con casos
POST /api/v1/eval/runs/{run_id}/compare  # {baseline_run_id} → reporte de regresión
```

Persistencia: tablas `eval_datasets`, `eval_runs` y `eval_case_results`
(migración Alembic `011`). Los endpoints legacy `/api/v1/eval/feedback`,
`/stats`, `/recent` y `/run` siguen operativos.

## MCP Server

Zent expone sus capacidades vía **Model Context Protocol** (Streamable HTTP,
stateless) montado en la misma API bajo `/mcp` — los middlewares de
autenticación, cuota y rate limits aplican igual que en REST (sin bypass).

```bash
# URL MCP: http://localhost:8000/mcp
# Header en cada request: Authorization: Bearer zent_sk_live_...
```

| Tool | Permiso RBAC | Descripción |
|---|---|---|
| `search_knowledge` | `rag:read` | Búsqueda semántica en la KB del tenant |
| `query_database` | `rag:read` | NL → SQL read-only validado (SQL solo visible a admin) |
| `get_document` | `rag:read` | Chunks por `document_id` (aislamiento de tenant estricto) |
| `execute_agent` | `agents:execute` | Ejecuta un agente (ReAct, allowlist, guardrails, quotas) |
| `get_usage` | `usage:read` | Agregados de uso (requests, tokens, costo) |

- **Política por org** en `config_json["mcp"]`: habilitar/deshabilitar MCP o
  por tool, `min_role`, `rpm` (rate limit por tool vía Redis).
- **Auditoría**: cada tool call escribe `audit_logs` con `mcp_client`, tool,
  tenant, user, cost y resultado; el consumo se registra en la Usage Engine.
- Docs: [docs/developers/mcp.md](docs/developers/mcp.md). Config:
  `RAG_RAG_MCP_ENABLED`, `RAG_RAG_MCP_ALLOWED_HOSTS`, `RAG_RAG_MCP_DEFAULT_RPM`.

## Variables de Entorno

Todas las variables usan el prefijo `RAG_` (configurado en `src/config.py` con `pydantic-settings`). Variables principales:

| Variable | Default | Descripción |
|---|---|---|
| `RAG_ENVIRONMENT` | `development` | Entorno (development/production) |
| `RAG_POSTGRES_HOST` | `localhost` | Host de PostgreSQL |
| `RAG_POSTGRES_USER` | `rag_user` | Usuario PostgreSQL |
| `RAG_QDRANT_HOST` | `localhost` | Host de Qdrant |
| `RAG_REDIS_URL` | `redis://localhost:6379/0` | URL de Redis |
| `RAG_LITELLM_API_BASE` | — | API base del LLM (OpenAI, Novita, Ollama...) |
| `RAG_LITELLM_API_KEY` | — | API key del proveedor LLM |
| `RAG_LITELLM_DEFAULT_MODEL` | `gpt-4o-mini` | Modelo LLM por defecto |
| `RAG_EMBEDDING_MODEL` | `openai/baai/bge-m3` | Embeddings (Novita cloud). Usa `ollama/bge-m3` solo en local CPU |
| `RAG_VECTOR_DIMENSION` | `1024` | Dimensiones del vector (debe coincidir con el modelo) |
| `RAG_INGEST_SKIP_TABLES` | `sales,product_reviews` | Tablas omitidas en Sync All (comma-separated) |
| `RAG_INGEST_MAX_ROWS_PER_TABLE` | `0` | Tope de filas/tabla (0 = sin tope) |
| `RAG_INGEST_EMBED_CONCURRENCY` | `8` | Batches de embed en paralelo (forzado a 1 si Ollama) |
| `RAG_INGEST_TABLE_CONCURRENCY` | `3` | Tablas en paralelo (forzado a 1 si Ollama) |
| `RAG_INGEST_UPSERT_BATCH_SIZE` | `200` | Vectors por upsert a Qdrant |
| `RAG_PORTAL_SESSION_KEY` | (dev default) | Clave AES-256 (32 bytes hex/base64) para `rag_sess_` |
| `RAG_AUTH_LOGIN_MAX_ATTEMPTS` | `5` | Fallos de login antes de 429 |
| `RAG_RAG_TOP_K` | `5` | Chunks a recuperar en búsqueda vectorial |
| `RAG_RAG_MAX_CONTEXT_TOKENS` | `32000` | Tokens máximos en el contexto ensamblado |
| `RAG_RAG_SQL_EXPERT_ENABLED` | `false` | Activar módulo Text-to-SQL |
| `RAG_RAG_LAZY_INGESTION_ENABLED` | `false` | Fallback de ingesta perezosa si no hay SQL ni vectores |
| `RAG_RAG_LAZY_INGEST_MAX_ROWS_PER_TABLE` | `25` | Filas candidatas por tabla en lazy ingest |
| `RAG_RAG_LAZY_INGEST_MAX_TABLES` | `5` | Tablas máximas escaneadas en lazy ingest |
| `RAG_RAG_LAZY_INGEST_TIMEOUT_SECONDS` | `4` | Timeout del fallback lazy (segundos) |
| `RAG_EVAL_JUDGE_ENABLED` | `true` | Activa el LLM-judge de métricas de calidad |
| `RAG_EVAL_JUDGE_MODEL` | `gpt-4o-mini` | Modelo del juez de evaluación |
| `RAG_EVAL_REGRESSION_QUALITY_MIN_DELTA` | `-0.05` | Delta mínimo de score compuesto antes de marcar regresión |

## Comandos Útiles

```bash
# Ver logs de la API
docker compose logs -f api

# Ver logs de un servicio específico
docker compose logs -f ollama

# Reconstruir y reiniciar solo la API tras cambios de código
docker compose up -d --build api

# Reiniciar toda la stack
docker compose down && docker compose up -d --build

# Ejecutar tests localmente
pip install -e ".[dev]"
pytest tests/ -v

# Lint & type check
ruff check src/
mypy src/
```

## Diseño

- **Clean Architecture**: Separación estricta entre API → Application → Domain → Infrastructure. El dominio no depende de ningún framework ni librería externa.
- **Circuit Breaker**: Protege las llamadas a LLM y embeddings con un patrón fail-fast. Tras 3 fallos consecutivos, abre el circuito y rechaza llamadas durante 30s.
- **Multi-tenant con aislamiento estricto**: colección Qdrant única compartida (`rag_documents`) con filtro obligatorio por `organization_id` en cada búsqueda/upsert; SQL Expert inyecta `organization_id` en tablas organization-aware; Redis keys, jobs de ingestion y audit logs namespaced por organización.
- **Conversation History**: Las conversaciones se cachean en Redis con TTL configurable. El contexto incluye el historial de la sesión.
- **SQL Expert**: Módulo opcional que convierte preguntas en lenguaje natural a SQL, ejecuta contra PostgreSQL y añade los resultados al contexto del LLM.

## Seguridad Multi-Tenant (cross-tenant leakage prevention)

1. **La identidad manda**: el tenant se deriva EXCLUSIVAMENTE del Bearer validado
   (hash SHA-256 de la API key en `api_keys`, o sesión portal AES-256-GCM).
2. **Nunca se confía en headers/body**: `X-Organization-Id`, `X-User-Id`,
   `X-User-Role` y `organization_id` del body no definen la identidad; si
   difieren del contexto autenticado → **403** (validado centralmente en
   `TenantMiddleware`, src/api/tenant_middleware.py).
3. **TenantContext** (`tenant_id`, `user_id`, `roles`, `permissions`) se
   propaga vía `request.state` + ContextVar a API, RAG, Vector Store, SQL,
   Connectors, Usage, Billing y Audit (`src/platform/tenants/context.py`).
4. **RBAC**: `memberships(org, user, role) → roles → role_permissions →
   permissions`. Roles de sistema: `owner`, `admin`, `member`, `viewer`.
   Política en `src/platform/rbac/policy.py` (`require_permission(...)`).
5. **404 (no 403)** al acceder por ID a recursos de otra organización: no se
   revela ni la existencia del recurso.
6. **Auditoría**: toda acción sensible (projects, kbs, agents, connectors,
   api keys, roles) escribe en `audit_logs` con la organización del contexto
   autenticado; cada organización solo lee sus propias entradas.
7. **Tests de aislamiento**: `tests/test_tenant_isolation.py` demuestra con
   dos organizaciones reales (A y B) que A no puede leer, modificar ni
   vector-search datos de B; incluye integración real con Qdrant.

## Licencia

Proprietary. Todos los derechos reservados.
