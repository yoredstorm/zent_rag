# Fase 02 — Super Admin (Zent Control Center) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> Índice: [`docs/platform/ZENT_PLATFORM_ROADMAP.md`](../../platform/ZENT_PLATFORM_ROADMAP.md)

**Goal:** Dar al dueño de Zent un Control Center en `/admin` con sesión de platform admin (no API key), métricas reales, ficha de cliente y acciones de suscripción, incluyendo impersonate auditado.

**Architecture:** Mismo Vite app, layout distinto. Backend: identidad de plataforma **additive** sobre `TenantContext` / sesiones. Las rutas de listado cross-tenant ya existen bajo `require_platform_admin` + key `admin:*`; hay que aceptar **también** sesión `typ=platform`. No mezclar un `owner` de tenant en el control plane.

**Tech Stack:** FastAPI, AES-GCM sessions, Postgres, React, pytest.

## Global Constraints

- No reescribir billing, RAG, ni el portal customer (salvo links “back”).
- Identidad de tenant solo del Bearer para rutas de tenant. Platform admin **no** usa `X-Organization-Id` para “ser” un customer salvo impersonate explícito.
- API `1.0.0` additive only.
- `core/` no importa `infrastructure` ni FastAPI.
- Copy del portal en español.
- Tests: `pytest`. Lint: `ruff check src/ tests/ sdk/python`.
- Migraciones: `013+` (si 01 usó 013, esta es `014_platform_admin.py`).
- No Stripe, no entitlements engine, no K8s.
- **Impersonate sin audit es un bug de seguridad, no un follow-up.**

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

- `TenantContext.is_platform_admin()` → `"admin:*" in scopes` only ([`entities.py`](../../../src/core/domain/entities.py)).
- `require_platform_admin` ([`policy.py`](../../../src/platform/rbac/policy.py)).
- Billing admin: `GET /api/v1/billing/admin/subscriptions`, `GET /admin/organizations`, `DELETE /admin/subscriptions/{id}` ([`billing.py`](../../../src/api/routes/billing.py)).
- Comentario en billing: sesiones portal **no** son platform admin.
- Session payload: `user_id`, `organization_id`, `typ="portal"` ([`session.py`](../../../src/platform/auth/session.py)).
- Audit: [`AuditLogService`](../../../src/platform/audit/service.py) escribe con `ctx.tenant_id` — impersonate debe registrar **org objetivo + actor platform** (metadata), no falsear el tenant del actor.
- Tests: `tests/test_billing.py`, `tests/test_identity_hardening.py`, `tests/test_tenant_isolation.py`.

## Gaps

- No hay login de platform admin en el portal.
- `SessionPayload.organization_id` es obligatorio — hay que soportar `typ="platform"` con `organization_id` nulo **o** un org sentinel de plataforma documentado. Preferir **UUID nil prohibido**; usar `organization_id: UUID | None` solo si `typ=="platform"`.
- No hay métricas MRR/ARR en API.
- No hay impersonate, pause, suspend, reset usage como producto.

## Diseño de identidad (obligatorio)

Elegir **una** y no mezclar:

**Recomendado:** columna `users.is_platform_admin BOOLEAN NOT NULL DEFAULT false`. Seed **un** usuario vía SQL de init + env `PLATFORM_ADMIN_EMAIL` (no commitear password). Login `POST /api/v1/auth/platform/login` {email, password} → sesión `typ="platform"` y `scopes` incluye `admin:*` **solo** en el contexto in-memory, no como API key persistida.

`TenantContext` para platform:

- `tenant_id`: no usar un org de cliente. Para rutas `/api/v1/platform/*` el middleware establece un contexto de plataforma.
- `is_platform_admin()`: `typ=="platform"` **o** `"admin:*" in scopes` (keys de máquina siguen funcionando).

Rutas `/api/v1/admin/prompt` y SQL runner son **org-admin**, no Control Center. No moverlas bajo `/admin` del frontend de plataforma.

Impersonate: emite una sesión portal **corta** (TTL ≤ 1h) del org objetivo, `sid` nuevo, audit `platform.impersonate` con `actor_user_id`, `target_organization_id`, IP. El Control Center no “pinta” datos de otro tenant sin este token.

---

### Task 1: Platform session + policy

**Files:**

- Modify: `src/core/domain/entities.py` (`is_platform_admin`, quizá `auth_type`)
- Modify: `src/platform/auth/session.py` (`SessionPayload`)
- Modify: `src/api/tenant_middleware.py`
- Modify: `src/platform/rbac/policy.py`
- Modify: `src/api/routes/auth.py`
- Migration: `014_platform_admin.py` (o 013 si 01 no corrió — **detectar** el último revision)
- Test: `tests/test_identity_hardening.py`, nuevo `tests/test_platform_admin.py`

- [ ] **Step 1: Tests que fallen**

  1. Sesión portal owner de org A llama `GET /api/v1/billing/admin/organizations` → 403.
  2. API key `admin:*` sigue 200 (regresión).
  3. Platform session → 200.
  4. Spoof `X-Organization-Id` en platform session no lista otra cosa ni eleva a tenant.

