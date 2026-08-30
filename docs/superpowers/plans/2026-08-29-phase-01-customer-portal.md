# Fase 01 — Customer Portal 2.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> Índice: [`docs/platform/ZENT_PLATFORM_ROADMAP.md`](../../platform/ZENT_PLATFORM_ROADMAP.md)
> IA: [`docs/platform/INFORMATION_ARCHITECTURE.md`](../../platform/INFORMATION_ARCHITECTURE.md) (si Fase 00 ya corrió; si no, usar el árbol de ese plan).

**Goal:** Convertir el portal tenant existente en un Customer Portal SaaS demostrable: dashboard de producto, Knowledge Center unificado, billing de lectura, settings e invites, sin segundo frontend.

**Architecture:** Un solo app Vite en `portal/`. Nuevas rutas y un layout de nav agrupada. Backend solo additive (invites + campos extra en usage). Reusar APIs de billing, sources, jobs, KBs, ingestion, auth.

**Tech Stack:** React 19, React Router 7, Tailwind 4, Recharts, FastAPI, Alembic, pytest.

## Global Constraints

- No reescribir funcionalidad que ya funciona (chat, auth, keys, ingestión SQL, prompts).
- Identidad de tenant solo del Bearer; nunca `X-Organization-Id` ni `organization_id` del body.
- API pública permanece `1.0.0` (additive only).
- `core/` no importa `infrastructure` ni FastAPI.
- Copy del portal en español.
- Tests: `pytest`. Lint: `ruff check src/ tests/ sdk/python`.
- Migraciones Alembic: siguiente id `013+` (solo si invites necesitan tabla).
- `PAYMENT_PROVIDER=manual` sigue siendo el default. **No Stripe.**
- No Super Admin, no Agent Builder profundo, no widget, no K8s.

## Protocolo del agente (obligatorio)

1. Inspect existing architecture
2. Do not rewrite working functionality
3. Identify existing components
4. Design changes
5. Implement
6. Add migrations
7. Add tests
8. Update API
9. Update frontend
10. Update documentation
11. Run tests
12. Run lint
13. Check backwards compatibility
14. Report files changed
15. Report remaining risks

---

## Exists / Reuse

| Pieza | Path |
|---|---|
| Router y nav | `portal/src/App.tsx` |
| Dashboard | `portal/src/pages/Dashboard.tsx`, `portal/src/components/UsageChart.tsx` |
| Usage | `portal/src/pages/Usage.tsx` — `GET /api/v1/billing/usage` |
| Ingestión SQL | `portal/src/pages/Ingestion.tsx`, `GET /api/v1/ingestion/sources` |
| KBs | `portal/src/pages/KnowledgeBases.tsx`, `/api/v1/knowledge-bases` |
| Sources API | `src/api/routes/sources.py` — tipos `sql\|file\|csv\|excel\|web\|s3\|api` |
| Jobs | `src/api/routes/jobs.py` |
| Billing | `GET /plans`, `/subscription`, `/usage`, `/invoices` en `src/api/routes/billing.py` |
| Users | `portal/src/pages/Users.tsx`; `InviteUserRequest` **sin ruta** en `organizations.py` |
| Auth | `portal/src/auth.tsx`, `src/api/routes/auth.py` |
| Memberships | `src/api/routes/organizations.py` |
| Plan limits users | `check_resource_limit(..., "users")` |

## Gaps

- Dashboard: faltan tokens, chunks, coste, errores, top users/queries, greeting “Good afternoon, {company}”.
- Knowledge no unificado; KBs/connectors son CRUD plano.
- No hay `/billing` ni `/settings`.
- No hay invite (el Pydantic model está muerto).
- Nav de 12 ítems planos; roles de `/auth/me` no gaten el menú.

---

### Task 1: Usage dashboard payload (backend)

**Files:**

- Modify: `src/api/routes/billing.py` (`GET /usage`)
- Modify: `src/platform/usage/usage_engine.py` o el agregador que ya alimenta `/usage`
- Test: `tests/test_billing.py` o `tests/test_usage_engine.py` (el que ya cubre `/usage`)

