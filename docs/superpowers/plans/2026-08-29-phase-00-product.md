# Fase 00 — Product Definition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> Índice: [`docs/platform/ZENT_PLATFORM_ROADMAP.md`](../../platform/ZENT_PLATFORM_ROADMAP.md)

**Goal:** Congelar posicionamiento, glosario, información de arquitectura de los dos productos y el outline de presentación, sin escribir features de aplicación.

**Architecture:** Zent ya es RAG-as-a-Service en el README. Esta fase solo produce documentos de producto en `docs/platform/` que las fases 01–14 deben respetar. Cero cambios en `src/`, `portal/` (salvo un enlace en README si aún no existe).

**Tech Stack:** Markdown en `docs/platform/`. No hay runtime.

## Global Constraints

- No reescribir funcionalidad que ya funciona.
- Identidad de tenant solo del Bearer; nunca `X-Organization-Id` ni `organization_id` del body.
- API pública permanece `1.0.0` (additive only).
- `core/` no importa `infrastructure` ni FastAPI.
- Copy del portal en español.
- Tests: `pytest`. Lint: `ruff check src/ tests/ sdk/python`.
- Migraciones Alembic: siguiente id `013+` (esta fase no migra).
- `PAYMENT_PROVIDER=manual` sigue siendo el default.
- No introducir Kubernetes, SSO, Stripe ni widgets en esta fase.
- No tocar código de producto.

## Protocolo del agente (obligatorio)

1. Inspect existing architecture
2. Do not rewrite working functionality
3. Identify existing components
4. Design changes
5. Implement (solo docs)
6. Add migrations — N/A
7. Add tests — N/A salvo que se añada un test de docs (no hace falta)
8. Update API — N/A
9. Update frontend — N/A
10. Update documentation
11. Run tests — no deben romperse (no se toca código)
12. Run lint — N/A si no hay Python
13. Check backwards compatibility
14. Report files changed
15. Report remaining risks

---

## Exists / Reuse

- Posicionamiento actual: [`README.md`](../../../README.md) (RAG-as-a-Service / AI Agent Platform).
- Roadmap técnico corto plazo: README sección 15.
- Auditoría y orden de fases: [`docs/platform/ZENT_PLATFORM_ROADMAP.md`](../../platform/ZENT_PLATFORM_ROADMAP.md).
- Portal actual (para la IA): [`portal/src/App.tsx`](../../../portal/src/App.tsx).
- Roles: `owner` / `admin` / `member` / `viewer` en [`02-rbac.sql`](../../../src/infrastructure/db_init/02-rbac.sql).
- Platform admin hoy: scope `admin:*` only.

## Gaps

- No hay `PRODUCT.md`, árbol de navegación de los dos productos, ni speaker notes de la presentación.
- El README mezcla “para developers” con visión de producto.

## Fuera de alcance

Código, migraciones, Stripe, Super Admin UI, Agent Builder, K8s.

---

### Task 1: Product brief

**Files:**

- Create: `docs/platform/PRODUCT.md`

**Interfaces:**

- Consumes: `ZENT_PLATFORM_ROADMAP.md` (posicionamiento y glosario)
- Produces: brief que las fases 01–02 copian para copy de UI

- [x] **Step 1: Inspeccionar** README secciones 1–2 y el roadmap (Current State + Posicionamiento).

- [x] **Step 2: Escribir `docs/platform/PRODUCT.md`** con exactamente estas secciones, sin TBD:

  1. **Qué es Zent** — una frase: *AI Data Platform / RAG-as-a-Service para empresas*.
  2. **Qué no es** — no es un chatbot genérico con PDFs.
  3. **Cadena de valor** — Data (SQL/PDF/CSV/Excel/API/Web/S3) → Knowledge → Agent → Chat / API / Widget.
  4. **Dos productos** — Customer Portal vs Control Center; mismo `/api/v1`.
  5. **Glosario** — Organization, platform admin, organization admin, entitlement, knowledge base, agent, source, embed.
  6. **Promesa de demo** — “Turn your business data into an AI workforce.”
  7. **Fuentes in-scope hoy vs después** — hoy: tipos del registry; después: Drive, SharePoint, ERP/CRM (Fase 12).

- [x] **Step 3: Verificar** que el brief no contradice el README (sigue siendo RAG-as-a-Service; no se renombra el paquete Python ni los SDKs).

- [ ] **Step 4: Commit** (si el usuario pidió commit)

```bash
git add docs/platform/PRODUCT.md
git commit -m "docs: freeze Zent product positioning for SaaS phases"
```

