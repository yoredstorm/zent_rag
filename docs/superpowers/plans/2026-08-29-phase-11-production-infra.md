# Fase 11 — Production Infrastructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> Índice: [`docs/platform/ZENT_PLATFORM_ROADMAP.md`](../../platform/ZENT_PLATFORM_ROADMAP.md)

**Goal:** Dejar un camino de producción **inicial**: Docker (o el Compose actual) + servicios managed (Postgres, Redis, Qdrant, object storage), Cloudflare delante, backups y DR documentados. **No Kubernetes.**

**Architecture:**

```
Internet → Cloudflare → Load balancer / single VM
    → API + Workers
    → managed PG + Redis + Qdrant + object storage
```

Compose sigue siendo el MVP/demo. Esta fase añade `docs/platform/PRODUCTION.md`, perfiles Compose `docker-compose.prod.yml` (sin Ollama local si embeddings van a API), backups, y checklist. Código solo donde haga falta (health, `ENVIRONMENT=production` checks que ya existen).

**Tech Stack:** Docker, Cloudflare (doc), Alembic, existing PLG stack (opcional managed Grafana).

## Global Constraints

- No introducir K8s manifests en esta fase.
- Identidad / API sin cambios funcionales salvo config.
- No bajar Compose de desarrollo.
- Secrets solo env / secret manager; actualizar `.env.example` con nombres, no valores.
- Copy docs en español o inglés consistente con `docs/developers`.

## Protocolo del agente (obligatorio)

1. Inspect existing architecture
2. Do not rewrite working functionality
3. Identify existing components
4. Design changes
5. Implement
6. Add migrations — N/A salvo flags
7. Add tests (config validation)
8. Update API — N/A
9. Update frontend — nginx headers si Fase 07 no los cerró
10. Update documentation
11. Run tests
12. Run lint
13. Check backwards compatibility
14. Report files changed
15. Report remaining risks

---

## Exists / Reuse

- [`docker-compose.yml`](../../../docker-compose.yml), `Dockerfile.api`, `portal/Dockerfile`, `worker_entry.py`.
- Health: `GET /health`.
- Production CORS guard en settings.
- CI ya levanta PG/Qdrant/Redis.
- README quickstart.

## Gaps

- No hay compose prod, backup/restore, RPO/RTO, object storage para archivos de ingestión (hoy filesystem/S3 connector).
- Alertmanager citado en README y no cableado.

---

### Task 1: Compose / deploy profile

- [ ] **Step 1: Inspeccionar** servicios y env vars obligatorias en `config.py`.
- [ ] **Step 2: Crear** `docker-compose.prod.yml` que **no** incluya Ollama si `LITELLM_*` apunta a remoto; no commitear passwords.
- [ ] **Step 3: Documentar** managed PG (pgvector), Redis, Qdrant cloud, S3-compatible para blobs.

---

### Task 2: Backups y DR

- Create: `docs/platform/BACKUPS.md`, `docs/platform/DISASTER_RECOVERY.md`
- [ ] **Step 1:** Postgres: pg_dump cadence, Qdrant snapshot, Redis AOF/opcional “cache puede perderse”.
- [ ] **Step 2:** Restore drill checklist (pasos, no “hacer backups”).
- [ ] **Step 3:** Object storage: documentos de `file` sources no pueden vivir solo en disco del contenedor API.

---

### Task 3: Observability prod

- [ ] **Step 1:** Cablear o documentar Alertmanager (`config/prometheus/alert-rules.yml` ya existe).
- [ ] **Step 2:** Tracing: cómo encender `TRACING_ENABLED` hacia OTLP managed.
- [ ] **Step 3:** `/metrics` sigue gated (token/loopback).

Tests: `tests/test_architecture.py` + un test de que `ENVIRONMENT=production` + `CORS_ALLOWED_ORIGINS=*` falla al cargar settings (si aún no existe, añadirlo).

```bash
ruff check src/ tests/ sdk/python
pytest tests/test_architecture.py -q
```

Expected: PASS

## Criterios de aceptación

- Un operador puede desplegar sin K8s siguiendo `PRODUCTION.md`.
- Demo local Compose **sigue** documentada.
- RPO/RTO escritos (aunque sean “best effort”).

## Fuera de alcance

Kubernetes (Fase 14), multi-region, BYOC vector DB.

## Riesgos residuales

- Qdrant snapshot vs PG desfasados: documentar orden de restore.
- Ollama vs embeddings hosted: latencia/coste (FinOps 08).
