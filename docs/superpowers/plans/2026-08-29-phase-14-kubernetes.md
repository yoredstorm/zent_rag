# Fase 14 — Kubernetes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> Índice: [`docs/platform/ZENT_PLATFORM_ROADMAP.md`](../../platform/ZENT_PLATFORM_ROADMAP.md)

**Goal:** Definir (y solo entonces aplicar) manifests Kubernetes **cuando** Compose + managed services (Fase 11) no basten. Esta fase es **opcional**. No usar K8s para marketing.

**Architecture:** API Deployment + ingestion-worker Deployment + Service/Ingress. Stateful sets **no** para PG/Qdrant/Redis si siguen managed. Secrets vía Secret / External Secrets. Misma imagen que `Dockerfile.api`.

**Tech Stack:** Kubernetes, Helm o Kustomize (elegir **uno**), existing Dockerfiles.

## Global Constraints

- No migrar PG/Qdrant/Redis a pods salvo que PRODUCTION.md lo exija (default: **managed**).
- Identidad y API sin cambios.
- No romper docker-compose demo.
- Tests: no se requiere cluster en CI en v1 (kubeconform / kustomize build). Lint Python intacto.
- Si el producto aún no tiene carga multi-nodo, **el entregable puede ser solo docs + manifests no desplegados** — pero deben ser válidos.

## Protocolo del agente (obligatorio)

1. Inspect existing architecture
2. Do not rewrite working functionality
3. Identify existing components
4. Design changes
5. Implement
6. Add migrations — N/A
7. Add tests (manifest validation)
8. Update API — N/A
9. Update frontend — N/A
10. Update documentation
11. Run tests
12. Run lint
13. Check backwards compatibility
14. Report files changed
15. Report remaining risks

---

## Exists / Reuse

- Fase 11 `docs/platform/PRODUCTION.md`.
- Dockerfiles API/portal/worker.
- Health `/health`, métricas `/metrics`.
- HPA solo si hay métricas CPU/RPS reales.

## Criterio para **empezar** esta fase

Documentar en el PR: síntoma (CPU API, cola ingestion, RTO). Si no hay síntoma, el agente **no** inventa un cluster; entrega Kustomize + README “cuando escalar”.

---

### Task 1: Manifests

- Create: `deploy/k8s/` (Deployment api, worker, portal; Ingress TLS; NetworkPolicy básica).
- [ ] **Step 1:** `kustomize build` o `helm template` en CI (job nuevo, sin kube).
- [ ] **Step 2:** Recursos: probes en `/health`; no privilege; read-only root fs si es viable.
- [ ] **Step 3:** Workers: una replica de ingestion-worker primero; HPA después.

---

### Task 2: Docs

- Create: `docs/platform/KUBERNETES.md` — cuándo sí / cuándo no; cómo se relaciona con Compose.
- Actualizar roadmap README: K8s no es requisito de venta.

```bash
ruff check src/ tests/ sdk/python
# plus: kustomize build deploy/k8s
```

Expected: PASS / manifests render

## Criterios de aceptación

- Manifests renderizan.
- Demo Compose intacta.
- No hay PG en el cluster por defecto.

## Riesgos residuales

- Drift Compose vs K8s env vars.
- Qdrant en cluster vs managed: backups (Fase 11) siguen siendo el riesgo #1.
- Coste de cluster > beneficio en < N customers — documentar umbral cualitativo.
