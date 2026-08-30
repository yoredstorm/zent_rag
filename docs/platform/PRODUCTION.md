# Producción (sin Kubernetes por defecto)

Camino inicial: **Cloudflare → VM o load balancer → API + workers**. Postgres, Redis, Qdrant y object storage **managed**. Compose de demo (`docker-compose.yml`) no se reemplaza; para prod usar `docker-compose.prod.yml` (sin Ollama).

Kubernetes es **opcional** y **no es requisito de venta**. Solo si Compose + managed ya no bastan: [`KUBERNETES.md`](KUBERNETES.md).

## Checklist

1. `RAG_ENVIRONMENT=production`
2. Secretos solo en el host / secret manager. Nunca commitear valores. Nombres en `.env.example`.
3. `RAG_CORS_ALLOWED_ORIGINS` orígenes `https` explícitos (`*` rechazado al boot).
4. `RAG_PORTAL_SESSION_KEY` = `openssl rand -hex 32` (no el default de desarrollo).
5. `RAG_LITELLM_API_BASE` + `RAG_LITELLM_API_KEY` (embeddings hosted, no Ollama).
6. `RAG_ADMIN_ENABLED=false`, `RAG_SEED_DEMO_DATA=false`.
7. `RAG_METRICS_TOKEN` para scrape de `/metrics` (sigue gated: token o loopback).
8. Cloudflare: TLS, WAF, no exponer Postgres/Redis/Qdrant a Internet.

## Compose prod

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

Bind de puertos solo a `127.0.0.1`. Pon Cloudflare o un reverse proxy delante.

Para Postgres/Redis/Qdrant managed, apunta `RAG_POSTGRES_HOST`, `RAG_REDIS_URL`, `RAG_QDRANT_HOST` a esos endpoints (pgvector en PG).

## Object storage

Los `file` sources no deben vivir solo en el disco del contenedor API. Usa un bucket S3-compatible (conector `s3` / `RAG_UPLOAD_DIR` montado a un FS persistente solo como último recurso).

## Observabilidad

- `/metrics`: Prometheus con `METRICS_TOKEN`.
- Alertas: `config/prometheus/alert-rules.yml`. Cablear Alertmanager managed o documentar el webhook del operador; no hay Alertmanager en `docker-compose.prod.yml`.
- Tracing: `RAG_TRACING_ENABLED=true` + OTLP del vendor (`TRACING_*` en Settings).

## Demo local

Sigue siendo `docker compose up` + README. No uses `docker-compose.prod.yml` para el vertical demo.
