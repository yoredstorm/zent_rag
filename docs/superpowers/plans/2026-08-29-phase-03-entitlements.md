# Fase 03 — Subscriptions and Entitlements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> Índice: [`docs/platform/ZENT_PLATFORM_ROADMAP.md`](../../platform/ZENT_PLATFORM_ROADMAP.md)

**Goal:** Hacer que los planes sean configurables sin cambiar código: un motor de entitlements (feature/limit/value) que sustituya `plans.features` JSON y las columnas sueltas como única fuente de verdad, reutilizando `plans` / `subscriptions` / `check_resource_limit`.

**Architecture:** Tabla `plan_entitlements` + función única `check_entitlement(organization_id, key)`. `plan_limits.py` y creación de agents/KBs/connectors/users delegan ahí. `plans.features` queda como **display opcional** sincronizado o deprecado en docs (no borrar columna). Super Admin (Fase 02) edita entitlements; el Customer Portal lee `GET /entitlements`.

**Tech Stack:** Postgres, Alembic, FastAPI, pytest. UI admin mínima en Control Center.

## Global Constraints

- No reemplazar tablas `plans` ni `subscriptions`.
- Identidad de tenant solo del Bearer.
- API `1.0.0` additive only.
- `core/` no importa `infrastructure` ni FastAPI.
- Copy del portal en español.
- Tests: `pytest`. Lint: `ruff check src/ tests/ sdk/python`.
- Migraciones: siguiente revision (`015` típico).
- No Stripe (Fase 04). No widget. `PAYMENT_PROVIDER=manual`.

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

- `plans` columnas: `requests_per_month`, `max_users_per_organization`, `max_agents`, `max_knowledge_bases`, `max_connectors`, overage_*, `features JSONB` ([`03-billing.sql`](../../../src/infrastructure/db_init/03-billing.sql), [`14-billing-platform.sql`](../../../src/infrastructure/db_init/14-billing-platform.sql)).
- Enforcement: [`src/platform/billing/plan_limits.py`](../../../src/platform/billing/plan_limits.py) — keys `agents|knowledge_bases|connectors|users`.
- Cuota requests: middleware + `request_quota`.
- Seeds: trial / starter / pro / enterprise.
- Admin org list: platform routes de Fase 02.
- Tests: `tests/test_billing_limits_api.py`, `tests/test_billing.py`.

## Gaps

- Features comerciales (SSO, embed, custom models) no se enforcean.
- Cambiar un límite implica ALTER o deploy de seeds.
- No hay `subscription_events` de negocio (sí `billing_events` de webhooks).

## Modelo de datos

```sql
CREATE TABLE plan_entitlements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id UUID NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
    key VARCHAR(80) NOT NULL,
    value_type VARCHAR(20) NOT NULL CHECK (value_type IN ('bool', 'int', 'bigint')),
    value_bool BOOLEAN,
    value_int BIGINT,
    UNIQUE (plan_id, key)
);
```

Keys **estables** (seed para los 4 planes):

| key | type | significado |
|---|---|---|
| `monthly_requests` | int | cuota (NULL = ilimitado) |
| `max_users` | int | |
| `max_agents` | int | |
| `max_knowledge_bases` | int | |
| `max_connectors` | int | |
| `max_documents` | int | opcional; si no hay count fiable, omitir seed y no enforcar |
| `api_access` | bool | |
| `custom_models` | bool | |
| `embed_widget` | bool | default false excepto pro/enterprise |
| `eval_ui` | bool | |
| `sso` | bool | false hasta Fase 07; el key existe para no migrar después |

Backfill: copiar columnas actuales de `plans` a filas entitlement en la migración. **No** borrar columnas de `plans` en esta fase (el código viejo puede leerlas hasta que `check_resource_limit` lea entitlements).

`subscription_events`: `id`, `subscription_id`, `organization_id`, `event_type` (`created|plan_changed|paused|suspended|canceled|usage_reset`), `from_plan_id`, `to_plan_id`, `actor_user_id`, `created_at`. Escribir desde las acciones de Fase 02 y upgrade.

