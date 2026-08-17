# RAG-as-a-Service Platform

AI Agent Orchestration con Retrieval-Augmented Generation (RAG) multi-tenant, full observability y facturación integrada.

## Stack Tecnológico

| Capa | Tecnología | Rol |
|---|---|---|
| **API Gateway** | FastAPI (Python 3.11) | REST API, validación Pydantic, Swagger/ReDoc autodocumentado |
| **BD Relacional** | PostgreSQL 16 + pgvector | Tenants, usuarios, billing, schemas de datos de dominio |
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
│  API Layer (FastAPI)                                            │
│  ├── /health          Health check                              │
│  ├── /metrics         Prometheus metrics                        │
│  ├── /api/v1/rag/*    RAG Query endpoint                        │
│  ├── /api/v1/ingestion/*  Data ingestion (SQL → Vector DB)     │
│  ├── /api/v1/admin/*  Dynamic table management (dev only)       │
│  ├── /api/v1/billing/*  Subscription & API key management       │
│  └── /docs            Swagger UI auto-generated                 │
├─────────────────────────────────────────────────────────────────┤
│  Application Layer (Use Cases)                                  │
│  └── RAGOrchestrator: embedding → search → assemble → generate │
├─────────────────────────────────────────────────────────────────┤
│  Domain Layer (Entities & Ports)                                │
│  ├── LLMProvider, EmbeddingProvider, VectorStore, CacheProvider │
│  └── LLMResponse, RAGQueryResult, RetrievalContext              │
├─────────────────────────────────────────────────────────────────┤
│  Infrastructure Layer (Adapters)                                │
│  ├── LiteLLMProvider      LLM + Embeddings via LiteLLM          │
│  ├── QdrantVectorStore    Vector DB CRUD + semantic search      │
│  ├── PostgresRepositories Tenants, users, billing, SQL data     │
│  ├── RedisCache           Rate limiting & conversation cache    │
│  ├── CircuitBreaker       Fail-fast protection for LLM calls    │
│  └── DataIngestion        SQL rows → embeddings → Qdrant       │
├─────────────────────────────────────────────────────────────────┤
│  Observability Stack (PLG)                                      │
│  ├── Prometheus   Metrics scraping from /metrics                │
│  ├── Loki         Centralized structured JSON logs              │
│  ├── Promtail     Log tailing agent for Docker containers       │
│  └── Grafana      Pre-configured dashboards (health, billing)   │
└─────────────────────────────────────────────────────────────────┘
```

## Flujo RAG (Query → Response)

```
1. POST /api/v1/rag/query  { query, tenant_id, user_id, model? }
│
2. Resolver tenant + validar API Key / rate limit
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
│   ├── api/                    # FastAPI REST Layer
│   │   ├── main.py             # App factory, middleware, routers, lifespan
│   │   ├── deps.py             # Dependency injection (Clean Architecture)
│   │   ├── metrics.py          # Prometheus metric definitions
│   │   ├── middleware.py       # Trace ID injection, structured logging
│   │   ├── billing_middleware.py  # Tenant/user resolution from Bearer token
│   │   └── routes/
│   │       ├── query.py        # POST /api/v1/rag/query
│   │       ├── ingestion.py    # POST /api/v1/ingestion/sync
│   │       ├── admin.py        # GET/POST/DELETE /api/v1/admin/*
│   │       ├── billing.py      # GET/POST /api/v1/billing/*
│   │       └── health.py       # GET /health, GET /metrics
│   │
│   ├── application/            # Use Cases / Orchestrators
│   │   └── orchestrator.py     # RAG query execution flow
│   │
│   ├── domain/                 # Pure domain logic (no external deps)
│   │   ├── entities.py         # LLMResponse, RAGQueryResult, etc.
│   │   ├── models.py           # Pydantic request/response models
│   │   ├── ports.py            # ABC interfaces (LLMProvider, VectorStore, etc.)
│   │   ├── services.py         # Domain services (rate limiting, context assembly)
│   │   └── sql_expert.py       # Natural Language → SQL (Text-to-SQL)
│   │
│   ├── infrastructure/         # External adapters (DB, Cache, LLM, Qdrant)
│   │   ├── llm_provider.py     # LiteLLM unified adapter (LLM + Embeddings)
│   │   ├── vector_store.py     # Qdrant vector store adapter
│   │   ├── relational_db.py    # PostgreSQL async repositories
│   │   ├── cache.py            # Redis cache provider
│   │   ├── data_ingestion.py   # SQL → Embeddings → Qdrant pipeline
│   │   ├── circuit_breaker.py  # Fail-fast pattern for LLM/embedding calls
│   │   ├── billing_service.py  # Billing/subscription domain
│   │   ├── sql_expert.py       # SQL schema introspection + query execution
│   │   ├── logging_config.py   # Structlog JSON configuration
│   │   └── db_init/            # SQL init schemas & Alembic migrations
│   │       ├── 01-init-schema.sql
│   │       ├── 02-seed-retail.sql
│   │       ├── 03-billing.sql
│   │       ├── 04-tenant-fields.sql
│   │       └── versions/001_initial.py
│   │
│   └── config.py               # Typed settings via pydantic-settings (prefix RAG_)
│
├── tests/
│   ├── conftest.py             # Async fixtures (mock DB, Qdrant, Redis, LLM)
│   ├── test_rag_query.py       # RAG query integration tests
│   └── test_billing.py         # Billing endpoint tests
│
├── portal/                     # Portal B2B (Vite + React) — UI tenant
│   ├── src/                    # Signup, dashboard, usage, keys, ingestion, prompts, chat
│   ├── Dockerfile              # Multi-stage nginx static
│   └── nginx.conf              # Proxy /api → api:8000
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
| **API Docs (Swagger)** | http://localhost:8000/docs | API Key en header |
| **API Docs (ReDoc)** | http://localhost:8000/redoc | API Key en header |
| **Grafana Dashboards** | http://localhost:3000 | admin / admin |
| **Prometheus** | http://localhost:9090 | Sin auth |
| **Loki** | http://localhost:3100 | Sin auth |
| **PostgreSQL** | localhost:5432 | rag_user / changeme_in_production |

### 5. Flujo de uso típico

1. **Crear trial** → http://localhost:8080/signup (empresa → tenant + API token)
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
  X-Tenant-Id: <uuid>
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

Gestiona el system prompt del asistente RAG por tenant y por rol (admin vs customer) sin redeploy. El endpoint de test usa el pipeline RAG real (vectores + SQL expert) para pruebas con datos reales.

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

**Variables disponibles** en los prompts: `{role}`, `{tenant_name}`, `{date}`, `{top_k}`.

### Auth (portal)

```bash
POST   /api/v1/auth/signup                                # Trial: company_name + email + password → rag_sess_ (AES-256-GCM)
POST   /api/v1/auth/login                                 # email + password → rag_sess_
GET    /api/v1/auth/me                                    # Perfil (Bearer rag_sess_ o rag_live_)
```

### Billing

```bash
GET    /api/v1/billing/plans                              # Listar planes disponibles
POST   /api/v1/billing/subscription/create-trial          # Crear tenant trial (API/legacy; body: company_name)
GET    /api/v1/billing/subscription                       # Ver suscripción actual (Bearer)
POST   /api/v1/billing/subscription/upgrade               # Cambiar de plan (Bearer + X-New-Plan)
GET    /api/v1/billing/usage                              # Uso del tenant (Bearer)
GET    /api/v1/billing/token                              # Info API key (Bearer)
POST   /api/v1/billing/token/rotate                       # Rotar API key (Bearer)
```

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
- **Multi-tenant**: Cada tenant tiene su propio collection en Qdrant, su API key, y su propio system prompt personalizable (vía `config_json`). Rate limiting por tenant.
- **Conversation History**: Las conversaciones se cachean en Redis con TTL configurable. El contexto incluye el historial de la sesión.
- **SQL Expert**: Módulo opcional que convierte preguntas en lenguaje natural a SQL, ejecuta contra PostgreSQL y añade los resultados al contexto del LLM.

## Licencia

Proprietary. Todos los derechos reservados.
