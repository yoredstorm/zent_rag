# FinOps — revenue vs coste

Números derivados de `usage_events`, `invoices`, `subscriptions` y `plans`. No hay mocks ni cifras de demo en producción.

## Endpoints (platform admin)

- `GET /api/v1/platform/finops/summary`
- `GET /api/v1/platform/finops/organizations/{id}`

Query opcional: `start`, `end` (ISO-8601). Default: últimos 30 días. Máximo 366 días.

El tenant **no** puede leer estos endpoints (403 `platform_admin_required`). En `GET /api/v1/billing/usage` ve `estimated_costs` (llm / embedding / storage) de **su** org. No incluye infra de Zent ni margen.

## Cash vs MRR

| Campo | Definición |
|---|---|
| `revenue_cents` | Suma de `invoices.total_cents` con `status = paid` y `paid_at` en el periodo. **Cash**, no MRR. |
| `revenue_basis` | Siempre `invoices_paid` en esta fase. |
| `mrr_cents` | Nota de run-rate: planes de suscripciones `active` + `trialing` (anual / 12). No se suma al cash. |

Un customer con plan de $299 y sin factura pagada en el periodo muestra `revenue_cents = 0` y `subscription_price_cents` / `mrr_cents` = 29900.

## Costes

| Bucket | Fuente |
|---|---|
| `llm` | `usage_events` clasificados como LLM: `COALESCE(actual_cost, estimated_cost)`. |
| `embedding` | Eventos solo de embedding (`embedding_tokens > 0` sin prompt/completion, o modelo `embed` / `bge` / `e5-`). |
| `storage` | Puntos Qdrant × `VECTOR_DIMENSION` × 4 bytes / GB × `plans.overage_storage_cost_per_gb`. 0 si Qdrant no responde o el plan no tiene overage. |
| `infra` | `RAG_FINOPS_INFRA_COST_PER_ORG_MONTH_CENTS` × orgs activas × (días del periodo / 30). Rate configurable, no telemetría inventada. Default 0. |

`estimated_cost` es **estimado interno** (pricing registry). Puede desfasarse de la factura del provider.

## Margen

```
gross_profit = revenue_cents/100 − (llm + embedding + storage + infra)
gross_margin_pct = gross_profit / (revenue_cents/100) × 100   # null si revenue = 0
```

## Customers (solo summary)

- `new`: organizaciones con `created_at` en el periodo.
- `churned`: suscripciones `canceled` con `canceled_at` en el periodo.
- `arpu_cents`: `revenue_cents / orgs con factura pagada` (null si nadie pagó).

Churn/expansion más finos dependen de `subscription_events` (Fase 03). Si `canceled_at` no está poblado, churn puede quedar en 0.

## UI

Control Center: `/admin/usage` (Ingresos / Costes / Economía AI). La ficha de cliente reutiliza el desglose por org.