**Interfaces:**

- Consumes: `usage_events` (tokens, latency_ms, status, user_id)
- Produces: JSON additive, ejemplo:

```python
{
  "totals": {
    "requests": int,
    "tokens": int,
    "avg_latency_ms": float,
    "errors": int,          # NEW
    "estimated_cost": float  # NEW, 0.0 si no hay pricing
  },
  "daily": [...],  # existing + optional errors/cost per day
  "recent": [...],
  "top_users": [{"user_id": str, "requests": int}],  # NEW, max 5
  "top_queries": [{"query_preview": str, "count": int}],  # NEW if data exists; else []
}
```

Si `top_queries` no tiene tabla, devolver `[]` — no inventar un warehouse.

- [ ] **Step 1: Escribir test que falle** en el cliente HTTP de billing/usage: `assert "errors" in body["totals"]` y `assert "top_users" in body`.

- [ ] **Step 2: Correr el test**

```bash
pytest tests/test_billing.py -k usage -q
```

Expected: FAIL (key missing) o adaptar el nombre del test file real.

- [ ] **Step 3: Implementar** agregaciones SQL **siempre** filtradas por `organization_id` del `TenantContext`. Errores = `usage_events.status` distinto de `completed` (confirmar valores reales en el engine; no asumir).

- [ ] **Step 4: Correr tests de billing + tenant isolation**

```bash
pytest tests/test_billing.py tests/test_tenant_isolation.py tests/test_usage_engine.py -q
```

Expected: PASS

- [ ] **Step 5: Commit** si el usuario lo pidió.

---

### Task 2: Invitations API

**Files:**

- Create: `src/infrastructure/db_init/versions/013_org_invites.py`
- Create or modify: `src/infrastructure/db_init/16-org-invites.sql` (fresco)
- Modify: `src/api/routes/organizations.py`
- Test: `tests/test_auth.py` o nuevo `tests/test_org_invites.py`

**Interfaces:**

- Produces:

```python
# POST /api/v1/organizations/invites
# permission: users:write
# body: { "email": str, "role": "owner|admin|member|viewer" }
# 201: { "id": uuid, "email": str, "role": str, "status": "pending", "expires_at": iso }

# GET /api/v1/organizations/invites
# POST /api/v1/organizations/invites/{id}/accept  (auth: signup or logged-in matching email)
```

Tabla `organization_invites`: `id`, `organization_id`, `email`, `role`, `token_hash`, `expires_at`, `accepted_at`, `created_by_user_id`.

- [ ] **Step 1: Test** — owner invita; el invitado no ve datos de otra org; duplicate email → 409; plan limit users → 409 `plan_limit_reached` vía `check_resource_limit`.

- [ ] **Step 2: Migración 013** + endpoint. **No** enviar email real (no hay mailer): devolver el token **una vez** en el 201 (igual que API keys) o documentar “copiar enlace” en UI. No loguear el token en claro.

- [ ] **Step 3: Audit** `invite.created` / `invite.accepted` vía `AuditLogService`.

- [ ] **Step 4: pytest** isolation + invites. Expected: PASS.

---

### Task 3: Knowledge Center (frontend + thin API glue)

**Files:**

- Create: `portal/src/pages/knowledge/Sources.tsx`, `Collections.tsx`, `Documents.tsx`, `SqlSources.tsx`, `Jobs.tsx`, `Playground.tsx`
- Modify: `portal/src/App.tsx` (rutas + redirects)
- Reuse: `Ingestion.tsx` lógica → `SqlSources.tsx` (mover, no duplicar sync)
- Modify: `KnowledgeBases.tsx` → Collections
- Optional backend: `GET /api/v1/sources` ya lista; documents vía `source_documents` si hay repo — si no hay listado, añadir `GET /api/v1/sources/{id}/documents` **additive** en `sources.py`

**Playground:** formulario query → `POST /api/v1/rag/query` (mismo que chat). Mostrar answer + sources. No nuevo orchestrator.