- [ ] **Step 2: Implementar** login platform + middleware. Passwords bcrypt igual que portal.

- [ ] **Step 3:** `pytest tests/test_platform_admin.py tests/test_identity_hardening.py tests/test_tenant_isolation.py -q` — PASS.

---

### Task 2: Platform metrics + customer actions API

**Files:**

- Create: `src/api/routes/platform.py` (router prefix `/api/v1/platform`)
- Modify: `src/api/main.py` (include_router)
- Modify: `src/api/routes/billing.py` (pause/suspend/reset) **o** poner acciones en `platform.py` que usen `BillingService`
- Test: `tests/test_platform_admin.py`

**Interfaces:**

```python
# GET /api/v1/platform/metrics
# {
#   "mrr_cents": int,          # suma price del plan * subs active|trialing (monthly); annual/12
#   "arr_cents": int,           # mrr * 12
#   "customers": int,         # orgs with sub active|trialing
#   "active_agents": int,
#   "ai_requests_30d": int,
#   "llm_cost_30d": float,    # SUM(usage_events.estimated_cost) 30d
#   "gross_margin_pct": float | null  # null si coste o mrr es 0
# }

# GET /api/v1/platform/organizations
# reusa datos de GET /billing/admin/organizations; no duplicar si se puede alias

# GET /api/v1/platform/organizations/{id}
# ficha: plan, status, started, mrr_cents, users, agents, requests_30d, ai_cost_30d, margin

# POST /api/v1/platform/organizations/{id}/plan        { "plan_name": str }
# POST /api/v1/platform/organizations/{id}/pause
# POST /api/v1/platform/organizations/{id}/suspend
# POST /api/v1/platform/organizations/{id}/cancel     # wrap existing cancel semantics
# POST /api/v1/platform/organizations/{id}/usage/reset
# POST /api/v1/platform/organizations/{id}/impersonate  # { "expires_seconds": int } → { "access_token": str }
```

MRR: calcular de `plans.price_monthly_cents` / `price_annual_cents` y `subscriptions.billing_interval` **reales**. No hardcodear $12840.

Reset usage: resetear contador del ciclo actual (`request_quota` / Redis usage) **solo** el org path; test de que org B no se resetea.

- [ ] **Step 1: Tests** de métricas con dos orgs (números derivados, no snapshots mágicos salvo fixtures).

- [ ] **Step 2: Implementar** queries SQL con filtros explícitos. Impersonate + audit.

- [ ] **Step 3: pytest** + confirmar DELETE admin subscription sigue igual.

---

### Task 3: Control Center UI

**Files:**

- Create: `portal/src/pages/admin/AdminLayout.tsx`, `Dashboard.tsx`, `Customers.tsx`, `CustomerDetail.tsx`
- Modify: `portal/src/App.tsx` — rutas `/admin`, `/admin/login`, `/admin/customers`, `/admin/customers/:orgId`
- Create: `portal/src/platformAuth.tsx` (sesión **separada** de `rag_portal_token` — p.ej. `rag_platform_token`)
- Modify: `portal/src/api.ts` si hace falta un client sin `X-Organization-Id` de customer

- [ ] **Step 1: Login** `/admin/login` → platform login. Un tenant user con sesión customer que visite `/admin` → redirect login admin, **no** ver datos.

- [ ] **Step 2: Dashboard** cards: MRR, ARR, CUSTOMERS, ACTIVE AGENTS, AI REQUESTS, LLM COST, GROSS MARGIN — del Task 2.

- [ ] **Step 3: Lista + ficha** con acciones. Confirmación modal para suspend/cancel/reset. Impersonate abre el Customer Portal (otra pestaña o swap de token) y banner “Estás impersonando {org}”.

- [ ] **Step 4: Shell** no muestra nav de Chat/Knowledge.

---

### Task 4: Docs

- Modify: `docs/developers/authentication.md` — platform login, impersonate, amenaza (owner ≠ platform).
- Modify: `.env.example` — `PLATFORM_ADMIN_EMAIL` (sin password real).

- [ ] **Step 1: Documentar** que `admin:*` keys siguen válidas para automatización.

- [ ] **Step 2: Lint + tests**

```bash
ruff check src/ tests/ sdk/python
pytest tests/test_platform_admin.py tests/test_identity_hardening.py tests/test_tenant_isolation.py tests/test_billing.py -q
```

Expected: PASS

---

## Criterios de aceptación

- Owner de ACME no entra al Control Center.
- Platform admin ve métricas calculadas de DB.
- Impersonate genera audit y token de corta duración.
- API key `admin:*` no se rompe.
- Customer Portal (Fase 01) no se degrada.

## Riesgos residuales

- `AuditLogService` atado a `ctx.tenant_id`: impersonate/platform actions necesitan `organization_id` del **recurso** en metadata o una tabla `platform_audit_logs`. Elegir una y testearla; no silenciar fallos de audit en impersonate (el servicio hoy tragá excepciones — **impersonate debe fallar si el audit no se escribe**, override puntual).
- Seed del primer platform admin en prod: proceso manual documentado.