---

### Task 2: Information architecture

**Files:**

- Create: `docs/platform/INFORMATION_ARCHITECTURE.md`

**Interfaces:**

- Consumes: rutas actuales de `portal/src/App.tsx` y APIs de `src/api/main.py`
- Produces: árboles de nav que la Fase 01 y 02 implementan

- [x] **Step 1: Escribir el árbol Customer Portal** (nombres en español, paths en inglés):

```
Chat                         /chat
Knowledge
  Sources                    /knowledge/sources
  Collections                 /knowledge/collections
  Documents                  /knowledge/documents
  SQL Sources                /knowledge/sql
  Sync Jobs                  /knowledge/jobs
  Search Playground          /knowledge/playground
Workspace
  Projects                   /projects
  Agents                     /agents
  Connectors                 /connectors
  Prompts                    /prompts
Account
  Users                      /users
  API Keys                   /keys
  Usage                      /usage
  Billing                    /billing
  Audit                      /audit
  Settings                   /settings
```

Redirects: `/ingestion` → `/knowledge/sql`; `/knowledge-bases` → `/knowledge/collections`.

- [x] **Step 2: Escribir el árbol Control Center** (`/admin`):

```
Dashboard                    /admin
Customers                    /admin/customers
  :orgId                     /admin/customers/:orgId
Billing                      /admin/billing
Plans                        /admin/plans
Usage / costs                /admin/usage
Audit (platform)             /admin/audit
```

Impersonate, pause, suspend viven en la ficha `:orgId`, no como nav top-level.

- [x] **Step 3: Documentar roles de UI**

  - Customer: `owner` / `admin` / `member` / `viewer` (nav gated en Fase 01).
  - Control Center: solo `is_platform_admin` (Fase 02). Un `owner` de ACME **no** entra a `/admin`.

- [ ] **Step 4: Commit** si aplica.

---

### Task 3: Presentation outline

**Files:**

- Create: `docs/platform/PRESENTATION.md`

- [x] **Step 1: Escribir 10 slides** con título + 3–6 bullets de speaker notes (no diseño gráfico):

  1. Zent — Turn your business data into an AI workforce.
  2. The problem — ERP, CRM, SQL, Excel, PDF fragmentados.
  3. The solution — Data → Zent → Knowledge → Agents → Answers.
  4. Architecture — Frontend → API → RAG (SQL / Qdrant / LLM).
  5. Customer Experience — Dashboard, Knowledge, Agent, Chat, API.
  6. Business Control — Control Center (customers, subscriptions, revenue).
  7. AI Economics — ejemplo $299 revenue vs costes LLM/embed/infra/storage.
  8. Security — multi-tenant, RBAC, encryption, audit, keys, rate limits.
  9. Scale — 1 → 100 → 1 000 customers → enterprise.
  10. Close — One platform. Every business. Its own AI.

- [x] **Step 2: Añadir “qué pantalla enseñar”** por slide 5 y 6 (rutas del Task 2). Marcar qué slides **no** se pueden demo hasta Fase 01/02/05/08.

- [ ] **Step 3: Commit** si aplica.

---

### Task 4: README pointer

**Files:**

- Modify: `README.md` (una fila en la tabla de documentación, sección 16)
- Modify: `docs/developers/README.md` si el enlace al roadmap aún no está

- [x] **Step 1: Añadir** enlace a `docs/platform/ZENT_PLATFORM_ROADMAP.md` y a `docs/platform/PRODUCT.md` sin reescribir el README.

- [x] **Step 2: Confirmar** que la sección 15 del README no contradice el orden de fases (puede decir “detalle en ZENT_PLATFORM_ROADMAP”).

---

## Criterios de aceptación

- Existen `PRODUCT.md`, `INFORMATION_ARCHITECTURE.md`, `PRESENTATION.md`.
- Ningún “TBD” / “TODO” en esos archivos.
- Cero cambios en `src/` y `portal/src/`.
- El glosario usa Organization = tenant; platform admin ≠ organization admin.

## Comandos

No hay tests nuevos. Si se tocó Python por error:

```bash
ruff check src/ tests/ sdk/python
pytest tests/test_architecture.py -q
```

Expected: PASS, o no corridos si el diff es solo `docs/`.

## Riesgos residuales

- Copy de producto en inglés (slides) vs portal en español: intencional (presentación vs producto).
- La IA de nav puede ajustarse en Fase 01 si una ruta no tiene API; documentar el desvío en el PR de 01, no reabrir el brief.
