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
| **Embeddings** | Ollama (bge-m3) | Embeddings locales de 1024 dimensiones |
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
3. Generar embedding de la pregunta (LiteLLM → Ollama bge-m3)
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
├── web-tester/                 # Dev-only single-page web UI
│   ├── index.html              # Dashboard, DB Explorer, Chat RAG, API console
│   └── Dockerfile
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
| **Web Tester** | http://localhost:8080 | Dev-only, sin auth |
| **API Docs (Swagger)** | http://localhost:8000/docs | API Key en header |
| **API Docs (ReDoc)** | http://localhost:8000/redoc | API Key en header |
| **Grafana Dashboards** | http://localhost:3000 | admin / admin |
| **Prometheus** | http://localhost:9090 | Sin auth |
| **Loki** | http://localhost:3100 | Sin auth |
| **PostgreSQL** | localhost:5432 | rag_user / changeme_in_production |

### 5. Flujo de uso típico

1. **Crear tenant y API key** → `POST /api/v1/billing/create-trial` o usa el endpoint de billing en la web-tester
2. **Sincronizar datos** → En la web-tester: pestaña "Ingestion" → "Sync All" (convierte filas SQL en vectores en Qdrant)
3. **Hacer consultas RAG** → En la web-tester: pestaña "Chat RAG" → escribe tu pregunta

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

Gestiona el system prompt del asistente RAG por tenant sin redeploy. Ideal para iterar con el cliente hasta afinar el tono, dominio y comportamiento.

```bash
GET    /api/v1/admin/prompt         # Ver prompt actual + default + variables disponibles
PUT    /api/v1/admin/prompt         # Actualizar system_prompt y/o custom_instructions
DELETE /api/v1/admin/prompt         # Resetear al prompt por defecto
POST   /api/v1/admin/prompt/test    # Probar un prompt con una query (dry-run, no guarda)
```

**Flujo de iteración típico:**
1. `GET /prompt` para ver el prompt actual y el default
2. `POST /prompt/test` con un prompt candidato + query de prueba → evaluar respuesta
3. Repetir paso 2 ajustando hasta obtener el tono deseado
4. `PUT /prompt` para guardar la versión final
5. `DELETE /prompt` para volver al default si algo sale mal

**Variables disponibles** en los prompts: `{role}`, `{tenant_name}`, `{date}`, `{top_k}`.

### Billing

```bash
GET    /api/v1/billing/plans                       # Listar planes disponibles
POST   /api/v1/billing/create-trial                # Crear tenant trial
GET    /api/v1/billing/subscription                # Ver suscripción actual
POST   /api/v1/billing/upgrade                     # Cambiar de plan
GET    /api/v1/billing/token                       # Obtener/ver API key
POST   /api/v1/billing/rotate-token                # Rotar API key
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
| `RAG_EMBEDDING_MODEL` | `text-embedding-3-small` | Modelo de embeddings |
| `RAG_VECTOR_DIMENSION` | `1536` | Dimensiones del vector de embedding |
| `RAG_RAG_TOP_K` | `5` | Chunks a recuperar en búsqueda vectorial |
| `RAG_RAG_MAX_CONTEXT_TOKENS` | `32000` | Tokens máximos en el contexto ensamblado |
| `RAG_RAG_SQL_EXPERT_ENABLED` | `false` | Activar módulo Text-to-SQL |

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