Columnas de Sources UI: Name, Type, Status, Last Sync, Rows/Chunks, Errors — mapear de `kb_sources` + `source_sync_state` + último job. Si un campo no existe, mostrar "—" y **añadir** el campo en el JSON del GET sources en vez de fake data.

- [ ] **Step 1: Inspeccionar** `_source_response` y job/sync payloads reales.

- [ ] **Step 2: Extender GET sources** (si falta last_sync / error_count) con test en `tests/test_knowledge_*.py`.

- [ ] **Step 3: Rutas React** y redirects `/ingestion` → `/knowledge/sql`, `/knowledge-bases` → `/knowledge/collections`.

- [ ] **Step 4: Nav agrupada** según IA. Mobile drawer debe listar los mismos grupos.

- [ ] **Step 5: Verificar** que Chat, Keys, Prompts, Audit siguen funcionando (rutas intactas).

---

### Task 4: Dashboard, Usage, Billing (read-only), Settings

**Files:**

- Modify: `portal/src/pages/Dashboard.tsx`
- Modify: `portal/src/pages/Usage.tsx` (añadir charts Recharts: requests + latency; reusar `UsageChart` o extraer)
- Create: `portal/src/pages/Billing.tsx` — plan, status, quota, lista de `GET /api/v1/billing/invoices`, `GET /api/v1/billing/plans` (sin checkout)
- Create: `portal/src/pages/Settings.tsx` — perfil org `GET/PUT /api/v1/organizations` (ya existe update)
- Modify: `portal/src/pages/Users.tsx` — formulario invite
- Modify: `portal/src/auth.tsx` — persistir roles de `/me` y ocultar nav (`users`, `keys`, `billing`, `prompts`) si el rol es `viewer`

Greeting dashboard:

```tsx
title={`Buenas tardes, ${session.companyName}.`}
```

(Usar franja horaria local para buenos días/tardes/noches.)

Cards: Plan, Usage bar, AI Requests, Tokens, Knowledge chunks (si hay métrica; si no, count de sources o `GET /billing/usage/storage`), API Health.

- [ ] **Step 1: Dashboard** consume el payload del Task 1. Sin números inventados.

- [ ] **Step 2: Billing page** — botones Upgrade/Cancel **deshabilitados** con texto “El pago self-service llega en una fase posterior” (Fase 04). Cancel API existe; no llamarla desde un botón primario sin confirmación. Preferir solo lectura en esta fase.

- [ ] **Step 3: Settings** — nombre/empresa/país; no password reset (Fase 07).

---

### Task 5: Docs + quality

**Files:**

- Modify: `docs/developers/README.md` (portal routes)
- Optional: `docs/developers/authentication.md` — invites

- [ ] **Step 1: Documentar** `POST /organizations/invites` y campos nuevos de `/usage`.

- [ ] **Step 2: Lint + tests**

```bash
ruff check src/ tests/ sdk/python
pytest tests/test_billing.py tests/test_auth.py tests/test_org_invites.py tests/test_tenant_isolation.py tests/test_knowledge_queue.py -q
```

Expected: PASS (omitir archivos que no existan; no skippear isolation).

- [ ] **Step 3: Reportar** archivos + riesgos.

---

## Criterios de aceptación

- Un usuario trial ve dashboard con plan, cuota, requests, tokens, health, y al menos un gráfico.
- Knowledge Center navega sources / collections / jobs / playground; ingestión SQL no se pierde.
- `/billing` muestra plan + invoices (aunque la lista esté vacía).
- Owner puede crear un invite; el modelo `InviteUserRequest` deja de estar muerto.
- Viewer no ve “Claves” ni “Usuarios” en nav.
- Ningún mock de MRR ni de Stripe.
- Chat streaming sigue igual.

## Riesgos residuales

- Dual path ingestion (legacy `/ingestion` vs Knowledge Platform): el redirect no borra la API legacy.
- `top_queries` puede quedar vacío hasta que exista persistencia de texto de query (privacy).
- Chunks count puede requerir Qdrant count filtrado por org — si es caro, mostrar storage de `/usage/storage` y documentarlo.
