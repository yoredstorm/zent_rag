# Fase 04 — Billing Real (Stripe) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> Índice: [`docs/platform/ZENT_PLATFORM_ROADMAP.md`](../../platform/ZENT_PLATFORM_ROADMAP.md)

**Goal:** Cobrar de verdad: adapter Stripe sobre el puerto `PaymentProvider` existente, checkout self-service, webhooks, invoices/payments alineados, sin tirar el provider `manual`.

**Architecture:** Flujo `Subscription → Entitlements → Usage → Invoice → Payment`. `get_payment_provider()` ya ramifica `manual` vs `stripe` ([`provider.py`](../../../src/infrastructure/billing/provider.py)). Implementar `StripePaymentProvider` en `src/infrastructure/billing/stripe_provider.py`. Extra opcional `[billing-stripe]` como el error actual indica. UI customer: upgrade/cancel reales; Control Center sigue pudiendo cambiar planes en manual/enterprise.

**Tech Stack:** Stripe API, FastAPI webhooks existentes `POST /api/v1/billing/webhooks/{provider}`, pytest con stubs (no red en CI).

## Global Constraints

- No eliminar `ManualPaymentProvider`.
- Identidad de tenant solo del Bearer.
- API `1.0.0` additive only.
- `core/` no importa Stripe ni FastAPI (el adapter vive en `infrastructure`).
- Copy del portal en español.
- Tests: `pytest`. Lint: `ruff check src/ tests/ sdk/python`.
- Migraciones: solo si falta columna; las de provider **ya existen**.
- Default `PAYMENT_PROVIDER=manual` en `.env.example` y Compose. Stripe es opt-in.
- No K8s, no widget, no FinOps dashboard (08).

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

- Puerto: [`src/core/ports/payment_provider.py`](../../../src/core/ports/payment_provider.py) — `create_checkout_session`, `verify_webhook_signature`, `cancel_subscription`.
- Manual + HMAC: [`manual_provider.py`](../../../src/infrastructure/billing/manual_provider.py).
- Webhooks: [`src/api/routes/billing_webhooks.py`](../../../src/api/routes/billing_webhooks.py), [`src/platform/billing/webhooks.py`](../../../src/platform/billing/webhooks.py).
- Tests: [`tests/test_billing_webhooks.py`](../../../tests/test_billing_webhooks.py).
- Upgrade: `POST /api/v1/billing/subscription/upgrade` gated por `SELF_SERVICE_UPGRADE_ENABLED`.
- Invoices/payments tables + [`invoices.py`](../../../src/platform/billing/invoices.py).
- Settings: `PAYMENT_PROVIDER`, `SELF_SERVICE_UPGRADE_ENABLED` en [`config.py`](../../../src/core/config.py).
- Docs: [`docs/developers/webhooks.md`](../../developers/webhooks.md).

## Gaps

- `get_payment_provider()` raise si `stripe`.
- Customer Billing UI (Fase 01) tiene upgrade deshabilitado.
- Trial → paid sin tarjeta.

## Diseño Stripe

- Products/Prices: mapear `plans.name` → Price IDs por **settings** o tabla `plan_provider_prices (plan_id, interval, provider, price_id)` — preferir tabla para no redeploy al cambiar Price.
- Checkout: `mode=subscription`, `client_reference_id` o metadata `organization_id` (UUID). El webhook **no** confía en el body del browser.
- Eventos: `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.paid`, `invoice.payment_failed`. Idempotencia: `billing_events (provider, event_id)` ya UNIQUE.
- `past_due` / `suspended` según Stripe; no inventar estados fuera del CHECK de `subscriptions`.
- Enterprise: sigue `manual` + Control Center; no forzar Checkout.

Secrets: `BILLING_STRIPE_SECRET_KEY`, `BILLING_STRIPE_WEBHOOK_SECRET` — solo env, nunca el repo.

---

### Task 1: Stripe adapter + tests de firma

**Files:**