---

### Task 1: Schema + seed + domain helper

**Files:**

- Create: `src/platform/billing/entitlements.py` — `get_entitlements(org_id) -> dict[str, bool | int | None]`, `check_entitlement(org_id, key, *, increment=0)`
- Create: migration `015_plan_entitlements.py` + SQL fresco
- Modify: `plan_limits.py` para llamar `check_entitlement` mapeando `agents` → `max_agents`, etc.
- Test: `tests/test_entitlements.py`

**Interfaces:**

```python
class EntitlementDenied(Exception):
    def __init__(self, key: str, limit: int | None, current: int | None = None): ...

async def check_entitlement(organization_id: UUID, key: str) -> None:
    """Bool false → EntitlementDenied. Int: same semantics as PlanLimitError (NULL unlimited)."""

async def get_org_entitlements(organization_id: UUID) -> dict[str, object]: ...
```

- [ ] **Step 1: Test** — org en trial no puede `embed_widget`; org con `max_agents=1` que ya tiene 1 agente falla el segundo create (via API existente).

- [ ] **Step 2: Migración + backfill**. Idempotente.

- [ ] **Step 3: `create_agent` / KB / connector / invite** siguen devolviendo 409 `plan_limit_reached` (mismo error_code). Internamente entitlements.

- [ ] **Step 4: pytest** `tests/test_entitlements.py tests/test_billing_limits_api.py tests/test_agent_api.py -q` — PASS.

---

### Task 2: API

**Files:**

- Modify: `src/api/routes/billing.py`
- Modify: `src/api/routes/platform.py` (si existe de Fase 02) para CRUD entitlements de un plan

```python
# GET /api/v1/billing/entitlements
# org-scoped, permission billing:read
# { "plan_name": str, "entitlements": { "max_agents": 3, "embed_widget": false, ... } }

# PUT /api/v1/platform/plans/{plan_id}/entitlements
# platform admin
# body: { "entitlements": [ { "key": "max_agents", "value_type": "int", "value_int": 10 } ] }
```

- [ ] **Step 1: Tests** — tenant no puede PUT platform entitlements; platform sí; GET tenant solo su plan.

- [ ] **Step 2: Implementar**. Cache: si hay cache Redis de límites, invalidar al PUT.

---

### Task 3: UI

**Files:**

- Create: `portal/src/pages/admin/Plans.tsx` — tabla de planes + editor de entitlements
- Modify: Customer `Billing.tsx` (Fase 01) — mostrar entitlements (checks y números), no el JSON crudo `features`
- Modify: `portal/src/App.tsx` — `/admin/plans`

- [ ] **Step 1: Control Center** edita `max_agents` de starter, guarda, un tenant starter no crea el agente N+1.

- [ ] **Step 2: Customer billing** lista límites en español.

---

### Task 4: subscription_events + docs

- Escribir evento en change plan / pause / suspend / cancel / reset (hooks existentes).
- `docs/developers/usage.md` — entitlements vs quota de requests.
- `GET /plans` puede incluir `entitlements` additive; no quitar `features`.

```bash
ruff check src/ tests/ sdk/python
pytest tests/test_entitlements.py tests/test_billing_limits_api.py tests/test_billing.py tests/test_platform_admin.py -q
```

Expected: PASS

---

## Criterios de aceptación

- Un límite de plan se cambia desde Control Center **sin** ALTER TABLE.
- `plans.features` no es lo que el backend enforca.
- Crear recursos sigue el mismo 409.
- Trial/starter/pro/enterprise tienen seeds de entitlements coherentes con las columnas actuales.

## Fuera de alcance

Stripe, overage invoicing nuevo, feature flags de infra (LaunchDarkly), SSO real.

## Riesgos residuales

- Doble fuente durante transición (columnas `plans.*` vs entitlements): documentar que `check_entitlement` gana. Lectura de columnas solo para backfill.
- `monthly_requests` duplica `request_quota`: el middleware debe seguir siendo la puerta de requests; entitlement es la fuente del número.
