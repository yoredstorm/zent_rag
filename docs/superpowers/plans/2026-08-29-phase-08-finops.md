# Fase 08 — FinOps / AI Cost Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> Índice: [`docs/platform/ZENT_PLATFORM_ROADMAP.md`](../../platform/ZENT_PLATFORM_ROADMAP.md)

**Goal:** El dueño de Zent ve si el negocio funciona: revenue vs coste LLM/embeddings/storage/infra por customer, y métricas de AI economics. Números **derivados** de `usage_events`, `pricing_models`, `subscriptions`, `invoices` — no mocks.

**Architecture:** Capa de reporte en `src/platform/billing/` o `src/platform/finops/` que agrega. UI solo en Control Center (`/admin/usage`). Customer Portal puede ver **su** coste estimado (additive en usage) pero no el margen de Zent.

**Tech Stack:** SQL aggregations, pricing registry existente, React, pytest.

## Global Constraints

- No reescribir usage engine.
- Identidad: métricas de plataforma = platform admin; tenant solo su org.
- API `1.0.0` additive only.
- `core/` no importa `infrastructure` ni FastAPI.
- Copy del portal en español.
- Tests: `pytest`. Lint: `ruff check src/ tests/ sdk/python`.
- Infra “coste” que no está en `usage_events` (Postgres, Redis) se modela como **rate configurable** en settings (`FINOPS_INFRA_COST_PER_ORG_MONTH_CENTS`), no como telemetría inventada.

## Protocolo del agente (obligatorio)

1. Inspect existing architecture
2. Do not rewrite working functionality
3. Identify existing components
4. Design changes
5. Implement
6. Add migrations (solo si hace falta snapshot mensual)
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

- `usage_events.estimated_cost`, `actual_cost`, tokens, `event_type` ([`usage_engine.py`](../../../src/platform/usage/usage_engine.py)).
- `pricing_models` + `GET/PUT /api/v1/billing/pricing`.
- Fase 02 `GET /api/v1/platform/metrics` (MRR, llm_cost_30d).
- Invoices `total_cents`.

## Gaps

- No hay desglose LLM vs embedding vs storage vs infra.
- No hay margen por org ni ARPU/churn (churn puede ser count de `canceled` en el mes — definirlo).

## Modelo de reporte (contrato)

```python
# GET /api/v1/platform/finops/summary
{
  "period": {"start": iso, "end": iso},
  "revenue_cents": int,          # invoices paid in period OR MRR * months (documentar cuál; preferir invoices paid + active MRR note)
  "costs": {
    "llm": float,
    "embedding": float,
    "storage": float,
    "infra": float
  },
  "gross_profit": float,
  "gross_margin_pct": float | null,
  "customers": {"new": int, "churned": int, "arpu_cents": int | null}
}

# GET /api/v1/platform/finops/organizations/{id}
# same costs vs subscription price for that org
```

Clasificar `usage_events.event_type` / `model` en llm vs embedding (inspeccionar valores reales). Storage: reusar `/usage/storage` * precio `overage_storage` o `pricing_models`.

---

### Task 1: Engine + tests

- [ ] **Step 1: Tests** con fixtures de events + un invoice paid; margen calculable.
- [ ] **Step 2: Org A no aparece en finops de org B** (platform lista todas; tenant endpoint si existe solo self).
- [ ] **Step 3: Implementar** queries index-friendly (`organization_id, created_at`).

---

### Task 2: UI Control Center

- [ ] **Step 1:** `/admin/usage` — Revenue / Costs / AI Economics (cost/request, cost/customer, revenue/request, margin/customer).
- [ ] **Step 2:** Ficha customer (Fase 02) usa el mismo desglose (reemplazar llm_cost único si era grosero).

---

### Task 3: Docs

- Documentar fórmulas en `docs/platform/FINOPS.md` (cómo se calcula MRR vs cash).
- Slide 7 de presentación puede citar este endpoint.

```bash
ruff check src/ tests/ sdk/python
pytest tests/test_finops.py tests/test_platform_admin.py tests/test_usage_engine.py -q
```

Expected: PASS

## Criterios de aceptación

- Un org con $299 de plan y costes de usage conocidos muestra profit y % margen **reproducible** en test.
- Tenant no ve margen de la plataforma.
- Cero números hardcoded de demo en producción.

## Riesgos residuales

- `estimated_cost` puede estar desfasado de la factura del provider: documentar “estimado interno”.
- Churn/expansion incompletos sin `subscription_events` bien poblados (Fase 03).