- Create: `src/infrastructure/billing/stripe_provider.py`
- Modify: `src/infrastructure/billing/provider.py` — instanciar adapter en vez de raise
- Modify: `pyproject.toml` extra `billing-stripe`
- Modify: `.env.example`
- Test: `tests/test_billing_webhooks.py` (vector Stripe-Signature) + `tests/test_stripe_provider.py` con httpx mock / stripe mock

- [ ] **Step 1: Test** `verify_webhook_signature` rechaza body tampered; acepta fixture firmado (construir HMAC como Stripe: `t=,v1=`).

- [ ] **Step 2: Implementar** `StripePaymentProvider` sin I/O real en unit tests.

- [ ] **Step 3:** `PAYMENT_PROVIDER=manual` en CI **sin** extra instalado debe seguir pasando toda la suite.

---

### Task 2: Checkout + webhook application

**Files:**

- Modify: `src/platform/billing/webhooks.py` — aplicar eventos a `subscriptions` / `invoices` / `payments`
- Modify: `src/api/routes/billing.py` — `POST /api/v1/billing/checkout` { `plan_name`, `interval`: `monthly|annual` }
- Modify: `src/platform/billing/service.py` — upgrade: si Stripe y flag on, crear checkout en vez de cambiar plan directo
- Test: `tests/test_billing.py`, `tests/test_billing_webhooks.py`

**Interfaces:**

```python
# POST /api/v1/billing/checkout
# permission: billing:write
# 201: { "checkout_url": str, "session_id": str }
# 409 si plan no público o enterprise-only
```

- [ ] **Step 1: Test** checkout no cambia el plan hasta webhook; webhook `completed` deja `status=active` y `provider_subscription_id`.

- [ ] **Step 2: Test** replay del mismo `event_id` no duplica payment.

- [ ] **Step 3: Test** org A webhook no muta org B (metadata org mismatch → 400, no update).

- [ ] **Step 4: Entitlements** (Fase 03) se recargan al cambiar `plan_id`. Escribir `subscription_events`.

---

### Task 3: Customer + admin UI

**Files:**

- Modify: `portal/src/pages/Billing.tsx` — planes, CTA checkout (abre `checkout_url`), cancel con confirmación (`POST /subscription/cancel`)
- Modify: env portal no necesita secret Stripe (solo API)
- Modify: Control Center customer detail — badge `payment_provider`

Cuando `SELF_SERVICE_UPGRADE_ENABLED=false`, la UI muestra “Contactar a Zent” (manual). Cuando true y Stripe configurado, habilitar botones.

- [ ] **Step 1: Quitar** el copy de “fase posterior” si el flag está on.

- [ ] **Step 2: Invoices** ya listadas en 01 — mostrar status `paid` tras webhook (test de contrato JSON).

---

### Task 4: Docs + flag

- [`docs/developers/webhooks.md`](../../developers/webhooks.md) — Stripe-Signature, eventos, idempotencia.
- README sección 15: tachar “Stripe como payment provider” o apuntar a este plan como hecho **solo cuando el código exista** (el agente de esta fase actualiza el README al cerrar).
- Documentar: tests locales con Stripe CLI no son requisito de CI.

```bash
ruff check src/ tests/ sdk/python
pytest tests/test_billing.py tests/test_billing_webhooks.py tests/test_entitlements.py tests/test_tenant_isolation.py -q
```

Expected: PASS

---

## Criterios de aceptación

- `PAYMENT_PROVIDER=manual` : comportamiento idéntico a hoy.
- Con Stripe + flag: tenant puede obtener `checkout_url`; tras evento verificado, plan y entitlements coinciden.
- Firma inválida → 400; event replay seguro.
- No hay secretos en git.

## Riesgos residuales

- Impuestos/VAT/dunning: fuera de alcance; Stripe Tax después.
- Annual vs monthly Price IDs mal mapeados: tests de tabla `plan_provider_prices`.
- Webhook antes que `create_checkout_session` persista org: usar metadata obligatorio y rechazar si falta.
